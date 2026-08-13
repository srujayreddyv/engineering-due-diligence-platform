"""Minimal machine-readable assessment, review, and decision interface."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Sequence, TextIO, Type

from .models import (
    Criticality,
    Environment,
    HumanDecisionDisposition,
    PolicyOutcome,
    RiskTolerance,
)
from .persistence import (
    SQLitePersistenceError,
    load_verified_assessment_evaluation_snapshot,
    load_verified_assessment_review,
    persist_human_decision_with_status,
)
from .request import REQUEST_DEFINITION_VERSION, AssessmentRequestInput
from .workflow import (
    AssessmentExecutionInput,
    AssessmentExecutionResult,
    AssessmentExecutionStatus,
    execute_assessment,
)


_OUTPUT_SCHEMA_VERSION = "assessment-cli-output.v1"
_REVIEW_OUTPUT_SCHEMA_VERSION = "assessment-review-cli-output.v1"
_DECISION_OUTPUT_SCHEMA_VERSION = "human-decision-cli-output.v1"
_USAGE_ERROR_MESSAGE = "The command arguments are invalid."
_INTERNAL_ERROR_MESSAGE = "The assessment could not be completed."
_REVIEW_INTERNAL_ERROR_MESSAGE = "The assessment review could not be loaded."
_DECISION_INTERNAL_ERROR_MESSAGE = "The human decision could not be recorded."
_DECISION_VALIDATION_ERROR_MESSAGE = "The human decision input is invalid."
_ACTOR_IDENTITY_ASSURANCE = "caller_asserted_not_authenticated"

_EXIT_COMPLETE = 0
_EXIT_INTERNAL = 1
_EXIT_USAGE = 2
_EXIT_INVALID_REQUEST = 3
_EXIT_COLLECTION_FAILED = 4
_EXIT_PERSISTENCE_FAILED = 5
_EXIT_CONFLICTING_DECISION = 6


class _CLIUsageError(Exception):
    """Internal signal for a sanitized command syntax failure."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CLIUsageError from None

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        raise _CLIUsageError from None


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _current_utc_time() -> datetime:
    return datetime.now(timezone.utc)


def _new_assessment_id() -> str:
    return "assessment-{}".format(str(_new_uuid()).lower())


