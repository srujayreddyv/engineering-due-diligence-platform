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
    EvidenceKind,
    EvidenceOutcome,
    FreshnessStatus,
    HumanDecisionDisposition,
    MetricStatus,
    PolicyOutcome,
    RiskTolerance,
)
from .persistence import (
    SQLitePersistenceError,
    evidence_normalization_version,
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
_REVIEW_REPORT_VERSION = "assessment-review-report.v1"
_DECISION_OUTPUT_SCHEMA_VERSION = "human-decision-cli-output.v1"
_USAGE_ERROR_MESSAGE = "The command arguments are invalid."
_INTERNAL_ERROR_MESSAGE = "The assessment could not be completed."
_REVIEW_INTERNAL_ERROR_MESSAGE = "The assessment review could not be loaded."
_DECISION_INTERNAL_ERROR_MESSAGE = "The human decision could not be recorded."
_DECISION_VALIDATION_ERROR_MESSAGE = "The human decision input is invalid."
_ACTOR_IDENTITY_ASSURANCE = "caller_asserted_not_authenticated"

_EVIDENCE_LABELS = {
    EvidenceKind.REPOSITORY_ARCHIVED: "Repository archived",
    EvidenceKind.LICENSE_STATUS: "Detected license metadata",
    EvidenceKind.LATEST_COMMIT_TIMESTAMP: "Latest commit timestamp",
    EvidenceKind.SECURITY_POLICY_PRESENT: (
        "Effective security policy presence"
    ),
}

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
    review.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )

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


def _markdown_value(value) -> str:
    """Render one dynamic value without allowing Markdown structure changes."""

    value = _serialized_value(value)
    if type(value) is bool:
        text = "true" if value else "false"
    elif value is None:
        text = "none"
    else:
        text = str(value)
    text = text.replace("&", "&amp;").replace("\\", "\\\\")
    for character in (
        "`",
        "*",
        "{",
        "}",
        "[",
        "]",
        "<",
        ">",
        "#",
        "|",
    ):
        text = text.replace(character, "\\" + character)
    return (
        text.replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
    )


def _markdown_field(lines, label: str, value) -> None:
    lines.append("- **{}:** {}".format(label, _markdown_value(value)))


def _markdown_ordered_values(lines, values, empty_text: str) -> None:
    if not values:
        lines.append("  - {}".format(empty_text))
        return
    for index, value in enumerate(values, start=1):
        lines.append("  {}. {}".format(index, _markdown_value(value)))


def _evidence_is_unusable(record) -> bool:
    return (
        record.collection_outcome is EvidenceOutcome.UNAVAILABLE
        or record.freshness_status_at_collection
        in (FreshnessStatus.STALE, FreshnessStatus.UNKNOWN)
    )


def _affected_results(record, snapshot):
    metrics = tuple(
        metric
        for metric in snapshot.metric_results
        if record.evidence_id in metric.input_evidence_ids
    )
    metric_ids = {metric.metric_result_id for metric in metrics}
    findings = tuple(
        finding
        for finding in snapshot.policy_findings
        if record.evidence_id in finding.input_evidence_ids
        or any(
            metric_id in metric_ids
            for metric_id in finding.input_metric_result_ids
        )
    )
    return metrics, findings


