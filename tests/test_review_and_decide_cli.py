"""Focused tests for the read-only review and immutable decide commands."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
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
    HumanDecisionDisposition,
    PolicyOutcome,
)
from engineering_due_diligence.persistence import (
    load_verified_human_decision,
    persist_assessment_evaluation_snapshot,
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_github_security_policy_presence_collection,
    persist_valid_assessment_request,
)
from tests.test_durable_assessment_evaluation import (
    ASSESSMENT_ID,
    EVALUATED_AT,
    _archived_result,
    _latest_result,
    _license_result,
    _security_result,
    _valid_request,
)


RECORDED_AT = datetime(2026, 8, 13, 16, 0, tzinfo=timezone.utc)


def _database_dump(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


class ReviewAndDecideCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-17.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _persist_evidence(self, path=None):
        path = path or self.database_path
        persist_valid_assessment_request(path, _valid_request())
        persist_github_repository_metadata_collection(
            path, _archived_result(unavailable=True)
        )
        persist_github_license_status_collection(path, _license_result())
        persist_github_latest_commit_collection(path, _latest_result())
        persist_github_security_policy_presence_collection(
            path, _security_result()
        )
        return path

    def _persist_snapshot(self, path=None):
        path = self._persist_evidence(path)
        result = evaluate_persisted_assessment(
            path, ASSESSMENT_ID, EVALUATED_AT
        )
        return persist_assessment_evaluation_snapshot(path, result)

    def _review_arguments(self, path=None, assessment_id=ASSESSMENT_ID):
        return [
            "review",
            "--database",
            str(path or self.database_path),
            "--assessment-id",
            assessment_id,
        ]

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
        assessment_id=ASSESSMENT_ID,
        evaluation_id=None,
        reviewer_actor_id="actor-reviewer",
        disposition="approve",
        rationale="The reviewed evidence supports adoption.",
        conditions=(),
        information_requests=(),
        acknowledgments=None,
    ):
        if acknowledgments is None:
            acknowledgments = (
                self._nonpassing_ids(snapshot)
                if disposition in (
                    "approve",
                    "approve_with_conditions",
                )
                else ()
            )
        arguments = [
            "decide",
            "--database",
            str(path or self.database_path),
            "--assessment-id",
            assessment_id,
            "--assessment-evaluation-id",
            evaluation_id or snapshot.assessment_evaluation_id,
            "--reviewer-actor-id",
            reviewer_actor_id,
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

    def _invoke(self, arguments, *, recorded_at=RECORDED_AT):
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
                    return_value=recorded_at,
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

    def test_review_returns_complete_exact_durable_input_without_mutation(self):
        snapshot = self._persist_snapshot()
        before = _database_dump(self.database_path)

        invoked = self._invoke(self._review_arguments())

        self.assertEqual(invoked["exit_code"], 0)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(
            output["output_schema_version"],
            "assessment-review-cli-output.v1",
        )
        self.assertEqual(output["status"], "review_complete")
        self.assertEqual(output["assessment_id"], ASSESSMENT_ID)
        self.assertEqual(
            output["repository_identity"], "github.com/Owner/Repository"
        )
        self.assertEqual(
            output["assessment_context"]["intended_use"],
            "Critical production authentication dependency",
        )
        self.assertEqual(
            output["submitted_at"], _valid_request().request.submitted_at.isoformat()
        )
        self.assertEqual(
            output["responsible_reviewer_actor_id"], "actor-reviewer"
        )
        self.assertEqual(
            output["assessment_evaluation_id"],
            snapshot.assessment_evaluation_id,
        )
        self.assertEqual(
            output["evaluated_at"], snapshot.evaluated_at.isoformat()
        )
        self.assertEqual(
            output["evaluation_schema_version"],
            snapshot.evaluation_schema_version,
        )
        self.assertEqual(output["integrity_digest"], snapshot.integrity_digest)
        expected_kinds = [
            "repository_archived",
            "license_status",
            "latest_commit_timestamp",
            "security_policy_present",
        ]
        self.assertEqual(
            [item["evidence_kind"] for item in output["evidence_records"]],
            expected_kinds,
        )
        self.assertEqual(
            [item["evidence_kind"] for item in output["evidence_references"]],
            expected_kinds,
        )
        self.assertEqual(len(output["metric_results"]), 4)
        self.assertEqual(len(output["policy_findings"]), 4)
        self.assertTrue(
            all(
                set(metric)
                == {
                    "metric_result_id",
                    "assessment_id",
                    "calculation_attempt_id",
                    "metric_name",
                    "metric_definition_version",
                    "input_evidence_ids",
                    "input_digest",
                    "calculated_at",
                    "result_status",
                    "input_sufficiency",
                    "metric_schema_version",
                    "value",
                    "unit",
                    "reason_code",
                }
                for metric in output["metric_results"]
            )
        )
        self.assertTrue(
            all(
                set(finding)
                == {
                    "policy_finding_id",
                    "assessment_id",
                    "policy_id",
                    "policy_version",
                    "policy_engine_version",
                    "policy_evaluation_id",
                    "requirement_id",
                    "requirement_version",
                    "outcome",
                    "input_evidence_ids",
                    "input_metric_result_ids",
                    "deterministic_reason",
                    "evaluated_at",
                    "finding_schema_version",
                    "condition_template",
                }
                for finding in output["policy_findings"]
            )
        )
        self.assertEqual(
            [metric["metric_result_id"] for metric in output["metric_results"]],
            [metric.metric_result_id for metric in snapshot.metric_results],
        )
        self.assertEqual(
            [
                finding["policy_finding_id"]
                for finding in output["policy_findings"]
            ],
            [
                finding.policy_finding_id
                for finding in snapshot.policy_findings
            ],
        )
        self.assertEqual(
            output["required_approval_acknowledgments"],
            list(self._nonpassing_ids(snapshot)),
        )
        self.assertEqual(
            output["human_decision"], {"status": "not_recorded"}
        )
        self.assertNotIn("recommendation", output)
        self.assertNotIn("raw_snapshot", invoked["stdout"])
        self.assertNotIn("response_bytes", invoked["stdout"])
        self.assertEqual(_database_dump(self.database_path), before)
        invoked["transport"].assert_not_called()
        invoked["cli_clock"].assert_not_called()
        invoked["evaluation_clock"].assert_not_called()
        invoked["decision_clock"].assert_not_called()

    def test_review_returns_the_verified_existing_decision(self):
        snapshot = self._persist_snapshot()
        arguments = self._decide_arguments(
            snapshot,
            disposition="approve_with_conditions",
            conditions=("Pin the reviewed major version.",),
        )
        recorded = self._invoke(arguments)
        self.assertEqual(recorded["exit_code"], 0)

        reviewed = self._invoke(self._review_arguments())

        output = json.loads(reviewed["stdout"])
        decision = output["human_decision"]
        self.assertEqual(decision["status"], "recorded")
        self.assertEqual(
            decision["human_decision_id"],
            json.loads(recorded["stdout"])["human_decision_id"],
        )
        self.assertEqual(
            decision["conditions"], ["Pin the reviewed major version."]
        )
        self.assertEqual(decision["recorded_at"], RECORDED_AT.isoformat())
        reviewed["decision_clock"].assert_not_called()

    def test_review_missing_request_or_evaluation_has_safe_specific_failure(self):
        connection = persistence._connect(str(self.database_path))
        connection.close()
        missing = self._invoke(self._review_arguments())
        self.assertEqual(missing["exit_code"], 5)
        missing_output = json.loads(missing["stdout"])
        self.assertEqual(missing_output["status"], "persistence_failed")
        self.assertEqual(missing_output["error"]["category"], "request_not_found")

        request_only_path = (
            Path(self.temporary_directory.name) / "request-only.sqlite3"
        )
        persist_valid_assessment_request(request_only_path, _valid_request())
        no_evaluation = self._invoke(
            self._review_arguments(path=request_only_path)
        )
        self.assertEqual(no_evaluation["exit_code"], 5)
        self.assertEqual(
            json.loads(no_evaluation["stdout"])["error"]["category"],
            "evaluation_not_found",
        )

    def test_review_corrupt_evaluation_or_decision_fails_closed(self):
        for corruption in ("evaluation", "decision"):
            with self.subTest(corruption=corruption):
                path = Path(self.temporary_directory.name) / (
                    corruption + ".sqlite3"
                )
                snapshot = self._persist_snapshot(path)
                if corruption == "decision":
                    recorded = self._invoke(
                        self._decide_arguments(snapshot, path=path)
                    )
                    self.assertEqual(recorded["exit_code"], 0)
                with sqlite3.connect(path) as connection:
                    if corruption == "evaluation":
                        connection.execute(
                            "UPDATE assessment_evaluation_snapshots "
                            "SET integrity_digest = ?",
                            ("0" * 64,),
                        )
                    else:
                        connection.execute(
                            "UPDATE human_decisions SET rationale = ?",
                            ("Corrupted rationale.",),
                        )
                    connection.commit()

                invoked = self._invoke(self._review_arguments(path=path))

                self.assertEqual(invoked["exit_code"], 5)
                output = json.loads(invoked["stdout"])
                self.assertEqual(
                    output["error"]["category"], "verification_failed"
                )
                self.assertNotIn("UPDATE", invoked["stdout"])
                self.assertNotIn(str(path), invoked["stdout"])

    def test_decide_supports_all_four_dispositions(self):
        cases = (
            ("approve", (), (), True),
            (
                "approve_with_conditions",
                ("Pin the reviewed major version.",),
                (),
                True,
            ),
            (
                "needs_more_information",
                (),
                ("Provide the operating owner.",),
                False,
            ),
            ("reject", (), (), False),
        )
        for index, (disposition, conditions, requests, acknowledge) in enumerate(
            cases
        ):
            with self.subTest(disposition=disposition):
                path = Path(self.temporary_directory.name) / (
                    "disposition-{}.sqlite3".format(index)
                )
                snapshot = self._persist_snapshot(path)
                acknowledgments = (
                    self._nonpassing_ids(snapshot) if acknowledge else ()
                )

                invoked = self._invoke(
                    self._decide_arguments(
                        snapshot,
                        path=path,
                        disposition=disposition,
                        conditions=conditions,
                        information_requests=requests,
                        acknowledgments=acknowledgments,
                    )
                )

                self.assertEqual(invoked["exit_code"], 0)
                output = json.loads(invoked["stdout"])
                self.assertEqual(
                    output["output_schema_version"],
                    "human-decision-cli-output.v1",
                )
                self.assertEqual(output["status"], "recorded")
                self.assertEqual(output["assessment_id"], ASSESSMENT_ID)
                self.assertEqual(
                    output["assessment_evaluation_id"],
                    snapshot.assessment_evaluation_id,
                )
                self.assertEqual(
                    output["decision_maker_actor_id"], "actor-reviewer"
                )
                self.assertEqual(output["disposition"], disposition)
                self.assertEqual(
                    output["rationale"],
                    "The reviewed evidence supports adoption.",
                )
                self.assertEqual(output["conditions"], list(conditions))
                self.assertEqual(
                    output["information_requests"], list(requests)
                )
                self.assertEqual(
                    output["acknowledged_policy_finding_ids"],
                    list(acknowledgments),
                )
                self.assertEqual(
                    output["actor_identity_assurance"],
                    "caller_asserted_not_authenticated",
                )
                self.assertEqual(
                    output["recorded_at"], RECORDED_AT.isoformat()
                )
                self.assertEqual(
                    output["decision_schema_version"], "human-decision.v1"
                )
                stored = load_verified_human_decision(path, ASSESSMENT_ID)
                self.assertEqual(
                    stored.human_decision_id, output["human_decision_id"]
                )
                invoked["transport"].assert_not_called()
                invoked["cli_clock"].assert_not_called()
                invoked["evaluation_clock"].assert_not_called()
                invoked["decision_clock"].assert_called_once_with()

    def test_decide_preserves_repeated_argument_order(self):
        snapshot = self._persist_snapshot()
        conditions = (
            "Pin the reviewed major version.",
            "Document the adoption owner.",
        )
        invoked = self._invoke(
            self._decide_arguments(
                snapshot,
                disposition="approve_with_conditions",
                conditions=conditions,
            )
        )

        self.assertEqual(invoked["exit_code"], 0)
        self.assertEqual(
            json.loads(invoked["stdout"])["conditions"], list(conditions)
        )

    def test_decide_rejects_invalid_acknowledgment_reviewer_and_evaluation(self):
        cases = (
            {"acknowledgments": ()},
            {"reviewer_actor_id": "actor-other"},
            {"evaluation_id": "assessment-evaluation-" + "0" * 64},
            {"disposition": "unsupported"},
        )
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                path = Path(self.temporary_directory.name) / (
                    "invalid-{}.sqlite3".format(index)
                )
                snapshot = self._persist_snapshot(path)

                invoked = self._invoke(
                    self._decide_arguments(snapshot, path=path, **changes)
                )

                self.assertEqual(invoked["exit_code"], 3)
                output = json.loads(invoked["stdout"])
                self.assertEqual(output["status"], "validation_failed")
                self.assertEqual(
                    output["error"],
                    {
                        "category": "invalid_decision",
                        "message": "The human decision input is invalid.",
                    },
                )
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM human_decisions"
                        ).fetchone()[0],
                        0,
                    )

    def test_exact_decision_replay_preserves_identity_time_and_bytes(self):
        snapshot = self._persist_snapshot()
        arguments = self._decide_arguments(snapshot)
        first = self._invoke(arguments)
        before = _database_dump(self.database_path)

        second = self._invoke(
            arguments,
            recorded_at=RECORDED_AT.replace(day=14),
        )

        self.assertEqual(second["exit_code"], 0)
        first_output = json.loads(first["stdout"])
        second_output = json.loads(second["stdout"])
        self.assertEqual(second_output["status"], "exact_replay")
        self.assertEqual(
            second_output["human_decision_id"],
            first_output["human_decision_id"],
        )
        self.assertEqual(
            second_output["recorded_at"], first_output["recorded_at"]
        )
        self.assertEqual(_database_dump(self.database_path), before)
        second["decision_clock"].assert_not_called()

    def test_changed_decision_replay_conflicts_without_mutation(self):
        snapshot = self._persist_snapshot()
        recorded = self._invoke(self._decide_arguments(snapshot))
        self.assertEqual(recorded["exit_code"], 0)
        before = _database_dump(self.database_path)

        conflict = self._invoke(
            self._decide_arguments(
                snapshot, rationale="A materially different rationale."
            )
        )

        self.assertEqual(conflict["exit_code"], 6)
        output = json.loads(conflict["stdout"])
        self.assertEqual(output["status"], "conflicting_decision")
        self.assertEqual(
            output["error"]["category"], "conflicting_replay"
        )
        self.assertEqual(_database_dump(self.database_path), before)
        conflict["decision_clock"].assert_not_called()

    def test_decide_reloads_verified_evaluation_before_persistence(self):
        snapshot = self._persist_snapshot()
        with patch.object(
            cli,
            "load_verified_assessment_evaluation_snapshot",
            wraps=cli.load_verified_assessment_evaluation_snapshot,
        ) as loader:
            invoked = self._invoke(self._decide_arguments(snapshot))

        self.assertEqual(invoked["exit_code"], 0)
        loader.assert_called_once_with(
            str(self.database_path), ASSESSMENT_ID
        )

    def test_decide_fails_before_write_when_evaluation_is_corrupt(self):
        snapshot = self._persist_snapshot()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE assessment_evaluation_snapshots "
                "SET integrity_digest = ?",
                ("0" * 64,),
            )
            connection.commit()

        invoked = self._invoke(self._decide_arguments(snapshot))

        self.assertEqual(invoked["exit_code"], 5)
        output = json.loads(invoked["stdout"])
        self.assertEqual(output["error"]["category"], "verification_failed")
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM human_decisions"
                ).fetchone()[0],
                0,
            )
        invoked["decision_clock"].assert_not_called()

    def test_review_and_decide_unexpected_errors_are_constant_and_safe(self):
        unsafe = "secret SQL /private/database.sqlite3 traceback"
        cases = (
            (
                self._review_arguments(),
                "load_verified_assessment_review",
                "assessment-review-cli-output.v1",
                "The assessment review could not be loaded.",
            ),
            (
                [
                    "decide",
                    "--database",
                    str(self.database_path),
                    "--assessment-id",
                    ASSESSMENT_ID,
                    "--assessment-evaluation-id",
                    "assessment-evaluation-id",
                    "--reviewer-actor-id",
                    "actor-reviewer",
                    "--decision",
                    "approve",
                    "--rationale",
                    "Rationale.",
                ],
                "load_verified_assessment_evaluation_snapshot",
                "human-decision-cli-output.v1",
                "The human decision could not be recorded.",
            ),
        )
        for arguments, target, schema_version, message in cases:
            with self.subTest(target=target):
                with patch.object(
                    cli, target, side_effect=RuntimeError(unsafe)
                ):
                    invoked = self._invoke(arguments)

                self.assertEqual(invoked["exit_code"], 1)
                self.assertEqual(invoked["stdout"], "")
                output = json.loads(invoked["stderr"])
                self.assertEqual(
                    output["output_schema_version"], schema_version
                )
                self.assertEqual(
                    output["error"],
                    {"category": "internal_error", "message": message},
                )
                self.assertNotIn(unsafe, invoked["stderr"])
                self.assertNotIn("traceback", invoked["stderr"].casefold())
                self.assertNotIn("select", invoked["stderr"].casefold())

    def test_decide_usage_and_persistence_failures_are_versioned_and_safe(self):
        usage = self._invoke(["decide", "--database", "secret.sqlite3"])
        self.assertEqual(usage["exit_code"], 2)
        self.assertEqual(usage["stdout"], "")
        usage_output = json.loads(usage["stderr"])
        self.assertEqual(
            usage_output["output_schema_version"],
            "human-decision-cli-output.v1",
        )
        self.assertEqual(usage_output["status"], "usage_error")

        snapshot = self._persist_snapshot()
        arguments = self._decide_arguments(snapshot)
        database_index = arguments.index("--database") + 1
        arguments[database_index] = ":memory:"
        failed = self._invoke(arguments)
        self.assertEqual(failed["exit_code"], 5)
        output = json.loads(failed["stdout"])
        self.assertEqual(output["status"], "persistence_failed")
        self.assertEqual(
            output["error"]["category"], "invalid_database_path"
        )
        self.assertNotIn(":memory:", failed["stdout"])
        self.assertNotIn("sqlite3", failed["stdout"].casefold())


if __name__ == "__main__":
    unittest.main()
