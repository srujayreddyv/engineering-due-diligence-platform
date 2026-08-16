"""Focused tests for deterministic Markdown assessment review rendering."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.cli as cli
import engineering_due_diligence.persistence as persistence
import engineering_due_diligence.workflow as workflow
from engineering_due_diligence.assessment import (
    evaluate_persisted_assessment,
)
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    LicenseStatus,
    PolicyOutcome,
    RiskTolerance,
)
from engineering_due_diligence.persistence import (
    persist_assessment_evaluation_snapshot,
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_github_security_policy_presence_collection,
    persist_valid_assessment_request,
)
from engineering_due_diligence.request import validate_assessment_request
from tests.test_durable_assessment_evaluation import (
    ASSESSMENT_ID,
    ATTEMPTED_AT,
    EVALUATED_AT,
    REPOSITORY_IDENTITY,
    _archived_result,
    _latest_result,
    _license_result,
    _security_result,
    _valid_request,
)
from tests.test_sqlite_license_status_persistence import _available_license


RECORDED_AT = datetime(2026, 8, 13, 16, 0, tzinfo=timezone.utc)


def _database_dump(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


def _section(document: str, heading: str, next_heading: str) -> str:
    start = document.index(heading)
    end = document.index(next_heading, start)
    return document[start:end]


class DeterministicReviewReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-18.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _request(self, *, tolerant=False):
        request = _valid_request().request
        if tolerant:
            request = replace(
                request,
                intended_use="Internal prototype dependency",
                environment=Environment.INTERNAL,
                criticality=Criticality.LOW,
                expected_lifetime_days=30,
                risk_tolerance=RiskTolerance.TOLERANT,
            )
        return validate_assessment_request(request)

    def _license_absent_result(self):
        raw_text = (
            '{"id":9123,"full_name":"Owner/Repository","license":null}'
        )
        return _available_license(
            LicenseStatus.ABSENT,
            raw_text=raw_text,
            assessment_id=ASSESSMENT_ID,
            repository_identity=REPOSITORY_IDENTITY,
            collection_attempt_id="collection-attempt-day-12-license-1",
            attempt_number=1,
            attempted_at=ATTEMPTED_AT,
        )

    def _persist_snapshot(
        self,
        *,
        path=None,
        unavailable_archived=True,
        tolerant=False,
        license_absent=False,
    ):
        path = path or self.database_path
        persist_valid_assessment_request(path, self._request(tolerant=tolerant))
        persist_github_repository_metadata_collection(
            path, _archived_result(unavailable=unavailable_archived)
        )
        persist_github_license_status_collection(
            path,
            self._license_absent_result()
            if license_absent
            else _license_result(),
        )
        persist_github_latest_commit_collection(path, _latest_result())
        persist_github_security_policy_presence_collection(
            path, _security_result()
        )
        result = evaluate_persisted_assessment(
            path, ASSESSMENT_ID, EVALUATED_AT
        )
        return persist_assessment_evaluation_snapshot(path, result)

    def _review_arguments(self, *, path=None, format_value=None):
        arguments = [
            "review",
            "--database",
            str(path or self.database_path),
            "--assessment-id",
            ASSESSMENT_ID,
        ]
        if format_value is not None:
            arguments.extend(("--format", format_value))
        return arguments

    def _nonpassing_ids(self, snapshot):
        return tuple(
            finding.policy_finding_id
            for finding in snapshot.policy_findings
            if finding.outcome is not PolicyOutcome.PASS
        )

    def _decide_arguments(
        self,
        snapshot,
        *,
        path=None,
        disposition="approve",
        rationale="The reviewed evidence supports adoption.",
        conditions=(),
        information_requests=(),
    ):
        acknowledgments = (
            self._nonpassing_ids(snapshot)
            if disposition in ("approve", "approve_with_conditions")
            else ()
        )
        arguments = [
            "decide",
            "--database",
            str(path or self.database_path),
            "--assessment-id",
            ASSESSMENT_ID,
            "--assessment-evaluation-id",
            snapshot.assessment_evaluation_id,
            "--reviewer-actor-id",
            "actor-reviewer",
            "--decision",
            disposition,
            "--rationale",
            rationale,
        ]
        for condition in conditions:
            arguments.extend(("--condition", condition))
        for request in information_requests:
            arguments.extend(("--information-request", request))
        for finding_id in acknowledgments:
            arguments.extend(("--acknowledge-policy-finding", finding_id))
        return arguments

    def _invoke(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with ExitStack() as stack:
            transport = stack.enter_context(
                patch(
                    "engineering_due_diligence.github."
                    "_get_public_github_repository",
                    side_effect=AssertionError("network activity is forbidden"),
                )
            )
            cli_clock = stack.enter_context(
                patch.object(
                    cli,
                    "_current_utc_time",
                    side_effect=AssertionError("CLI clock must not be read"),
                )
            )
            evaluation_clock = stack.enter_context(
                patch.object(
                    workflow,
                    "_current_evaluation_time",
                    side_effect=AssertionError(
                        "evaluation clock must not be read"
                    ),
                )
            )
            decision_clock = stack.enter_context(
                patch.object(
                    persistence,
                    "_current_decision_time",
                    return_value=RECORDED_AT,
                )
            )
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            exit_code = cli.main(arguments)
        return {
            "exit_code": exit_code,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "transport": transport,
            "cli_clock": cli_clock,
            "evaluation_clock": evaluation_clock,
            "decision_clock": decision_clock,
        }

    def test_default_and_explicit_json_review_are_byte_identical(self):
        self._persist_snapshot()

        default = self._invoke(self._review_arguments())
        explicit = self._invoke(
            self._review_arguments(format_value="json")
        )

        self.assertEqual(default["exit_code"], 0)
        self.assertEqual(default["stderr"], "")
        self.assertEqual(default["stdout"], explicit["stdout"])
        output = json.loads(default["stdout"])
        self.assertEqual(
            output["output_schema_version"],
            "assessment-review-cli-output.v1",
        )
        self.assertEqual(output["status"], "review_complete")

    def test_markdown_has_complete_ordered_structure_and_version(self):
        snapshot = self._persist_snapshot()

        invoked = self._invoke(
            self._review_arguments(format_value="markdown")
        )

        self.assertEqual(invoked["exit_code"], 0)
        self.assertEqual(invoked["stderr"], "")
        report = invoked["stdout"]
        self.assertIn(
            "**Report version:** assessment-review-report.v1", report
        )
        headings = (
            "## Assessment at a glance",
            "## Items requiring attention",
            "## Evidence observed",
            "## Unavailable information",
            "## Deterministic metrics",
            "## Policy requirements",
            "## Human decision",
            "## Technical provenance",
        )
        self.assertEqual(
            [report.index(heading) for heading in headings],
            sorted(report.index(heading) for heading in headings),
        )

        evidence = _section(
            report, "## Evidence observed", "## Unavailable information"
        )
        evidence_labels = (
            "Repository archived",
            "Detected license metadata",
            "Latest commit timestamp",
            "Effective security policy presence",
        )
        self.assertEqual(
            [evidence.index(label) for label in evidence_labels],
            sorted(evidence.index(label) for label in evidence_labels),
        )
        metrics = _section(
            report, "## Deterministic metrics", "## Policy requirements"
        )
        self.assertEqual(
            [
                metrics.index(item.metric_name)
                for item in snapshot.metric_results
            ],
            sorted(
                metrics.index(item.metric_name)
                for item in snapshot.metric_results
            ),
        )
        policies = _section(
            report, "## Policy requirements", "## Human decision"
        )
        self.assertEqual(
            [
                policies.index(item.requirement_id)
                for item in snapshot.policy_findings
            ],
            sorted(
                policies.index(item.requirement_id)
                for item in snapshot.policy_findings
            ),
        )
        self.assertNotIn("overall recommendation", report.lower().replace(
            "does not provide an overall recommendation", ""
        ))

    def test_policy_counts_and_required_acknowledgments_are_exact(self):
        snapshot = self._persist_snapshot()

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        counts = {
            outcome: sum(
                finding.outcome is outcome
                for finding in snapshot.policy_findings
            )
            for outcome in PolicyOutcome
        }
        for outcome in PolicyOutcome:
            self.assertIn(
                "- **{}:** {}".format(outcome.value, counts[outcome]),
                report,
            )
        acknowledgments = _section(
            report,
            "### Required approval acknowledgment finding IDs",
            "## Evidence observed",
        )
        expected_ids = self._nonpassing_ids(snapshot)
        self.assertEqual(
            [acknowledgments.index(finding_id) for finding_id in expected_ids],
            sorted(
                acknowledgments.index(finding_id)
                for finding_id in expected_ids
            ),
        )
        self.assertEqual(
            sum(acknowledgments.count(finding_id) for finding_id in expected_ids),
            len(expected_ids),
        )

    def test_markdown_review_is_read_only_clock_free_and_byte_deterministic(self):
        self._persist_snapshot()
        before = _database_dump(self.database_path)

        first = self._invoke(
            self._review_arguments(format_value="markdown")
        )
        second = self._invoke(
            self._review_arguments(format_value="markdown")
        )

        self.assertEqual(first["stdout"], second["stdout"])
        self.assertEqual(_database_dump(self.database_path), before)
        for invoked in (first, second):
            self.assertEqual(invoked["exit_code"], 0)
            invoked["transport"].assert_not_called()
            invoked["cli_clock"].assert_not_called()
            invoked["evaluation_clock"].assert_not_called()
            invoked["decision_clock"].assert_not_called()

    def test_unavailable_evidence_is_not_rendered_as_a_negative_fact(self):
        self._persist_snapshot(unavailable_archived=True)

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        evidence = _section(
            report,
            "### 1. Repository archived",
            "### 2. Detected license metadata",
        )
        self.assertIn("- **Status:** unavailable", evidence)
        self.assertNotIn("Normalized value", evidence)
        unavailable = _section(
            report, "## Unavailable information", "## Deterministic metrics"
        )
        self.assertIn(
            "Unavailable means the fact was not established. It must not be "
            "interpreted as false, absent, or unfavorable.",
            unavailable,
        )
        self.assertIn("repository_not_publicly_available", unavailable)
        self.assertIn("repository_archived", unavailable)
        self.assertIn("repository_not_archived", unavailable)

    def test_report_explicitly_states_when_all_information_is_available(self):
        self._persist_snapshot(unavailable_archived=False)

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        unavailable = _section(
            report, "## Unavailable information", "## Deterministic metrics"
        )
        self.assertIn(
            "No required evidence or deterministic metric was unavailable or "
            "unusable at the stored evaluation time.",
            unavailable,
        )

    def test_report_states_when_no_human_decision_exists(self):
        self._persist_snapshot()

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        decision = _section(
            report, "## Human decision", "## Technical provenance"
        )
        self.assertIn("No human decision has been recorded.", decision)
        self.assertIn(
            "Actor identity is caller asserted and not authenticated.",
            decision,
        )

    def test_recorded_decision_and_provenance_are_rendered_exactly(self):
        snapshot = self._persist_snapshot()
        verified_evidence = persistence.load_verified_assessment_review(
            self.database_path, ASSESSMENT_ID
        )[0]
        recorded = self._invoke(self._decide_arguments(snapshot))
        self.assertEqual(recorded["exit_code"], 0)
        stored = json.loads(recorded["stdout"])

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        decision = _section(
            report, "## Human decision", "## Technical provenance"
        )
        self.assertIn("- **Disposition:** approve", decision)
        self.assertIn(
            "- **Decision maker actor ID:** actor-reviewer", decision
        )
        self.assertIn(RECORDED_AT.isoformat(), decision)
        self.assertIn(stored["rationale"], decision)
        provenance = report[report.index("## Technical provenance") :]
        self.assertIn(snapshot.assessment_evaluation_id, provenance)
        self.assertIn(snapshot.integrity_digest, provenance)
        self.assertIn(stored["human_decision_id"], provenance)
        self.assertIn("human-decision.v1", provenance)
        expected_normalization_versions = {
            "repository_archived": "repository-archived-normalization.v1",
            "license_status": "license-status-normalization.v1",
            "latest_commit_timestamp": "latest-commit-normalization.v1",
            "security_policy_present": (
                "security-policy-presence-normalization.v1"
            ),
        }
        for evidence_kind, evidence_id in snapshot.evidence_references:
            self.assertIn(evidence_kind.value, provenance)
            self.assertIn(evidence_id, provenance)
        for index, evidence in enumerate(verified_evidence.evidence_records):
            self.assertIn(evidence.collector_name, provenance)
            self.assertIn(evidence.collector_version, provenance)
            self.assertIn(evidence.collection_attempt_id, provenance)
            evidence_provenance = _section(
                provenance,
                "#### {}".format(cli._EVIDENCE_LABELS[evidence.evidence_kind]),
                (
                    "#### {}".format(
                        cli._EVIDENCE_LABELS[
                            verified_evidence.evidence_records[
                                index + 1
                            ].evidence_kind
                        ]
                    )
                    if index + 1 < len(verified_evidence.evidence_records)
                    else "### Metric result provenance"
                ),
            )
            self.assertIn(
                "- **Normalization version:** {}".format(
                    expected_normalization_versions[evidence.evidence_kind.value]
                ),
                evidence_provenance,
            )
            self.assertIn(
                "- **Evidence schema version:** {}".format(
                    evidence.evidence_schema_version
                ),
                evidence_provenance,
            )
            for key, value in evidence.provenance:
                self.assertIn(key, provenance)
                self.assertIn(value, provenance)
            if evidence.integrity_digest is not None:
                self.assertIn(evidence.integrity_digest, provenance)
        self.assertNotIn(
            "Normalization contract / evidence schema version", provenance
        )
        for metric in snapshot.metric_results:
            self.assertIn(metric.metric_result_id, provenance)
            self.assertIn(metric.calculation_attempt_id, provenance)
            self.assertIn(metric.metric_definition_version, provenance)
            self.assertIn(metric.metric_schema_version, provenance)
            self.assertIn(metric.input_digest, provenance)
        for finding in snapshot.policy_findings:
            self.assertIn(finding.policy_finding_id, provenance)
            self.assertIn(finding.policy_evaluation_id, provenance)
            self.assertIn(finding.policy_version, provenance)
            self.assertIn(finding.policy_engine_version, provenance)
            self.assertIn(finding.requirement_version, provenance)
            self.assertIn(finding.finding_schema_version, provenance)

    def test_policy_template_and_human_conditions_remain_distinct(self):
        snapshot = self._persist_snapshot(
            unavailable_archived=False,
            tolerant=True,
            license_absent=True,
        )
        policy_condition = next(
            finding.condition_template
            for finding in snapshot.policy_findings
            if finding.outcome is PolicyOutcome.CONDITION_REQUIRED
        )
        human_condition = "Obtain counsel review before production adoption."
        recorded = self._invoke(
            self._decide_arguments(
                snapshot,
                disposition="approve_with_conditions",
                conditions=(human_condition,),
            )
        )
        self.assertEqual(recorded["exit_code"], 0)

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        policies = _section(
            report, "## Policy requirements", "## Human decision"
        )
        decision = _section(
            report, "## Human decision", "## Technical provenance"
        )
        self.assertIn(
            "Deterministic policy condition template", policies
        )
        self.assertIn(policy_condition, policies)
        self.assertNotIn(human_condition, policies)
        self.assertIn("Human-recorded adoption conditions", decision)
        self.assertIn(human_condition, decision)
        self.assertNotIn(policy_condition, decision)
        self.assertIn(
            "Adoption was accepted subject to the recorded conditions.",
            decision,
        )
        self.assertIn(
            "does not track or verify condition fulfillment", decision
        )
        self.assertNotIn("[ ]", report)
        self.assertNotIn("[x]", report.lower())

    def test_needs_more_information_is_rendered_as_immutable_disposition(self):
        snapshot = self._persist_snapshot()
        information_request = "Provide an accountable operating owner."
        recorded = self._invoke(
            self._decide_arguments(
                snapshot,
                disposition="needs_more_information",
                rationale="Ownership is not established.",
                information_requests=(information_request,),
            )
        )
        self.assertEqual(recorded["exit_code"], 0)

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        decision = _section(
            report, "## Human decision", "## Technical provenance"
        )
        self.assertIn("needs_more_information", decision)
        self.assertIn(information_request, decision)
        self.assertIn(
            "Needs more information is the immutable disposition for this "
            "assessment under the current model.",
            decision,
        )

    def test_raw_source_bodies_and_hidden_state_are_absent(self):
        self._persist_snapshot(unavailable_archived=False)

        report = self._invoke(
            self._review_arguments(format_value="markdown")
        )["stdout"]

        self.assertNotIn("raw_snapshot", report)
        self.assertNotIn("response_bytes", report)
        self.assertNotIn('"unrelated"', report)
        self.assertNotIn("snapshot_json", report)
        self.assertNotIn(str(self.database_path), report)
        self.assertNotIn("SQLite", report)
        self.assertNotIn("traceback", report.lower())

    def test_corrupt_state_uses_existing_sanitized_json_failure(self):
        self._persist_snapshot()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE assessment_evaluation_snapshots "
                "SET integrity_digest = ?",
                ("0" * 64,),
            )
            connection.commit()

        invoked = self._invoke(
            self._review_arguments(format_value="markdown")
        )

        self.assertEqual(invoked["exit_code"], 5)
        output = json.loads(invoked["stdout"])
        self.assertEqual(
            output["output_schema_version"],
            "assessment-review-cli-output.v1",
        )
        self.assertEqual(output["error"]["category"], "verification_failed")
        self.assertNotIn(str(self.database_path), invoked["stdout"])
        self.assertNotIn("UPDATE", invoked["stdout"])


if __name__ == "__main__":
    unittest.main()