def _review_markdown(review) -> str:
    """Render the exact verified review state as deterministic Markdown."""

    verified_evidence, snapshot, decision = review
    validation_result = verified_evidence.validation_result
    request = validation_result.request
    context = validation_result.context
    required_acknowledgments = tuple(
        finding.policy_finding_id
        for finding in snapshot.policy_findings
        if finding.outcome is not PolicyOutcome.PASS
    )
    unusable_evidence = tuple(
        record
        for record in verified_evidence.evidence_records
        if _evidence_is_unusable(record)
    )
    unavailable_metrics = tuple(
        metric
        for metric in snapshot.metric_results
        if metric.result_status is MetricStatus.UNAVAILABLE
    )
    nonpassing_findings = tuple(
        finding
        for finding in snapshot.policy_findings
        if finding.outcome is not PolicyOutcome.PASS
    )
    outcome_counts = {
        outcome: sum(
            finding.outcome is outcome
            for finding in snapshot.policy_findings
        )
        for outcome in PolicyOutcome
    }

    lines = [
        "# Assessment Review Report",
        "",
        "**Report version:** {}".format(_REVIEW_REPORT_VERSION),
        "",
        "This report is a deterministic presentation of the exact verified "
        "assessment review state. It does not provide an overall recommendation.",
        "",
        "## Assessment at a glance",
        "",
    ]
    _markdown_field(
        lines,
        "Repository identity",
        validation_result.normalized_repository_identity,
    )
    _markdown_field(lines, "Intended use", context.intended_use)
    _markdown_field(lines, "Environment", context.environment)
    _markdown_field(lines, "Criticality", context.criticality)
    _markdown_field(
        lines, "Expected lifetime days", context.expected_lifetime_days
    )
    _markdown_field(lines, "Risk tolerance", context.risk_tolerance)
    _markdown_field(lines, "Assessment ID", request.assessment_id)
    _markdown_field(
        lines,
        "Assessment evaluation ID",
        snapshot.assessment_evaluation_id,
    )
    _markdown_field(lines, "Evaluated time", snapshot.evaluated_at)
    _markdown_field(
        lines,
        "Responsible reviewer actor ID",
        request.responsible_reviewer_actor_id,
    )
    _markdown_field(
        lines,
        "Human decision state",
        "not_recorded" if decision is None else "recorded",
    )
    lines.extend(["", "### Policy finding counts by exact outcome", ""])
    for outcome in PolicyOutcome:
        _markdown_field(lines, outcome.value, outcome_counts[outcome])

    lines.extend(["", "## Items requiring attention", ""])
    lines.extend(["### Unavailable or unusable evidence", ""])
    if not unusable_evidence:
        lines.append("- None.")
    for record in unusable_evidence:
        reason = (
            record.unavailability_reason
            if record.collection_outcome is EvidenceOutcome.UNAVAILABLE
            else "freshness_status:{}".format(
                record.freshness_status_at_collection.value
            )
        )
        lines.append(
            "- **{}:** {}".format(
                _markdown_value(record.evidence_kind.value),
                _markdown_value(reason),
            )
        )

    lines.extend(["", "### Unavailable metrics", ""])
    if not unavailable_metrics:
        lines.append("- None.")
    for metric in unavailable_metrics:
        lines.append(
            "- **{}:** {}".format(
                _markdown_value(metric.metric_name),
                _markdown_value(metric.reason_code),
            )
        )

    lines.extend(["", "### Non-PASS policy findings", ""])
    if not nonpassing_findings:
        lines.append("- None.")
    for finding in nonpassing_findings:
        lines.append(
            "- **{}:** {} — {} (finding {})".format(
                _markdown_value(finding.requirement_id),
                _markdown_value(finding.outcome.value),
                _markdown_value(finding.deterministic_reason),
                _markdown_value(finding.policy_finding_id),
            )
        )

    lines.extend(["", "### Required approval acknowledgment finding IDs", ""])
    if not required_acknowledgments:
        lines.append("- None.")
    for finding_id in required_acknowledgments:
        lines.append("- {}".format(_markdown_value(finding_id)))

    lines.extend(["", "## Evidence observed", ""])
    for index, record in enumerate(
        verified_evidence.evidence_records, start=1
    ):
        lines.append(
            "### {}. {}".format(index, _EVIDENCE_LABELS[record.evidence_kind])
        )
        lines.append("")
        _markdown_field(lines, "Evidence kind", record.evidence_kind)
        _markdown_field(
            lines, "Status", record.collection_outcome
        )
        if record.collection_outcome is EvidenceOutcome.AVAILABLE:
            _markdown_field(lines, "Normalized value", record.value)
        _markdown_field(lines, "Source identity", record.source_identity)
        _markdown_field(lines, "Collection time", record.attempted_at)
        _markdown_field(
            lines,
            "Freshness status",
            record.freshness_status_at_collection,
        )
        if record.evidence_kind is EvidenceKind.LICENSE_STATUS:
            lines.append(
                "- **Semantic boundary:** This records detected license "
                "metadata only; it does not establish legal compatibility."
            )
        elif record.evidence_kind is EvidenceKind.SECURITY_POLICY_PRESENT:
            lines.append(
                "- **Semantic boundary:** This records effective security "
                "policy presence only; it does not establish policy quality, "
                "security posture, or general repository safety."
            )
        lines.append("")

    lines.extend(
        [
            "## Unavailable information",
            "",
            "Unavailable means the fact was not established. It must not be "
            "interpreted as false, absent, or unfavorable.",
            "",
        ]
    )
    if not unusable_evidence and not unavailable_metrics:
        lines.append(
            "No required evidence or deterministic metric was unavailable or "
            "unusable at the stored evaluation time."
        )
    for record in unusable_evidence:
        affected_metrics, affected_findings = _affected_results(
            record, snapshot
        )
        lines.append(
            "### {}".format(_EVIDENCE_LABELS[record.evidence_kind])
        )
        lines.append("")
        _markdown_field(lines, "Evidence kind", record.evidence_kind)
        if record.unavailability_reason is not None:
            _markdown_field(
                lines,
                "Unavailability reason",
                record.unavailability_reason,
            )
        _markdown_field(
            lines,
            "Freshness reason",
            "status:{}; basis:{}".format(
                record.freshness_status_at_collection.value,
                record.freshness_basis,
            ),
        )
        if record.error_category is not None:
            _markdown_field(lines, "Error category", record.error_category)
        _markdown_field(
            lines,
            "Affected metric",
            ", ".join(metric.metric_name for metric in affected_metrics)
            or "none",
        )
        _markdown_field(
            lines,
            "Affected policy finding",
            ", ".join(
                "{} ({})".format(
                    finding.requirement_id, finding.policy_finding_id
                )
                for finding in affected_findings
            )
            or "none",
        )
        lines.append("")
    if unavailable_metrics:
        lines.extend(["### Unavailable metric details", ""])
        for metric in unavailable_metrics:
            affected_findings = tuple(
                finding
                for finding in snapshot.policy_findings
                if metric.metric_result_id
                in finding.input_metric_result_ids
            )
            lines.append(
                "- **{}:** reason {}; affected policy finding {}".format(
                    _markdown_value(metric.metric_name),
                    _markdown_value(metric.reason_code),
                    _markdown_value(
                        ", ".join(
                            "{} ({})".format(
                                finding.requirement_id,
                                finding.policy_finding_id,
                            )
                            for finding in affected_findings
                        )
                        or "none"
                    ),
                )
            )

    lines.extend(["", "## Deterministic metrics", ""])
    for index, metric in enumerate(snapshot.metric_results, start=1):
        lines.append(
            "### {}. {}".format(index, _markdown_value(metric.metric_name))
        )
        lines.append("")
        _markdown_field(lines, "Status", metric.result_status)
        if metric.result_status is MetricStatus.AVAILABLE:
            _markdown_field(lines, "Value", metric.value)
            _markdown_field(lines, "Unit", metric.unit)
        _markdown_field(lines, "Input sufficiency", metric.input_sufficiency)
        if metric.result_status is MetricStatus.UNAVAILABLE:
            _markdown_field(lines, "Reason code", metric.reason_code)
        _markdown_field(lines, "Calculated time", metric.calculated_at)
        lines.append("")

    lines.extend(
        [
            "## Policy requirements",
            "",
            "A deterministic policy condition template is a policy finding. "
            "It is separate from any human-recorded adoption condition.",
            "",
        ]
    )
    for index, finding in enumerate(snapshot.policy_findings, start=1):
        lines.append(
            "### {}. {}".format(
                index, _markdown_value(finding.requirement_id)
            )
        )
        lines.append("")
        _markdown_field(lines, "Exact outcome", finding.outcome)
        _markdown_field(lines, "Reason", finding.deterministic_reason)
        if finding.condition_template is not None:
            _markdown_field(
                lines,
                "Deterministic policy condition template",
                finding.condition_template,
            )
        lines.append("")

    lines.extend(["## Human decision", ""])
    lines.append(
        "Actor identity is caller asserted and not authenticated."
    )
    lines.append("")
    if decision is None:
        lines.append("No human decision has been recorded.")
    else:
        _markdown_field(lines, "Disposition", decision.disposition)
        _markdown_field(lines, "Rationale", decision.rationale)
        _markdown_field(
            lines,
            "Decision maker actor ID",
            decision.decision_maker_actor_id,
        )
        _markdown_field(lines, "Recorded time", decision.recorded_at)
        lines.append("- **Human-recorded adoption conditions:**")
        _markdown_ordered_values(lines, decision.conditions, "None.")
        lines.append("- **Information requests:**")
        _markdown_ordered_values(
            lines, decision.information_requests, "None."
        )
        lines.append("- **Acknowledged policy finding IDs:**")
        _markdown_ordered_values(
            lines,
            decision.acknowledged_policy_finding_ids,
            "None.",
        )
        if (
            decision.disposition
            is HumanDecisionDisposition.APPROVE_WITH_CONDITIONS
        ):
            lines.extend(
                [
                    "",
                    "Adoption was accepted subject to the recorded conditions. "
                    "The platform does not track or verify condition fulfillment.",
                ]
            )
        elif (
            decision.disposition
            is HumanDecisionDisposition.NEEDS_MORE_INFORMATION
        ):
            lines.extend(
                [
                    "",
                    "Needs more information is the immutable disposition for "
                    "this assessment under the current model.",
                ]
            )

    lines.extend(["", "## Technical provenance", ""])
    _markdown_field(lines, "Assessment ID", request.assessment_id)
    _markdown_field(
        lines,
        "Assessment evaluation ID",
        snapshot.assessment_evaluation_id,
    )
    _markdown_field(
        lines,
        "Evaluation schema version",
        snapshot.evaluation_schema_version,
    )
    _markdown_field(
        lines, "Snapshot integrity digest", snapshot.integrity_digest
    )
    _markdown_field(
        lines, "Request definition version", request.request_definition_version
    )
    _markdown_field(lines, "Submission time", request.submitted_at)

    lines.extend(["", "### Canonical evidence references", ""])
    for evidence_kind, evidence_id in snapshot.evidence_references:
        lines.append(
            "- **{}:** {}".format(
                _markdown_value(evidence_kind.value),
                _markdown_value(evidence_id),
            )
        )

    lines.extend(["", "### Evidence record provenance", ""])
    for record in verified_evidence.evidence_records:
        lines.append(
            "#### {}".format(_EVIDENCE_LABELS[record.evidence_kind])
        )
        lines.append("")
        _markdown_field(lines, "Evidence ID", record.evidence_id)
        _markdown_field(lines, "Collector name", record.collector_name)
        _markdown_field(lines, "Collector version", record.collector_version)
        _markdown_field(
            lines,
            "Normalization version",
            evidence_normalization_version(record.evidence_kind),
        )
        _markdown_field(
            lines,
            "Evidence schema version",
            record.evidence_schema_version,
        )
        _markdown_field(
            lines, "Collection attempt ID", record.collection_attempt_id
        )
        _markdown_field(lines, "Attempt number", record.attempt_number)
        lines.append("- **Provenance pairs:**")
        if record.provenance:
            for key, value in record.provenance:
                lines.append(
                    "  - {}: {}".format(
                        _markdown_value(key), _markdown_value(value)
                    )
                )
        else:
            lines.append("  - None.")
        _markdown_field(
            lines,
            "Evidence digest",
            record.integrity_digest or "not_applicable",
        )
        lines.append("")

    lines.extend(["### Metric result provenance", ""])
    for metric in snapshot.metric_results:
        lines.append("#### {}".format(_markdown_value(metric.metric_name)))
        lines.append("")
        _markdown_field(lines, "Metric result ID", metric.metric_result_id)
        _markdown_field(
            lines,
            "Calculation attempt ID",
            metric.calculation_attempt_id,
        )
        _markdown_field(
            lines,
            "Metric definition version",
            metric.metric_definition_version,
        )
        _markdown_field(
            lines, "Metric schema version", metric.metric_schema_version
        )
        lines.append("- **Input evidence IDs:**")
        _markdown_ordered_values(lines, metric.input_evidence_ids, "None.")
        _markdown_field(lines, "Metric input digest", metric.input_digest)
        lines.append("")

    lines.extend(["### Policy finding provenance", ""])
    for finding in snapshot.policy_findings:
        lines.append(
            "#### {}".format(_markdown_value(finding.requirement_id))
        )
        lines.append("")
        _markdown_field(
            lines, "Policy finding ID", finding.policy_finding_id
        )
        _markdown_field(lines, "Policy ID", finding.policy_id)
        _markdown_field(
            lines, "Policy evaluation ID", finding.policy_evaluation_id
        )
        _markdown_field(lines, "Policy version", finding.policy_version)
        _markdown_field(
            lines, "Policy engine version", finding.policy_engine_version
        )
        _markdown_field(
            lines, "Requirement version", finding.requirement_version
        )
        _markdown_field(
            lines,
            "Policy finding schema version",
            finding.finding_schema_version,
        )
        lines.append("- **Input evidence IDs:**")
        _markdown_ordered_values(lines, finding.input_evidence_ids, "None.")
        lines.append("- **Input metric result IDs:**")
        _markdown_ordered_values(
            lines, finding.input_metric_result_ids, "None."
        )
        lines.append("")

    if decision is not None:
        lines.extend(["### Human decision provenance", ""])
        _markdown_field(
            lines, "Human decision ID", decision.human_decision_id
        )
        _markdown_field(
            lines,
            "Human decision schema version",
            decision.decision_schema_version,
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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
    if arguments.format == "markdown":
        return _review_markdown(review), _EXIT_COMPLETE
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
        if type(output) is str:
            sys.stdout.write(output)
        else:
            _write_json(sys.stdout, output)
    except Exception:
        _write_json(sys.stderr, _internal_error_output(command))
        return _EXIT_INTERNAL
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