def _integer_argument(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("invalid integer") from None


def _build_parser() -> _ArgumentParser:
    parser = _ArgumentParser(prog="engineering-due-diligence", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    assess = commands.add_parser("assess", add_help=False)
    assess.add_argument("--database", required=True)
    assess.add_argument("--repository", required=True)
    assess.add_argument("--intended-use", required=True)
    assess.add_argument("--environment", required=True)
    assess.add_argument("--criticality", required=True)
    assess.add_argument(
        "--expected-lifetime-days",
        required=True,
        type=_integer_argument,
    )
    assess.add_argument("--risk-tolerance", required=True)
    assess.add_argument("--submitted-by-actor-id", required=True)
    assess.add_argument("--responsible-reviewer-actor-id", required=True)

    review = commands.add_parser("review", add_help=False)
    review.add_argument("--database", required=True)
    review.add_argument("--assessment-id", required=True)

    decide = commands.add_parser("decide", add_help=False)
    decide.add_argument("--database", required=True)
    decide.add_argument("--assessment-id", required=True)
    decide.add_argument("--assessment-evaluation-id", required=True)
    decide.add_argument("--reviewer-actor-id", required=True)
    decide.add_argument("--decision", required=True)
    decide.add_argument("--rationale", required=True)
    decide.add_argument("--condition", action="append")
    decide.add_argument("--information-request", action="append")
    decide.add_argument("--acknowledge-policy-finding", action="append")
    return parser


def _enum_or_submitted_value(enum_type: Type[Enum], value: str):
    try:
        return enum_type(value)
    except ValueError:
        return value


def _serialized_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _assessment_summary(
    execution_input: AssessmentExecutionInput,
    normalized_repository_identity: Optional[str],
    evaluated_at: Optional[datetime],
):
    request = execution_input.request
    return {
        "assessment_id": request.assessment_id,
        "submitted_repository_locator": request.submitted_repository_locator,
        "normalized_repository_identity": normalized_repository_identity,
        "intended_use": request.intended_use,
        "environment": _serialized_value(request.environment),
        "criticality": _serialized_value(request.criticality),
        "expected_lifetime_days": request.expected_lifetime_days,
        "risk_tolerance": _serialized_value(request.risk_tolerance),
        "submitted_by_actor_id": request.submitted_by_actor_id,
        "responsible_reviewer_actor_id": (
            request.responsible_reviewer_actor_id
        ),
        "submitted_at": _serialized_value(request.submitted_at),
        "collection_attempted_at": _serialized_value(
            execution_input.collection_attempted_at
        ),
        "evaluated_at": _serialized_value(evaluated_at),
        "request_definition_version": request.request_definition_version,
    }


def _context_summary(context):
    if context is None:
        return None
    return {
        "assessment_id": context.assessment_id,
        "repository_identity": context.repository_identity,
        "intended_use": context.intended_use,
        "environment": context.environment.value,
        "criticality": context.criticality.value,
        "expected_lifetime_days": context.expected_lifetime_days,
        "risk_tolerance": context.risk_tolerance.value,
    }


def _validation_error_summary(error):
    return {
        "field": error.field,
        "code": error.code,
        "message": error.message,
    }


def _collection_failure_summary(failure):
    error = failure.error
    return {
        "evidence_kind": failure.evidence_kind.value,
        "collection_attempt_id": failure.collection_attempt_id,
        "outcome": failure.outcome.value,
        "error": {
            "category": error.category,
            "retryability": error.retryability,
            "message": error.message,
            "retry_after": error.retry_after,
        },
    }


def _evidence_summary(record):
    return {
        "evidence_id": record.evidence_id,
        "assessment_id": record.assessment_id,
        "evidence_kind": record.evidence_kind.value,
        "source_identity": record.source_identity,
        "collector_name": record.collector_name,
        "collector_version": record.collector_version,
        "collection_attempt_id": record.collection_attempt_id,
        "attempt_number": record.attempt_number,
        "attempted_at": record.attempted_at.isoformat(),
        "collection_outcome": record.collection_outcome.value,
        "freshness_basis": record.freshness_basis,
        "freshness_status_at_collection": (
            record.freshness_status_at_collection.value
        ),
        "evidence_schema_version": record.evidence_schema_version,
        "provenance": [
            {"key": key, "value": value}
            for key, value in record.provenance
        ],
        "value": _serialized_value(record.value),
        "integrity_digest": record.integrity_digest,
        "unavailability_reason": record.unavailability_reason,
        "error_category": record.error_category,
    }


def _metric_summary(metric):
    return {
        "metric_result_id": metric.metric_result_id,
        "assessment_id": metric.assessment_id,
        "calculation_attempt_id": metric.calculation_attempt_id,
        "metric_name": metric.metric_name,
        "metric_definition_version": metric.metric_definition_version,
        "input_evidence_ids": list(metric.input_evidence_ids),
        "input_digest": metric.input_digest,
        "calculated_at": metric.calculated_at.isoformat(),
        "result_status": metric.result_status.value,
        "input_sufficiency": metric.input_sufficiency.value,
        "metric_schema_version": metric.metric_schema_version,
        "value": _serialized_value(metric.value),
        "unit": metric.unit,
        "reason_code": metric.reason_code,
    }


def _finding_summary(finding):
    return {
        "policy_finding_id": finding.policy_finding_id,
        "assessment_id": finding.assessment_id,
        "policy_id": finding.policy_id,
        "policy_version": finding.policy_version,
        "policy_engine_version": finding.policy_engine_version,
        "policy_evaluation_id": finding.policy_evaluation_id,
        "requirement_id": finding.requirement_id,
        "requirement_version": finding.requirement_version,
        "outcome": finding.outcome.value,
        "input_evidence_ids": list(finding.input_evidence_ids),
        "input_metric_result_ids": list(
            finding.input_metric_result_ids
        ),
        "deterministic_reason": finding.deterministic_reason,
        "evaluated_at": finding.evaluated_at.isoformat(),
        "finding_schema_version": finding.finding_schema_version,
        "condition_template": finding.condition_template,
    }


def _human_decision_summary(decision):
    return {
        "human_decision_id": decision.human_decision_id,
        "assessment_id": decision.assessment_id,
        "assessment_evaluation_id": decision.assessment_evaluation_id,
        "decision_maker_actor_id": decision.decision_maker_actor_id,
        "disposition": decision.disposition.value,
        "rationale": decision.rationale,
        "conditions": list(decision.conditions),
        "information_requests": list(decision.information_requests),
        "acknowledged_policy_finding_ids": list(
            decision.acknowledged_policy_finding_ids
        ),
        "recorded_at": decision.recorded_at.isoformat(),
        "decision_schema_version": decision.decision_schema_version,
    }


def _empty_output(status: str):
    return {
        "output_schema_version": _OUTPUT_SCHEMA_VERSION,
        "status": status,
        "assessment": None,
        "context": None,
        "validation_errors": [],
        "collection_failure": None,
        "error": None,
        "evidence_records": [],
        "metric_results": [],
        "policy_findings": [],
        "human_decision": {"status": "not_implemented"},
    }


def _empty_review_output(status: str):
    return {
        "output_schema_version": _REVIEW_OUTPUT_SCHEMA_VERSION,
        "status": status,
        "assessment_id": None,
        "repository_identity": None,
        "assessment_context": None,
        "submitted_at": None,
        "responsible_reviewer_actor_id": None,
        "assessment_evaluation_id": None,
        "evaluated_at": None,
        "evaluation_schema_version": None,
        "integrity_digest": None,
        "evidence_records": [],
        "evidence_references": [],
        "metric_results": [],
        "policy_findings": [],
        "required_approval_acknowledgments": [],
        "human_decision": {"status": "unknown"},
        "error": None,
    }


def _review_output(review):
    verified_evidence, snapshot, decision = review
    validation_result = verified_evidence.validation_result
    request = validation_result.request
    output = _empty_review_output("review_complete")
    output.update(
        {
            "assessment_id": request.assessment_id,
            "repository_identity": (
                validation_result.normalized_repository_identity
            ),
            "assessment_context": _context_summary(
                validation_result.context
            ),
            "submitted_at": request.submitted_at.isoformat(),
            "responsible_reviewer_actor_id": (
                request.responsible_reviewer_actor_id
            ),
            "assessment_evaluation_id": (
                snapshot.assessment_evaluation_id
            ),
            "evaluated_at": snapshot.evaluated_at.isoformat(),
            "evaluation_schema_version": (
                snapshot.evaluation_schema_version
            ),
            "integrity_digest": snapshot.integrity_digest,
            "evidence_records": [
                _evidence_summary(record)
                for record in verified_evidence.evidence_records
            ],
            "evidence_references": [
                {
                    "evidence_kind": evidence_kind.value,
                    "evidence_id": evidence_id,
                }
                for evidence_kind, evidence_id in snapshot.evidence_references
            ],
            "metric_results": [
                _metric_summary(metric)
                for metric in snapshot.metric_results
            ],
            "policy_findings": [
                _finding_summary(finding)
                for finding in snapshot.policy_findings
            ],
            "required_approval_acknowledgments": [
                finding.policy_finding_id
                for finding in snapshot.policy_findings
                if finding.outcome is not PolicyOutcome.PASS
            ],
            "human_decision": (
                {"status": "not_recorded"}
                if decision is None
                else {
                    "status": "recorded",
                    **_human_decision_summary(decision),
                }
            ),
        }
    )
    return output


def _empty_decision_output(status: str):
    return {
        "output_schema_version": _DECISION_OUTPUT_SCHEMA_VERSION,
        "status": status,
        "human_decision_id": None,
        "assessment_id": None,
        "assessment_evaluation_id": None,
        "decision_maker_actor_id": None,
        "disposition": None,
        "rationale": None,
        "conditions": [],
        "information_requests": [],
        "acknowledged_policy_finding_ids": [],
        "recorded_at": None,
        "decision_schema_version": None,
        "actor_identity_assurance": _ACTOR_IDENTITY_ASSURANCE,
        "error": None,
    }


def _decision_output(decision, status: str):
    output = _empty_decision_output(status)
    output.update(_human_decision_summary(decision))
    return output


def _execution_output(result: AssessmentExecutionResult):
    evaluated_at = (
        result.assessment_result.evaluated_at
        if result.assessment_result is not None
        else None
    )
    output = _empty_output(result.status.value)
    output["assessment"] = _assessment_summary(
        result.execution_input,
        result.validation_result.normalized_repository_identity,
        evaluated_at,
    )
    output["context"] = _context_summary(result.validation_result.context)
    output["validation_errors"] = [
        _validation_error_summary(error)
        for error in result.validation_result.validation_errors
    ]

    if result.status is AssessmentExecutionStatus.INVALID_REQUEST:
        return output, _EXIT_INVALID_REQUEST

    if result.status is AssessmentExecutionStatus.COLLECTION_FAILED:
        output["collection_failure"] = _collection_failure_summary(
            result.failure
        )
        return output, _EXIT_COLLECTION_FAILED

    if result.status is AssessmentExecutionStatus.COMPLETE:
        assessment = result.assessment_result
        output["evidence_records"] = [
            _evidence_summary(record)
            for record in assessment.evidence_records
        ]
        output["metric_results"] = [
            _metric_summary(metric) for metric in assessment.metric_results
        ]
        output["policy_findings"] = [
            _finding_summary(finding)
            for finding in assessment.policy_findings
        ]
        return output, _EXIT_COMPLETE

    raise ValueError("unsupported assessment execution status")


def _persistence_failure_output(
    execution_input: AssessmentExecutionInput,
    error: SQLitePersistenceError,
):
    output = _empty_output("persistence_failed")
    output["assessment"] = _assessment_summary(
        execution_input, None, None
    )
    output["error"] = {
        "category": error.category,
        "message": error.message,
    }
    return output


def _safe_error_output(status: str, category: str, message: str):
    output = _empty_output(status)
    output["error"] = {"category": category, "message": message}
    return output


def _review_error_output(status: str, category: str, message: str):
    output = _empty_review_output(status)
    output["error"] = {"category": category, "message": message}
    return output


def _decision_error_output(status: str, category: str, message: str):
    output = _empty_decision_output(status)
    output["error"] = {"category": category, "message": message}
    return output


def _command_from_arguments(argv: Optional[Sequence[str]]) -> Optional[str]:
    values = tuple(sys.argv[1:] if argv is None else argv)
    if values and values[0] in ("assess", "review", "decide"):
        return values[0]
    return None


def _usage_error_output(command: Optional[str]):
    if command == "review":
        return _review_error_output(
            "usage_error", "usage_error", _USAGE_ERROR_MESSAGE
        )
    if command == "decide":
        return _decision_error_output(
            "usage_error", "usage_error", _USAGE_ERROR_MESSAGE
        )
    return _safe_error_output(
        "usage_error", "usage_error", _USAGE_ERROR_MESSAGE
    )


def _internal_error_output(command: Optional[str]):
    if command == "review":
        return _review_error_output(
            "internal_error",
            "internal_error",
            _REVIEW_INTERNAL_ERROR_MESSAGE,
        )
    if command == "decide":
        return _decision_error_output(
            "internal_error",
            "internal_error",
            _DECISION_INTERNAL_ERROR_MESSAGE,
        )
    return _safe_error_output(
        "internal_error", "internal_error", _INTERNAL_ERROR_MESSAGE
    )


def _known_persistence_error_output(
    command: str,
    error: SQLitePersistenceError,
    execution_input: Optional[AssessmentExecutionInput],
):
    if command == "review":
        if error.category == "invalid_input":
            return (
                _review_error_output(
                    "validation_failed",
                    "invalid_review",
                    "The assessment review input is invalid.",
                ),
                _EXIT_INVALID_REQUEST,
            )
        return (
            _review_error_output(
                "persistence_failed", error.category, error.message
            ),
            _EXIT_PERSISTENCE_FAILED,
        )
    if command == "decide":
        if error.category == "invalid_input":
            return (
                _decision_error_output(
                    "validation_failed",
                    "invalid_decision",
                    _DECISION_VALIDATION_ERROR_MESSAGE,
                ),
                _EXIT_INVALID_REQUEST,
            )
        if error.category == "conflicting_replay":
            return (
                _decision_error_output(
                    "conflicting_decision", error.category, error.message
                ),
                _EXIT_CONFLICTING_DECISION,
            )
        return (
            _decision_error_output(
                "persistence_failed", error.category, error.message
            ),
            _EXIT_PERSISTENCE_FAILED,
        )
    if execution_input is None:
        output = _safe_error_output(
            "persistence_failed", error.category, error.message
        )
    else:
        output = _persistence_failure_output(execution_input, error)
    return output, _EXIT_PERSISTENCE_FAILED


def _write_json(stream: TextIO, output) -> None:
    document = json.dumps(
        output,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    stream.write(document + "\n")


def _request_from_arguments(arguments) -> AssessmentRequestInput:
    return AssessmentRequestInput(
        assessment_id=_new_assessment_id(),
        submitted_repository_locator=arguments.repository,
        intended_use=arguments.intended_use,
        environment=_enum_or_submitted_value(
            Environment, arguments.environment
        ),
        criticality=_enum_or_submitted_value(
            Criticality, arguments.criticality
        ),
        expected_lifetime_days=arguments.expected_lifetime_days,
        risk_tolerance=_enum_or_submitted_value(
            RiskTolerance, arguments.risk_tolerance
        ),
        submitted_by_actor_id=arguments.submitted_by_actor_id,
        responsible_reviewer_actor_id=(
            arguments.responsible_reviewer_actor_id
        ),
        submitted_at=_current_utc_time(),
        request_definition_version=REQUEST_DEFINITION_VERSION,
    )


def _run_review(arguments):
    review = load_verified_assessment_review(
        arguments.database, arguments.assessment_id
    )
    return _review_output(review), _EXIT_COMPLETE


def _run_decide(arguments):
    try:
        disposition = HumanDecisionDisposition(arguments.decision)
    except ValueError:
        return (
            _decision_error_output(
                "validation_failed",
                "invalid_decision",
                _DECISION_VALIDATION_ERROR_MESSAGE,
            ),
            _EXIT_INVALID_REQUEST,
        )
    snapshot = load_verified_assessment_evaluation_snapshot(
        arguments.database, arguments.assessment_id
    )
    if (
        snapshot.assessment_id != arguments.assessment_id
        or snapshot.assessment_evaluation_id
        != arguments.assessment_evaluation_id
    ):
        return (
            _decision_error_output(
                "validation_failed",
                "invalid_decision",
                _DECISION_VALIDATION_ERROR_MESSAGE,
            ),
            _EXIT_INVALID_REQUEST,
        )
    decision, status = persist_human_decision_with_status(
        arguments.database,
        assessment_id=arguments.assessment_id,
        assessment_evaluation_id=arguments.assessment_evaluation_id,
        decision_maker_actor_id=arguments.reviewer_actor_id,
        disposition=disposition,
        rationale=arguments.rationale,
        conditions=tuple(arguments.condition or ()),
        information_requests=tuple(arguments.information_request or ()),
        acknowledged_policy_finding_ids=tuple(
            arguments.acknowledge_policy_finding or ()
        ),
    )
    return _decision_output(decision, status), _EXIT_COMPLETE


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one command and return its stable process exit code."""

    command = _command_from_arguments(argv)
    try:
        arguments = _build_parser().parse_args(argv)
    except _CLIUsageError:
        _write_json(sys.stderr, _usage_error_output(command))
        return _EXIT_USAGE

    execution_input = None
    try:
        if arguments.command == "assess":
            request = _request_from_arguments(arguments)
            execution_input = AssessmentExecutionInput(
                request=request,
                collection_attempted_at=_current_utc_time(),
            )
            result = execute_assessment(
                arguments.database, execution_input
            )
            output, exit_code = _execution_output(result)
        elif arguments.command == "review":
            output, exit_code = _run_review(arguments)
        elif arguments.command == "decide":
            output, exit_code = _run_decide(arguments)
        else:
            raise ValueError("unsupported command")
    except SQLitePersistenceError as error:
        output, exit_code = _known_persistence_error_output(
            arguments.command, error, execution_input
        )
    except Exception:
        _write_json(sys.stderr, _internal_error_output(command))
        return _EXIT_INTERNAL

    try:
        _write_json(sys.stdout, output)
    except Exception:
        _write_json(sys.stderr, _internal_error_output(command))
        return _EXIT_INTERNAL
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
