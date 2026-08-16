#!/usr/bin/env python3
"""Run the frozen Day 19 deterministic system conformance evaluation."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import uuid
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from unittest.mock import patch

import engineering_due_diligence.cli as cli
import engineering_due_diligence.persistence as persistence
import engineering_due_diligence.workflow as workflow
from engineering_due_diligence.assessment import (
    ASSESSMENT_EVALUATION_SCHEMA_VERSION,
)
from engineering_due_diligence.evaluation import (
    FINDING_SCHEMA_VERSION,
    METRIC_SCHEMA_VERSION,
    METRIC_VERSIONS,
    POLICY_ENGINE_VERSION,
    POLICY_ID,
    POLICY_VERSION,
    REQUIREMENT_VERSIONS,
)
from engineering_due_diligence.models import (
    HUMAN_DECISION_SCHEMA_VERSION,
    EvidenceKind,
    PolicyOutcome,
)
from engineering_due_diligence.request import REQUEST_DEFINITION_VERSION

from deterministic_evaluation_scenarios import SCENARIOS, Scenario


OUTPUT_SCHEMA_VERSION = "deterministic-system-evaluation-output.v1"
HARNESS_VERSION = "deterministic-system-evaluation-harness.v1"
REPORT_VERSION = "assessment-review-report.v1"
REPOSITORY_LOCATOR = "https://github.com/Evaluation/FrozenRepository"
REPOSITORY_IDENTITY = "github.com/Evaluation/FrozenRepository"
REPOSITORY_ENDPOINT = (
    "https://api.github.com/repos/Evaluation/FrozenRepository"
)
COMMITS_ENDPOINT = REPOSITORY_ENDPOINT + "/commits?per_page=1"
POLICY_ENDPOINT = REPOSITORY_ENDPOINT + "/contents/.github/SECURITY.md"
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
POLICY_SHA = "abcdef0123456789abcdef0123456789abcdef01"
PRIVATE_SOURCE_MARKER = "day-19-private-source-body-must-not-appear"
SUBMITTED_AT = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
COLLECTION_AT = datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)
EVALUATED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
RECORDED_AT = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
EVIDENCE_ORDER = (
    "repository_archived",
    "license_status",
    "latest_commit_timestamp",
    "security_policy_present",
)
METRIC_ORDER = (
    "repository_archived",
    "license_present",
    "days_since_latest_commit",
    "security_policy_present",
)
POLICY_ORDER = (
    "repository_not_archived",
    "license_declared",
    "commit_recency",
    "security_policy",
)
COLLECTOR_VERSIONS = {
    "repository_archived": "public-github-repository-metadata.v1",
    "license_status": "public-github-license-status.v1",
    "latest_commit_timestamp": "public-github-latest-commit.v1",
    "security_policy_present": "public-github-security-policy-presence.v1",
}
MARKDOWN_SECTIONS = (
    "Assessment at a glance",
    "Items requiring attention",
    "Evidence observed",
    "Unavailable information",
    "Deterministic metrics",
    "Policy requirements",
    "Human decision",
    "Technical provenance",
)


class EvaluationMismatch(AssertionError):
    """One observed product behavior did not match a frozen expectation."""


@dataclass(frozen=True)
class Invocation:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CompletedArtifacts:
    review_json: str
    review_markdown: str
    decision_output: Optional[str]
    evidence_projection: Tuple[Tuple[object, ...], ...]
    metric_projection: Tuple[Tuple[object, ...], ...]
    policy_projection: Tuple[Tuple[object, ...], ...]
    source_body_digests: Tuple[Optional[str], ...]
    normalized_fact_projection: Tuple[Tuple[object, ...], ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationMismatch(message)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _scenario_uuid(scenario: Scenario) -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-8000-{:012d}".format(
        int(scenario.scenario_id[1:])
    ))


def _assessment_id(scenario: Scenario) -> str:
    return "assessment-{}".format(_scenario_uuid(scenario))


def _repository_response(scenario: Scenario) -> Tuple[int, bytes, Tuple]:
    return (
        200,
        _json_bytes(
            {
                "id": 91001,
                "full_name": "Evaluation/FrozenRepository",
                "archived": scenario.archived,
                "license": (
                    {
                        "key": "mit",
                        "name": "MIT License",
                        "spdx_id": "MIT",
                    }
                    if scenario.license_present
                    else None
                ),
                "private_marker": PRIVATE_SOURCE_MARKER,
            }
        ),
        (("ETag", '"day-19-repository"'),),
    )


def _latest_response(scenario: Scenario) -> Tuple[int, bytes, Tuple]:
    if scenario.latest_commit_age_days is None:
        return 200, b"[]", (("ETag", '"day-19-empty-commits"'),)
    commit_at = EVALUATED_AT - timedelta(
        days=scenario.latest_commit_age_days
    )
    return (
        200,
        _json_bytes(
            [
                {
                    "sha": COMMIT_SHA,
                    "url": REPOSITORY_ENDPOINT + "/commits/" + COMMIT_SHA,
                    "commit": {
                        "author": {"date": commit_at.isoformat()},
                        "committer": {"date": commit_at.isoformat()},
                    },
                    "private_marker": PRIVATE_SOURCE_MARKER,
                }
            ]
        ),
        (("ETag", '"day-19-commit"'),),
    )


def _policy_response() -> Tuple[int, bytes, Tuple]:
    return (
        200,
        _json_bytes(
            {
                "type": "file",
                "name": "SECURITY.md",
                "path": ".github/SECURITY.md",
                "size": 42,
                "sha": POLICY_SHA,
                "url": POLICY_ENDPOINT,
                "content": "ZnJvemVuLXNlY3VyaXR5LXBvbGljeQ==",
                "private_marker": PRIVATE_SOURCE_MARKER,
            }
        ),
        (("ETag", '"day-19-security-policy"'),),
    )


def _security_candidate_endpoints() -> Tuple[str, ...]:
    return (
        REPOSITORY_ENDPOINT + "/contents/.github/SECURITY.md",
        REPOSITORY_ENDPOINT + "/contents/SECURITY.md",
        REPOSITORY_ENDPOINT + "/contents/docs/SECURITY.md",
        "https://api.github.com/repos/Evaluation/.github/contents/.github/SECURITY.md",
        "https://api.github.com/repos/Evaluation/.github/contents/SECURITY.md",
        "https://api.github.com/repos/Evaluation/.github/contents/docs/SECURITY.md",
    )


def _transport_plan(
    scenario: Scenario,
) -> Tuple[Tuple[str, Tuple[object, ...]], ...]:
    repository_response = _repository_response(scenario)
    if scenario.rate_limit_latest_commit:
        return (
            (REPOSITORY_ENDPOINT, repository_response),
            (REPOSITORY_ENDPOINT, repository_response),
            (
                COMMITS_ENDPOINT,
                (
                    429,
                    None,
                    (
                        ("X-RateLimit-Remaining", "0"),
                        ("Retry-After", "60"),
                    ),
                ),
            ),
        )
    plan: List[Tuple[str, Tuple[object, ...]]] = [
        (REPOSITORY_ENDPOINT, repository_response),
        (REPOSITORY_ENDPOINT, repository_response),
        (COMMITS_ENDPOINT, _latest_response(scenario)),
        (REPOSITORY_ENDPOINT, repository_response),
    ]
    if scenario.security_policy_present:
        plan.append((POLICY_ENDPOINT, _policy_response()))
    else:
        plan.extend(
            (endpoint, (404, None, ()))
            for endpoint in _security_candidate_endpoints()
        )
    return tuple(plan)


class _FrozenTransport:
    def __init__(self, plan: Sequence[Tuple[str, Tuple[object, ...]]]):
        self._plan = list(plan)
        self.calls: List[str] = []

    def __call__(self, source_identity: str):
        if not self._plan:
            raise EvaluationMismatch("unexpected GitHub transport call")
        expected_identity, response = self._plan.pop(0)
        _require(
            source_identity == expected_identity,
            "GitHub source order or identity differed",
        )
        self.calls.append(source_identity)
        return response

    def require_complete(self) -> None:
        _require(not self._plan, "expected GitHub calls did not occur")


def _response_body_digests(scenario: Scenario) -> Tuple[Optional[str], ...]:
    digests = []
    for _, (_, body, _) in _transport_plan(scenario):
        digests.append(
            hashlib.sha256(body).hexdigest()
            if isinstance(body, bytes)
            else None
        )
    return tuple(digests)


def _assess_arguments(scenario: Scenario, database: Path) -> List[str]:
    context = scenario.context
    return [
        "assess",
        "--database",
        str(database),
        "--repository",
        REPOSITORY_LOCATOR,
        "--intended-use",
        context.intended_use,
        "--environment",
        context.environment,
        "--criticality",
        context.criticality,
        "--expected-lifetime-days",
        str(context.expected_lifetime_days),
        "--risk-tolerance",
        context.risk_tolerance,
        "--submitted-by-actor-id",
        "actor-submitter",
        "--responsible-reviewer-actor-id",
        "actor-reviewer",
    ]


def _capture_cli(arguments: Sequence[str], stack: ExitStack) -> Invocation:
    stdout = io.StringIO()
    stderr = io.StringIO()
    stack.enter_context(redirect_stdout(stdout))
    stack.enter_context(redirect_stderr(stderr))
    exit_code = cli.main(arguments)
    return Invocation(exit_code, stdout.getvalue(), stderr.getvalue())


def _invoke_assess(
    scenario: Scenario,
    database: Path,
    *,
    evaluation_clock_forbidden: bool = False,
) -> Tuple[Invocation, _FrozenTransport, object]:
    transport = _FrozenTransport(_transport_plan(scenario))
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "engineering_due_diligence.github."
                "_get_public_github_repository",
                side_effect=transport,
            )
        )
        stack.enter_context(
            patch.object(cli, "_new_uuid", return_value=_scenario_uuid(scenario))
        )
        stack.enter_context(
            patch.object(
                cli,
                "_current_utc_time",
                side_effect=(SUBMITTED_AT, COLLECTION_AT),
            )
        )
        evaluation_clock = stack.enter_context(
            patch.object(
                workflow,
                "_current_evaluation_time",
                side_effect=(
                    AssertionError("evaluation clock must not be read")
                    if evaluation_clock_forbidden
                    else None
                ),
                return_value=(None if evaluation_clock_forbidden else EVALUATED_AT),
            )
        )
        invoked = _capture_cli(_assess_arguments(scenario, database), stack)
    return invoked, transport, evaluation_clock


def _invoke_clock_free(arguments: Sequence[str]) -> Invocation:
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "engineering_due_diligence.github."
                "_get_public_github_repository",
                side_effect=AssertionError("network activity is forbidden"),
            )
        )
        stack.enter_context(
            patch.object(
                cli,
                "_current_utc_time",
                side_effect=AssertionError("CLI clock must not be read"),
            )
        )
        stack.enter_context(
            patch.object(
                workflow,
                "_current_evaluation_time",
                side_effect=AssertionError("evaluation clock must not be read"),
            )
        )
        stack.enter_context(
            patch.object(
                persistence,
                "_current_decision_time",
                side_effect=AssertionError("decision clock must not be read"),
            )
        )
        return _capture_cli(arguments, stack)


def _invoke_decide(
    database: Path,
    scenario: Scenario,
    evaluation_id: str,
    acknowledgment_ids: Sequence[str],
    *,
    exact_replay: bool = False,
) -> Invocation:
    decision = scenario.decision
    _require(decision is not None, "decision exercise is required")
    arguments = [
        "decide",
        "--database",
        str(database),
        "--assessment-id",
        _assessment_id(scenario),
        "--assessment-evaluation-id",
        evaluation_id,
        "--reviewer-actor-id",
        "actor-reviewer",
        "--decision",
        decision.disposition,
        "--rationale",
        decision.rationale,
    ]
    for condition in decision.conditions:
        arguments.extend(("--condition", condition))
    for request in decision.information_requests:
        arguments.extend(("--information-request", request))
    for finding_id in acknowledgment_ids:
        arguments.extend(("--acknowledge-policy-finding", finding_id))

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "engineering_due_diligence.github."
                "_get_public_github_repository",
                side_effect=AssertionError("network activity is forbidden"),
            )
        )
        stack.enter_context(
            patch.object(
                cli,
                "_current_utc_time",
                side_effect=AssertionError("CLI clock must not be read"),
            )
        )
        stack.enter_context(
            patch.object(
                workflow,
                "_current_evaluation_time",
                side_effect=AssertionError("evaluation clock must not be read"),
            )
        )
        decision_clock = stack.enter_context(
            patch.object(
                persistence,
                "_current_decision_time",
                side_effect=(
                    AssertionError("decision replay clock must not be read")
                    if exact_replay
                    else None
                ),
                return_value=(None if exact_replay else RECORDED_AT),
            )
        )
        invoked = _capture_cli(arguments, stack)
    if exact_replay:
        _require(decision_clock.call_count == 0, "decision replay read the clock")
    return invoked


def _review_arguments(
    database: Path, scenario: Scenario, output_format: str
) -> List[str]:
    return [
        "review",
        "--database",
        str(database),
        "--assessment-id",
        _assessment_id(scenario),
        "--format",
        output_format,
    ]


def _review(database: Path, scenario: Scenario, output_format: str) -> Invocation:
    return _invoke_clock_free(_review_arguments(database, scenario, output_format))


def _expected_commit_value(scenario: Scenario) -> Optional[str]:
    if scenario.latest_commit_age_days is None:
        return None
    return (
        EVALUATED_AT - timedelta(days=scenario.latest_commit_age_days)
    ).isoformat()


def _assert_context(scenario: Scenario, review: Dict[str, object]) -> None:
    context = review["assessment_context"]
    _require(review["assessment_id"] == _assessment_id(scenario), "assessment ID")
    _require(review["repository_identity"] == REPOSITORY_IDENTITY, "repository")
    _require(
        context
        == {
            "assessment_id": _assessment_id(scenario),
            "repository_identity": REPOSITORY_IDENTITY,
            "intended_use": scenario.context.intended_use,
            "environment": scenario.context.environment,
            "criticality": scenario.context.criticality,
            "expected_lifetime_days": scenario.context.expected_lifetime_days,
            "risk_tolerance": scenario.context.risk_tolerance,
        },
        "assessment context differed",
    )
    _require(review["submitted_at"] == SUBMITTED_AT.isoformat(), "submission time")
    _require(
        review["responsible_reviewer_actor_id"] == "actor-reviewer",
        "responsible reviewer",
    )


def _assert_evidence(
    scenario: Scenario, review: Dict[str, object]
) -> Tuple[Tuple[object, ...], ...]:
    records = review["evidence_records"]
    _require(
        tuple(item["evidence_kind"] for item in records) == EVIDENCE_ORDER,
        "evidence order differed",
    )
    projection = []
    for record, expected in zip(records, scenario.expected_evidence):
        expected_value = expected.value
        if expected_value == "commit_timestamp":
            expected_value = _expected_commit_value(scenario)
        actual = (
            record["evidence_kind"],
            record["collection_outcome"],
            record["value"],
            record["freshness_status_at_collection"],
            record["unavailability_reason"],
            record["error_category"],
        )
        wanted = (
            expected.kind,
            expected.outcome,
            expected_value,
            expected.freshness,
            expected.unavailability_reason,
            expected.error_category,
        )
        _require(actual == wanted, "evidence projection differed for {}".format(expected.kind))
        _require(record["evidence_schema_version"] == "evidence-record.v1", "evidence schema")
        _require(
            record["collector_version"] == COLLECTOR_VERSIONS[expected.kind],
            "collector version differed",
        )
        projection.append(actual)
    _require(len(projection) == 4, "evidence set was not complete")
    return tuple(projection)


def _assert_metrics(
    scenario: Scenario, review: Dict[str, object]
) -> Tuple[Tuple[object, ...], ...]:
    metrics = review["metric_results"]
    _require(
        tuple(item["metric_name"] for item in metrics) == METRIC_ORDER,
        "metric order differed",
    )
    projection = []
    for metric, expected in zip(metrics, scenario.expected_metrics):
        actual = (
            metric["metric_name"],
            metric["result_status"],
            metric["value"],
            metric["unit"],
            metric["input_sufficiency"],
            metric["reason_code"],
        )
        wanted = (
            expected.name,
            expected.status,
            expected.value,
            expected.unit,
            expected.sufficiency,
            expected.reason_code,
        )
        _require(actual == wanted, "metric projection differed for {}".format(expected.name))
        _require(
            metric["metric_definition_version"] == METRIC_VERSIONS[expected.name],
            "metric definition version differed",
        )
        _require(metric["metric_schema_version"] == METRIC_SCHEMA_VERSION, "metric schema")
        _require(metric["calculated_at"] == EVALUATED_AT.isoformat(), "metric time")
        projection.append(actual)
    _require(len(projection) == 4, "metric set was not complete")
    return tuple(projection)


def _assert_policy(
    scenario: Scenario, review: Dict[str, object]
) -> Tuple[Tuple[object, ...], ...]:
    findings = review["policy_findings"]
    _require(
        tuple(item["requirement_id"] for item in findings) == POLICY_ORDER,
        "policy order differed",
    )
    projection = []
    for finding, expected in zip(findings, scenario.expected_policy):
        actual = (
            finding["requirement_id"],
            finding["outcome"],
            finding["deterministic_reason"],
            finding["condition_template"],
        )
        wanted = (
            expected.requirement_id,
            expected.outcome,
            expected.reason_code,
            expected.condition_template,
        )
        _require(actual == wanted, "policy projection differed for {}".format(expected.requirement_id))
        _require(finding["policy_id"] == POLICY_ID, "policy ID differed")
        _require(finding["policy_version"] == POLICY_VERSION, "policy version differed")
        _require(finding["policy_engine_version"] == POLICY_ENGINE_VERSION, "engine version differed")
        _require(
            finding["requirement_version"]
            == REQUIREMENT_VERSIONS[expected.requirement_id],
            "requirement version differed",
        )
        _require(finding["finding_schema_version"] == FINDING_SCHEMA_VERSION, "finding schema")
        projection.append(actual)
    _require(len(projection) == 4, "policy set was not complete")
    return tuple(projection)


def _assert_snapshot(database: Path, scenario: Scenario, review: Dict[str, object]):
    verified_evidence, snapshot, _ = persistence.load_verified_assessment_review(
        database, _assessment_id(scenario)
    )
    _require(
        verified_evidence.validation_result.request.request_definition_version
        == REQUEST_DEFINITION_VERSION,
        "request definition version differed",
    )
    _require(snapshot.evaluated_at == EVALUATED_AT, "evaluation time differed")
    _require(
        snapshot.evaluation_schema_version == ASSESSMENT_EVALUATION_SCHEMA_VERSION,
        "evaluation schema version differed",
    )
    _require(
        review["assessment_evaluation_id"] == snapshot.assessment_evaluation_id,
        "review evaluation identity differed",
    )
    _require(review["integrity_digest"] == snapshot.integrity_digest, "review digest differed")
    _require(
        hashlib.sha256(snapshot.snapshot_json.encode("utf-8")).hexdigest()
        == snapshot.integrity_digest,
        "snapshot digest did not verify",
    )
    _require(
        tuple(item["evidence_kind"] for item in review["evidence_references"])
        == EVIDENCE_ORDER,
        "evidence reference order differed",
    )
    return snapshot


def _assert_markdown(
    scenario: Scenario,
    markdown: str,
    review: Dict[str, object],
) -> None:
    _require(
        "**Report version:** {}".format(REPORT_VERSION) in markdown,
        "report version missing",
    )
    positions = []
    for section in MARKDOWN_SECTIONS:
        marker = "## {}".format(section)
        _require(marker in markdown, "Markdown section missing: {}".format(section))
        positions.append(markdown.index(marker))
    _require(positions == sorted(positions), "Markdown section order differed")
    _require(PRIVATE_SOURCE_MARKER not in markdown, "raw source body leaked")
    _require("## Overall recommendation" not in markdown, "recommendation invented")
    _require(
        review["assessment_evaluation_id"] in markdown,
        "Markdown references another evaluation",
    )
    for finding_id in review["required_approval_acknowledgments"]:
        _require(finding_id in markdown, "required acknowledgment missing")
    for evidence_kind in EVIDENCE_ORDER:
        normalization_version = persistence.evidence_normalization_version(
            EvidenceKind(evidence_kind)
        )
        _require(
            normalization_version in markdown,
            "normalization version missing for {}".format(evidence_kind),
        )
    if scenario.scenario_id == "E08":
        _require(
            "Unavailable means the fact was not established" in markdown,
            "uncertainty explanation missing",
        )
        _require("not_evaluable" in markdown, "NOT_EVALUABLE missing")
    if scenario.scenario_id == "E03":
        _require(
            scenario.expected_policy[1].condition_template in markdown,
            "policy condition template changed",
        )
        _require(
            scenario.decision.conditions[0] in markdown,
            "human condition missing",
        )
        _require(
            "does not track or verify condition fulfillment" in markdown,
            "condition fulfillment disclaimer missing",
        )


def _decision_acknowledgments(
    scenario: Scenario, review: Dict[str, object]
) -> Tuple[str, ...]:
    decision = scenario.decision
    if decision is None:
        return ()
    by_requirement = {
        finding["requirement_id"]: finding["policy_finding_id"]
        for finding in review["policy_findings"]
    }
    return tuple(
        by_requirement[requirement_id]
        for requirement_id in decision.acknowledged_requirement_ids
    )


def _assert_common_success(
    database: Path,
    scenario: Scenario,
    review_json: str,
    markdown: str,
) -> Tuple[
    Tuple[Tuple[object, ...], ...],
    Tuple[Tuple[object, ...], ...],
    Tuple[Tuple[object, ...], ...],
]:
    review = json.loads(review_json)
    _require(review["output_schema_version"] == "assessment-review-cli-output.v1", "review schema")
    _require(review["status"] == "review_complete", "review did not complete")
    _assert_context(scenario, review)
    evidence = _assert_evidence(scenario, review)
    metrics = _assert_metrics(scenario, review)
    policy = _assert_policy(scenario, review)
    _assert_snapshot(database, scenario, review)
    required = tuple(
        finding["policy_finding_id"]
        for finding in review["policy_findings"]
        if finding["outcome"] != PolicyOutcome.PASS.value
    )
    _require(
        tuple(review["required_approval_acknowledgments"]) == required,
        "required acknowledgments were not every non-PASS finding in order",
    )
    _require(PRIVATE_SOURCE_MARKER not in review_json, "raw source body leaked to JSON")
    _assert_markdown(scenario, markdown, review)
    return evidence, metrics, policy


def _run_completed_instance(scenario: Scenario) -> CompletedArtifacts:
    with tempfile.TemporaryDirectory() as temporary_directory:
        database = Path(temporary_directory) / "evaluation.sqlite3"
        assessed, transport, evaluation_clock = _invoke_assess(scenario, database)
        transport.require_complete()
        _require(assessed.exit_code == 0 and not assessed.stderr, "assess did not complete")
        assess_output = json.loads(assessed.stdout)
        _require(assess_output["status"] == "complete", "assessment status differed")
        _require(PRIVATE_SOURCE_MARKER not in assessed.stdout, "raw source body leaked to assess")
        _require(evaluation_clock.call_count == 1, "evaluation time was not captured exactly once")

        initial_json = _review(database, scenario, "json")
        initial_markdown = _review(database, scenario, "markdown")
        _require(initial_json.exit_code == 0 and not initial_json.stderr, "initial review failed")
        _require(initial_markdown.exit_code == 0 and not initial_markdown.stderr, "initial report failed")
        initial_output = json.loads(initial_json.stdout)
        _require(initial_output["human_decision"] == {"status": "not_recorded"}, "decision existed before exercise")
        initial_snapshot_id = initial_output["assessment_evaluation_id"]
        initial_evaluated_at = initial_output["evaluated_at"]

        if scenario.assessment_replay:
            replay, replay_transport, replay_clock = _invoke_assess(
                scenario, database, evaluation_clock_forbidden=True
            )
            replay_transport.require_complete()
            _require(replay.exit_code == 0 and not replay.stderr, "assessment replay failed")
            _require(replay_clock.call_count == 0, "assessment replay captured evaluation time")
            replay_review = _review(database, scenario, "json")
            _require(replay_review.stdout == initial_json.stdout, "assessment replay changed durable review")
            replay_output = json.loads(replay_review.stdout)
            _require(replay_output["assessment_evaluation_id"] == initial_snapshot_id, "assessment replay changed evaluation ID")
            _require(replay_output["evaluated_at"] == initial_evaluated_at, "assessment replay changed evaluation time")

        decision_output = None
        if scenario.decision is not None:
            acknowledgment_ids = _decision_acknowledgments(scenario, initial_output)
            _require(
                acknowledgment_ids
                == tuple(initial_output["required_approval_acknowledgments"]),
                "fixed approval acknowledgments did not equal required findings",
            ) if scenario.decision.disposition.startswith("approve") else None
            decided = _invoke_decide(
                database,
                scenario,
                initial_snapshot_id,
                acknowledgment_ids,
            )
            _require(decided.exit_code == 0 and not decided.stderr, "decision exercise failed")
            decided_output = json.loads(decided.stdout)
            _require(decided_output["status"] == "recorded", "decision was not first recorded")
            _require(decided_output["recorded_at"] == RECORDED_AT.isoformat(), "decision time differed")
            _require(decided_output["decision_schema_version"] == HUMAN_DECISION_SCHEMA_VERSION, "decision schema")
            _require(decided_output["disposition"] == scenario.decision.disposition, "decision disposition differed")
            _require(tuple(decided_output["conditions"]) == scenario.decision.conditions, "human conditions differed")
            _require(tuple(decided_output["information_requests"]) == scenario.decision.information_requests, "information requests differed")
            _require(tuple(decided_output["acknowledged_policy_finding_ids"]) == acknowledgment_ids, "decision acknowledgments differed")
            decision_output = decided.stdout
            if scenario.decision.exercise_exact_replay:
                replayed = _invoke_decide(
                    database,
                    scenario,
                    initial_snapshot_id,
                    acknowledgment_ids,
                    exact_replay=True,
                )
                _require(replayed.exit_code == 0 and not replayed.stderr, "decision replay failed")
                replay_output = json.loads(replayed.stdout)
                _require(replay_output["status"] == "exact_replay", "decision replay status differed")
                _require(replay_output["human_decision_id"] == decided_output["human_decision_id"], "decision replay changed identity")
                _require(replay_output["recorded_at"] == decided_output["recorded_at"], "decision replay changed time")

        final_json = _review(database, scenario, "json")
        final_markdown = _review(database, scenario, "markdown")
        _require(final_json.exit_code == 0 and not final_json.stderr, "final review failed")
        _require(final_markdown.exit_code == 0 and not final_markdown.stderr, "final report failed")
        final_output = json.loads(final_json.stdout)
        if scenario.decision is None:
            _require(final_output["human_decision"] == {"status": "not_recorded"}, "automatic decision appeared")
        else:
            _require(final_output["human_decision"]["status"] == "recorded", "recorded decision missing from review")

        evidence, metrics, policy = _assert_common_success(
            database, scenario, final_json.stdout, final_markdown.stdout
        )
        normalized_facts = tuple(
            (item[0], item[1], item[2]) for item in evidence
        )
        return CompletedArtifacts(
            review_json=final_json.stdout,
            review_markdown=final_markdown.stdout,
            decision_output=decision_output,
            evidence_projection=evidence,
            metric_projection=metrics,
            policy_projection=policy,
            source_body_digests=_response_body_digests(scenario),
            normalized_fact_projection=normalized_facts,
        )


def _verified_partial_evidence(database: Path, assessment_id: str):
    filename = persistence._database_filename(database)
    connection = persistence._connect_read_only_v5(filename)
    try:
        _, validation_result = persistence._read_request(connection, assessment_id)
        rows = connection.execute(
            "SELECT {} FROM evidence_records WHERE assessment_id = ? "
            "ORDER BY evidence_kind".format(
                ", ".join(persistence._EVIDENCE_COLUMNS)
            ),
            (assessment_id,),
        ).fetchall()
        verified = tuple(
            persistence._verified_evidence_from_connection(
                connection, row, validation_result
            )
            for row in rows
        )
        _require(not connection.execute("PRAGMA foreign_key_check").fetchall(), "foreign key failure")
        order = {
            evidence_kind: index
            for index, evidence_kind in enumerate(EVIDENCE_ORDER)
        }
        return tuple(
            sorted(
                verified,
                key=lambda record: order[record.evidence_kind.value],
            )
        )
    finally:
        connection.rollback()
        connection.close()


def _row_count(database: Path, table: str) -> int:
    with sqlite3.connect(str(database)) as connection:
        return connection.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]


def _evaluate_rate_limit(scenario: Scenario) -> Tuple[Dict[str, object], None]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        database = Path(temporary_directory) / "evaluation.sqlite3"
        assessed, transport, evaluation_clock = _invoke_assess(
            scenario, database, evaluation_clock_forbidden=True
        )
        transport.require_complete()
        _require(assessed.exit_code == 4 and not assessed.stderr, "rate-limit scenario exit differed")
        output = json.loads(assessed.stdout)
        failure = output["collection_failure"]
        _require(output["status"] == "collection_failed", "rate-limit status differed")
        _require(failure["evidence_kind"] == "latest_commit_timestamp", "wrong failed evidence")
        _require(failure["outcome"] == "failed_retryable", "wrong failure outcome")
        _require(failure["error"]["category"] == "github_rate_limited", "wrong failure category")
        _require(output["metric_results"] == [] and output["policy_findings"] == [], "authoritative conclusions appeared")
        _require(PRIVATE_SOURCE_MARKER not in assessed.stdout, "failure leaked source body")
        _require(evaluation_clock.call_count == 0, "failure captured evaluation time")
        verified = _verified_partial_evidence(database, _assessment_id(scenario))
        projection = tuple(
            (record.evidence_kind.value, record.collection_outcome.value)
            for record in verified
        )
        _require(
            projection
            == (("repository_archived", "available"), ("license_status", "available")),
            "partial authoritative evidence differed",
        )
        _require(_row_count(database, "assessment_evaluation_snapshots") == 0, "evaluation snapshot fabricated")
        _require(_row_count(database, "human_decisions") == 0, "human decision fabricated")

        review = _review(database, scenario, "json")
        _require(review.exit_code == 5 and not review.stderr, "incomplete review failure channel differed")
        review_error = json.loads(review.stdout)
        _require(review_error["status"] == "persistence_failed", "incomplete review was presented")
        _require(review_error["error"]["category"] == "evaluation_not_found", "incomplete review failure differed")
        decide_arguments = [
            "decide", "--database", str(database), "--assessment-id", _assessment_id(scenario),
            "--assessment-evaluation-id", "assessment-evaluation-not-present",
            "--reviewer-actor-id", "actor-reviewer", "--decision", "reject",
            "--rationale", "This must not be recordable.",
        ]
        decide = _invoke_clock_free(decide_arguments)
        _require(decide.exit_code == 5 and not decide.stderr, "incomplete decision failure channel differed")
        _require(json.loads(decide.stdout)["status"] == "persistence_failed", "decision over incomplete assessment succeeded")
        _require(_row_count(database, "human_decisions") == 0, "failed decision mutated database")
        for customer_output in (assessed.stdout, review.stdout, decide.stdout):
            normalized_output = customer_output.casefold()
            _require(
                str(database).casefold() not in normalized_output,
                "rate-limit failure output leaked the temporary database path",
            )
            for forbidden_detail in (
                "sqlite",
                "operationalerror",
                "databaseerror",
                "integrityerror",
                "traceback",
                "assertionerror",
                "unexpected github transport call",
                "github source order or identity differed",
                "expected github calls did not occur",
                "network activity is forbidden",
                "select ",
                "insert ",
                "update ",
                "delete ",
                "pragma ",
                "create table",
                PRIVATE_SOURCE_MARKER.casefold(),
            ):
                _require(
                    forbidden_detail not in normalized_output,
                    "rate-limit failure output leaked internal details",
                )
        return (
            _result(
                scenario,
                evidence_projection=projection,
                metric_projection=(),
                policy_projection=(),
                decision_status="not_recordable",
                report_status="completed_assessment_not_presented",
                reproducibility_status="not_applicable",
                failure_category="github_rate_limited",
            ),
            None,
        )


def _evaluate_corruption(scenario: Scenario) -> Tuple[Dict[str, object], None]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        database = Path(temporary_directory) / "evaluation.sqlite3"
        assessed, transport, _ = _invoke_assess(scenario, database)
        transport.require_complete()
        _require(assessed.exit_code == 0, "corruption setup assessment failed")
        before = _review(database, scenario, "json")
        _require(before.exit_code == 0, "corruption setup review failed")
        before_output = json.loads(before.stdout)
        evidence = _assert_evidence(scenario, before_output)
        metrics = _assert_metrics(scenario, before_output)
        policy = _assert_policy(scenario, before_output)
        with sqlite3.connect(str(database)) as connection:
            connection.execute(
                "UPDATE assessment_evaluation_snapshots SET integrity_digest = ? "
                "WHERE assessment_id = ?",
                ("0" * 64, _assessment_id(scenario)),
            )
            connection.commit()

        review = _review(database, scenario, "markdown")
        _require(review.exit_code == 5 and not review.stderr, "corrupt review failure channel differed")
        review_error = json.loads(review.stdout)
        _require(review_error["output_schema_version"] == "assessment-review-cli-output.v1", "corrupt review schema differed")
        _require(review_error["status"] == "persistence_failed", "corrupt review status differed")
        _require(review_error["error"]["category"] == "verification_failed", "corrupt review category differed")
        serialized_error = json.dumps(review_error, sort_keys=True)
        for forbidden in ("0" * 64, "SQLite", "UPDATE", str(database)):
            _require(forbidden not in serialized_error, "corruption detail leaked")

        decide_arguments = [
            "decide", "--database", str(database), "--assessment-id", _assessment_id(scenario),
            "--assessment-evaluation-id", before_output["assessment_evaluation_id"],
            "--reviewer-actor-id", "actor-reviewer", "--decision", "reject",
            "--rationale", "A corrupt evaluation cannot support a decision.",
        ]
        decide = _invoke_clock_free(decide_arguments)
        _require(decide.exit_code == 5 and not decide.stderr, "corrupt decision failure channel differed")
        decision_error = json.loads(decide.stdout)
        _require(decision_error["error"]["category"] == "verification_failed", "corrupt decision category differed")
        _require(_row_count(database, "human_decisions") == 0, "corrupt decision mutated database")
        return (
            _result(
                scenario,
                evidence_projection=evidence,
                metric_projection=metrics,
                policy_projection=policy,
                decision_status="not_recordable",
                report_status="verification_failed_closed",
                reproducibility_status="not_applicable",
                failure_category="verification_failed",
            ),
            None,
        )


def _result(
    scenario: Scenario,
    *,
    evidence_projection: Iterable[Tuple[object, ...]],
    metric_projection: Iterable[Tuple[object, ...]],
    policy_projection: Iterable[Tuple[object, ...]],
    decision_status: str,
    report_status: str,
    reproducibility_status: str,
    failure_category: Optional[str],
    status: str = "passed",
) -> Dict[str, object]:
    return {
        "scenario_id": scenario.scenario_id,
        "terminal_expectation": scenario.terminal_expectation,
        "status": status,
        "observed_evidence_status_projection": [list(item) for item in evidence_projection],
        "metric_projection": [list(item) for item in metric_projection],
        "policy_outcome_projection": [list(item) for item in policy_projection],
        "decision_exercise_status": decision_status,
        "report_semantic_check_status": report_status,
        "reproducibility_status": reproducibility_status,
        "failure_category": failure_category,
    }


def evaluate_scenario(
    scenario: Scenario,
) -> Tuple[Dict[str, object], Optional[CompletedArtifacts]]:
    try:
        if scenario.rate_limit_latest_commit:
            return _evaluate_rate_limit(scenario)
        if scenario.corrupt_evaluation_before_review:
            return _evaluate_corruption(scenario)
        first = _run_completed_instance(scenario)
        second = _run_completed_instance(scenario)
        _require(first.review_json == second.review_json, "review JSON was not reproducible")
        _require(first.review_markdown == second.review_markdown, "review Markdown was not reproducible")
        _require(first.decision_output == second.decision_output, "decision output was not reproducible")
        decision_status = (
            "not_exercised"
            if scenario.decision is None
            else "recorded_and_verified"
        )
        return (
            _result(
                scenario,
                evidence_projection=first.evidence_projection,
                metric_projection=first.metric_projection,
                policy_projection=first.policy_projection,
                decision_status=decision_status,
                report_status="verified_json_and_markdown",
                reproducibility_status="byte_identical",
                failure_category=None,
            ),
            first,
        )
    except EvaluationMismatch:
        return (
            _result(
                scenario,
                evidence_projection=(),
                metric_projection=(),
                policy_projection=(),
                decision_status="not_verified",
                report_status="not_verified",
                reproducibility_status="not_verified",
                failure_category="expectation_mismatch",
                status="failed",
            ),
            None,
        )
    except Exception:
        return (
            _result(
                scenario,
                evidence_projection=(),
                metric_projection=(),
                policy_projection=(),
                decision_status="not_verified",
                report_status="not_verified",
                reproducibility_status="not_verified",
                failure_category="harness_defect",
                status="failed",
            ),
            None,
        )


def _assert_context_pair(
    results: List[Dict[str, object]],
    artifacts: Dict[str, CompletedArtifacts],
) -> None:
    try:
        tolerant = artifacts["E06"]
        strict = artifacts["E07"]
        _require(tolerant.source_body_digests == strict.source_body_digests, "paired source response digests differed")
        _require(tolerant.normalized_fact_projection == strict.normalized_fact_projection, "paired normalized repository facts differed")
        tolerant_metric = tuple((item[0], item[1], item[2], item[3]) for item in tolerant.metric_projection)
        strict_metric = tuple((item[0], item[1], item[2], item[3]) for item in strict.metric_projection)
        _require(tolerant_metric == strict_metric, "paired metric projections differed")
        _require(
            tuple(item[1] for item in tolerant.policy_projection)
            == ("pass", "condition_required", "pass", "condition_required"),
            "tolerant pair outcome differed",
        )
        _require(
            tuple(item[1] for item in strict.policy_projection)
            == ("pass", "fail", "fail", "fail"),
            "low-tolerance pair outcome differed",
        )
    except (KeyError, EvaluationMismatch):
        for result in results:
            if result["scenario_id"] in ("E06", "E07"):
                result["status"] = "failed"
                result["failure_category"] = "context_pair_mismatch"


def definition_versions() -> Dict[str, object]:
    return {
        "assessment_evaluation_schema_version": ASSESSMENT_EVALUATION_SCHEMA_VERSION,
        "collector_versions": dict(sorted(COLLECTOR_VERSIONS.items())),
        "evidence_normalization_versions": {
            evidence_kind: persistence.evidence_normalization_version(
                EvidenceKind(evidence_kind)
            )
            for evidence_kind in EVIDENCE_ORDER
        },
        "evidence_schema_version": "evidence-record.v1",
        "human_decision_schema_version": HUMAN_DECISION_SCHEMA_VERSION,
        "metric_definition_versions": dict(sorted(METRIC_VERSIONS.items())),
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "policy_engine_version": POLICY_ENGINE_VERSION,
        "policy_finding_schema_version": FINDING_SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "request_definition_version": REQUEST_DEFINITION_VERSION,
        "requirement_versions": dict(sorted(REQUIREMENT_VERSIONS.items())),
    }


def build_summary(results: Sequence[Dict[str, object]]) -> Dict[str, object]:
    passed_count = sum(result.get("status") == "passed" for result in results)
    return {
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "harness_version": HARNESS_VERSION,
        "definition_versions": definition_versions(),
        "scenario_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "scenario_results": list(results),
    }


def serialize_summary(summary: Dict[str, object]) -> str:
    return json.dumps(
        summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"


def run_evaluation(
    evaluator: Callable[
        [Scenario], Tuple[Dict[str, object], Optional[CompletedArtifacts]]
    ] = evaluate_scenario,
) -> Tuple[Dict[str, object], int]:
    results: List[Dict[str, object]] = []
    artifacts: Dict[str, CompletedArtifacts] = {}
    for scenario in SCENARIOS:
        result, completed = evaluator(scenario)
        results.append(result)
        if completed is not None:
            artifacts[scenario.scenario_id] = completed
    if evaluator is evaluate_scenario:
        _assert_context_pair(results, artifacts)
    summary = build_summary(results)
    return summary, 0 if summary["failed_count"] == 0 else 1


def main() -> int:
    summary, exit_code = run_evaluation()
    sys.stdout.write(serialize_summary(summary))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
