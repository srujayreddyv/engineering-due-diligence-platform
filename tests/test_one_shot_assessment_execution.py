"""Focused tests for one-shot assessment execution."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.workflow as workflow
from engineering_due_diligence.assessment import (
    evaluate_persisted_assessment,
)
from engineering_due_diligence.github import GitHubCollectionOutcome
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    MetricStatus,
    PolicyOutcome,
    RiskTolerance,
)
from engineering_due_diligence.persistence import SQLitePersistenceError
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
)
from engineering_due_diligence.workflow import (
    AssessmentExecutionInput,
    AssessmentExecutionResult,
    AssessmentExecutionStatus,
    execute_assessment,
)


ASSESSMENT_ID = "assessment-day-13"
REPOSITORY_IDENTITY = "github.com/Owner/Repository"
REPOSITORY_ENDPOINT = "https://api.github.com/repos/Owner/Repository"
COMMITS_ENDPOINT = REPOSITORY_ENDPOINT + "/commits?per_page=1"
POLICY_ENDPOINT = (
    REPOSITORY_ENDPOINT + "/contents/.github/SECURITY.md"
)
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
POLICY_SHA = "a" * 40
SUBMITTED_AT = datetime(
    2026,
    8,
    9,
    8,
    30,
    tzinfo=timezone(timedelta(hours=5, minutes=30)),
)
ATTEMPTED_AT = datetime(
    2026, 8, 9, 9, 0, tzinfo=timezone(timedelta(hours=-7))
)
EVALUATED_AT = datetime(
    2026, 8, 10, 11, 15, tzinfo=timezone(timedelta(hours=2))
)


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _request(**changes):
    values = {
        "assessment_id": ASSESSMENT_ID,
        "submitted_repository_locator": (
            "https://github.com/Owner/Repository"
        ),
        "intended_use": "Critical production authentication dependency",
        "environment": Environment.PRODUCTION,
        "criticality": Criticality.CRITICAL,
        "expected_lifetime_days": 1_825,
        "risk_tolerance": RiskTolerance.LOW,
        "submitted_by_actor_id": "actor-submitter",
        "responsible_reviewer_actor_id": "actor-reviewer",
        "submitted_at": SUBMITTED_AT,
        "request_definition_version": REQUEST_DEFINITION_VERSION,
    }
    values.update(changes)
    return AssessmentRequestInput(**values)


def _execution_input(request=None):
    return AssessmentExecutionInput(
        request=request or _request(),
        collection_attempted_at=ATTEMPTED_AT,
    )


def _archived_response(*, archived=False):
    return (
        200,
        _json_bytes(
            {
                "id": 101,
                "full_name": "Owner/Repository",
                "archived": archived,
                "unrelated": {"preserved": True},
            }
        ),
        (("ETag", '"archived-etag"'),),
    )


def _license_response():
    return (
        200,
        _json_bytes(
            {
                "id": 101,
                "full_name": "Owner/Repository",
                "license": {
                    "key": "mit",
                    "name": "MIT License",
                    "spdx_id": "MIT",
                },
                "unrelated": ["preserved"],
            }
        ),
        (("ETag", '"license-etag"'),),
    )


def _latest_response(
    *,
    empty=False,
    committer_date="2026-08-07T09:15:16-05:00",
):
    payload = [] if empty else [
        {
            "sha": COMMIT_SHA,
            "url": REPOSITORY_ENDPOINT + "/commits/" + COMMIT_SHA,
            "commit": {
                "author": {"date": "1999-01-01T00:00:00Z"},
                "committer": {"date": committer_date},
            },
            "unrelated": {"preserved": True},
        }
    ]
    return (200, _json_bytes(payload), (("ETag", '"commit-etag"'),))


def _security_repository_response():
    return (
        200,
        _json_bytes(
            {
                "id": 101,
                "full_name": "Owner/Repository",
                "unrelated": [1, 2],
            }
        ),
        (("ETag", '"security-repository-etag"'),),
    )


def _security_policy_response():
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
                "content": "cG9saWN5",
                "unrelated": {"preserved": True},
            }
        ),
        (("ETag", '"policy-etag"'),),
    )


def _successful_responses(
    *,
    latest_empty=False,
    archived=False,
    latest_committer_date="2026-08-07T09:15:16-05:00",
):
    return [
        _archived_response(archived=archived),
        _license_response(),
        _latest_response(
            empty=latest_empty,
            committer_date=latest_committer_date,
        ),
        _security_repository_response(),
        _security_policy_response(),
    ]


def _database_dump(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


def _row_counts(path):
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0]
            for table in (
                "assessment_requests",
                "collection_attempts",
                "github_source_snapshots",
                "evidence_records",
                "github_source_observations",
            )
        }


class OneShotAssessmentExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-13.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _execute(
        self,
        responses,
        execution_input=None,
        evaluation_time=EVALUATED_AT,
    ):
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=responses,
        ) as transport, patch.object(
            workflow,
            "_current_evaluation_time",
            return_value=evaluation_time,
        ) as clock:
            result = execute_assessment(
                self.database_path,
                execution_input or _execution_input(),
            )
        return result, transport, clock

    def test_contracts_are_frozen_and_reject_contradictory_results(self):
        execution_input = _execution_input()
        invalid_result, _, clock = self._execute(
            [],
            replace(
                execution_input,
                request=replace(execution_input.request, intended_use=""),
            ),
        )
        self.assertEqual(
            tuple(status.value for status in AssessmentExecutionStatus),
            ("invalid_request", "collection_failed", "complete"),
        )
        self.assertFalse(hasattr(execution_input, "evaluated_at"))
        self.assertIs(
            execution_input.collection_attempted_at, ATTEMPTED_AT
        )
        with self.assertRaises(TypeError):
            AssessmentExecutionInput(
                request=execution_input.request,
                collection_attempted_at=ATTEMPTED_AT,
                evaluated_at=EVALUATED_AT,
            )
        with self.assertRaises(FrozenInstanceError):
            execution_input.collection_attempted_at = EVALUATED_AT
        with self.assertRaises(FrozenInstanceError):
            invalid_result.status = AssessmentExecutionStatus.COMPLETE
        with self.assertRaises(ValueError):
            replace(
                execution_input,
                collection_attempted_at=ATTEMPTED_AT.replace(tzinfo=None),
            )
        with self.assertRaises(ValueError):
            AssessmentExecutionResult(
                execution_input=execution_input,
                validation_result=invalid_result.validation_result,
                status=AssessmentExecutionStatus.COMPLETE,
                failure=None,
                assessment_result=None,
            )
        clock.assert_not_called()

    def test_complete_execution_returns_four_verified_kinds(self):
        execution_input = _execution_input()
        result, transport, clock = self._execute(
            _successful_responses(), execution_input
        )

        self.assertIs(result.status, AssessmentExecutionStatus.COMPLETE)
        self.assertIs(result.execution_input, execution_input)
        self.assertIs(result.validation_result.request, execution_input.request)
        self.assertIsNone(result.failure)
        self.assertIsNotNone(result.assessment_result)
        self.assertIs(
            result.assessment_result.evaluated_at,
            EVALUATED_AT,
        )
        self.assertTrue(
            all(
                metric.calculated_at is EVALUATED_AT
                for metric in result.assessment_result.metric_results
            )
        )
        self.assertTrue(
            all(
                finding.evaluated_at is EVALUATED_AT
                for finding in result.assessment_result.policy_findings
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "assessment_result.evaluated_at must be timezone-aware",
        ):
            replace(
                result,
                assessment_result=replace(
                    result.assessment_result,
                    evaluated_at=EVALUATED_AT.replace(tzinfo=None),
                ),
            )
        self.assertEqual(
            tuple(
                record.evidence_kind
                for record in result.assessment_result.evidence_records
            ),
            (
                EvidenceKind.REPOSITORY_ARCHIVED,
                EvidenceKind.LICENSE_STATUS,
                EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                EvidenceKind.SECURITY_POLICY_PRESENT,
            ),
        )
        self.assertEqual(len(result.assessment_result.metric_results), 4)
        self.assertEqual(len(result.assessment_result.policy_findings), 4)
        self.assertEqual(transport.call_count, 5)
        clock.assert_called_once_with()
        self.assertEqual(
            _row_counts(self.database_path),
            {
                "assessment_requests": 1,
                "collection_attempts": 4,
                "github_source_snapshots": 5,
                "evidence_records": 4,
                "github_source_observations": 2,
            },
        )

    def test_unavailable_evidence_continues_to_not_evaluable_finding(self):
        result, transport, clock = self._execute(
            _successful_responses(latest_empty=True)
        )

        self.assertIs(result.status, AssessmentExecutionStatus.COMPLETE)
        latest_evidence = result.assessment_result.evidence_records[2]
        self.assertIs(
            latest_evidence.collection_outcome,
            EvidenceOutcome.UNAVAILABLE,
        )
        latest_metric = next(
            item
            for item in result.assessment_result.metric_results
            if item.metric_name == "days_since_latest_commit"
        )
        latest_finding = next(
            item
            for item in result.assessment_result.policy_findings
            if item.requirement_id == "commit_recency"
        )
        self.assertIs(latest_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertIs(latest_finding.outcome, PolicyOutcome.NOT_EVALUABLE)
        self.assertEqual(transport.call_count, 5)
        clock.assert_called_once_with()

    def test_invalid_request_returns_without_database_or_network_activity(self):
        invalid_input = _execution_input(
            _request(submitted_repository_locator="http://github.com/a/b")
        )
        result, transport, clock = self._execute([], invalid_input)

        self.assertIs(
            result.status, AssessmentExecutionStatus.INVALID_REQUEST
        )
        self.assertEqual(result.validation_result.validation_status, "invalid")
        self.assertIsNone(result.failure)
        self.assertIsNone(result.assessment_result)
        self.assertFalse(self.database_path.exists())
        transport.assert_not_called()
        clock.assert_not_called()

    def test_collection_order_ids_and_persistence_precede_next_collector(self):
        responses = _successful_responses()
        observed = []

        def transport_side_effect(source_identity):
            index = len(observed)
            if index == 0:
                self.assertTrue(self.database_path.exists())
            counts = _row_counts(self.database_path)
            observed.append(
                (
                    source_identity,
                    counts["assessment_requests"],
                    counts["collection_attempts"],
                    counts["evidence_records"],
                )
            )
            return responses[index]

        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=transport_side_effect,
        ), patch.object(
            workflow,
            "_current_evaluation_time",
            return_value=EVALUATED_AT,
        ) as clock:
            execute_assessment(self.database_path, _execution_input())

        self.assertEqual(
            observed,
            [
                (REPOSITORY_ENDPOINT, 1, 0, 0),
                (REPOSITORY_ENDPOINT, 1, 1, 1),
                (COMMITS_ENDPOINT, 1, 2, 2),
                (REPOSITORY_ENDPOINT, 1, 3, 3),
                (POLICY_ENDPOINT, 1, 3, 3),
            ],
        )
        with sqlite3.connect(self.database_path) as connection:
            attempts = connection.execute(
                "SELECT evidence_kind, collection_attempt_id, "
                "attempt_number, attempted_at "
                "FROM collection_attempts ORDER BY rowid"
            ).fetchall()
        self.assertEqual(
            tuple(row[0] for row in attempts),
            (
                "repository_archived",
                "license_status",
                "latest_commit_timestamp",
                "security_policy_present",
            ),
        )
        self.assertEqual(tuple(row[2] for row in attempts), (1, 1, 1, 1))
        self.assertEqual(
            tuple(row[3] for row in attempts),
            (ATTEMPTED_AT.isoformat(),) * 4,
        )
        clock.assert_called_once_with()
        self.assertEqual(len({row[1] for row in attempts}), 4)
        self.assertEqual(
            tuple(row[1] for row in attempts),
            (
                "collection-attempt-"
                "5d3c565791e974bed289288c7ac3570232cb253c15402bcd513ed59d4a7f65f0",
                "collection-attempt-"
                "53466cb8c21adcbf4331a95c7ded970b282504b9a2566f26a2eec2b3656ae7b1",
                "collection-attempt-"
                "2dc824a85af1c3a8bc0a297337a1fb00e21405cf94d5e359447963b082e70dad",
                "collection-attempt-"
                "7ab0f6ef4a4470d590d4b0d2976c850ffe325b2a7b7d32beab6355e1c4052add",
            ),
        )

    def test_midsequence_failure_is_durable_and_stops_later_work(self):
        for status, expected_outcome in (
            (503, GitHubCollectionOutcome.FAILED_RETRYABLE),
            (409, GitHubCollectionOutcome.FAILED_NONRETRYABLE),
        ):
            with self.subTest(status=status):
                database_path = Path(self.temporary_directory.name) / (
                    "failure-{}.sqlite3".format(status)
                )
                responses = [
                    _archived_response(),
                    _license_response(),
                    (status, None, ()),
                ]
                with patch(
                    "engineering_due_diligence.github."
                    "_get_public_github_repository",
                    side_effect=responses,
                ) as transport, patch.object(
                    workflow,
                    "evaluate_persisted_assessment",
                    side_effect=AssertionError("evaluation must not run"),
                ) as evaluator, patch.object(
                    workflow,
                    "_current_evaluation_time",
                    side_effect=AssertionError("clock must not run"),
                ) as clock:
                    result = execute_assessment(
                        database_path, _execution_input()
                    )

                self.assertIs(
                    result.status,
                    AssessmentExecutionStatus.COLLECTION_FAILED,
                )
                self.assertIs(
                    result.failure.evidence_kind,
                    EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                )
                self.assertIs(result.failure.outcome, expected_outcome)
                self.assertIsNone(result.assessment_result)
                self.assertEqual(transport.call_count, 3)
                evaluator.assert_not_called()
                clock.assert_not_called()
                counts = _row_counts(database_path)
                self.assertEqual(counts["collection_attempts"], 3)
                self.assertEqual(counts["evidence_records"], 2)
                with sqlite3.connect(database_path) as connection:
                    last_attempt = connection.execute(
                        "SELECT evidence_kind, outcome, error_category "
                        "FROM collection_attempts ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                self.assertEqual(last_attempt[0], "latest_commit_timestamp")
                self.assertEqual(last_attempt[1], expected_outcome.value)
                self.assertIsNotNone(last_attempt[2])

    def test_persistence_and_programmer_errors_are_not_reclassified(self):
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=AssertionError("collection must not start"),
        ) as transport, patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=AssertionError("clock must not run"),
        ) as persistence_clock:
            with self.assertRaises(SQLitePersistenceError) as raised:
                execute_assessment(":memory:", _execution_input())
        self.assertEqual(raised.exception.category, "invalid_database_path")
        transport.assert_not_called()
        persistence_clock.assert_not_called()

        programmer_error = RuntimeError("programmer failure")
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=programmer_error,
        ), patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=AssertionError("clock must not run"),
        ) as programmer_clock:
            with self.assertRaises(RuntimeError) as programmer_raised:
                execute_assessment(
                    Path(self.temporary_directory.name) / "programmer.sqlite3",
                    _execution_input(),
                )
        self.assertIs(programmer_raised.exception, programmer_error)
        programmer_clock.assert_not_called()

    def test_commit_after_collection_start_before_evaluation_succeeds(self):
        commit_timestamp = datetime(
            2026, 8, 9, 17, 0, tzinfo=timezone.utc
        )
        self.assertGreater(commit_timestamp, ATTEMPTED_AT)
        self.assertLess(commit_timestamp, EVALUATED_AT)

        result, _, clock = self._execute(
            _successful_responses(
                latest_committer_date=commit_timestamp.isoformat()
            )
        )

        self.assertIs(result.status, AssessmentExecutionStatus.COMPLETE)
        latest = result.assessment_result.evidence_records[2]
        self.assertEqual(latest.value, commit_timestamp)
        self.assertIs(result.assessment_result.evaluated_at, EVALUATED_AT)
        clock.assert_called_once_with()

    def test_invalid_evaluation_clock_values_fail_closed(self):
        real_evaluator = evaluate_persisted_assessment
        for label, clock_value, message in (
            (
                "naive",
                EVALUATED_AT.replace(tzinfo=None),
                "evaluated_at must be timezone-aware",
            ),
            (
                "before evidence",
                ATTEMPTED_AT - timedelta(seconds=1),
                "attempted_at is after calculated_at",
            ),
        ):
            with self.subTest(label=label):
                database_path = Path(self.temporary_directory.name) / (
                    "invalid-clock-{}.sqlite3".format(
                        label.replace(" ", "-")
                    )
                )
                with patch(
                    "engineering_due_diligence.github."
                    "_get_public_github_repository",
                    side_effect=_successful_responses(),
                ), patch.object(
                    workflow,
                    "_current_evaluation_time",
                    return_value=clock_value,
                ) as clock, patch.object(
                    workflow,
                    "evaluate_persisted_assessment",
                    wraps=real_evaluator,
                ) as evaluator:
                    with self.assertRaisesRegex(ValueError, message):
                        execute_assessment(
                            database_path, _execution_input()
                        )

                clock.assert_called_once_with()
                if label == "naive":
                    evaluator.assert_not_called()
                else:
                    evaluator.assert_called_once_with(
                        database_path, ASSESSMENT_ID, clock_value
                    )
                self.assertEqual(
                    _row_counts(database_path)["evidence_records"], 4
                )

    def test_later_transient_reevaluation_does_not_mutate_durable_evidence(self):
        later_evaluated_at = EVALUATED_AT + timedelta(days=2)
        responses = _successful_responses()
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=responses + responses,
        ), patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=(EVALUATED_AT, later_evaluated_at),
        ) as clock:
            first = execute_assessment(
                self.database_path, _execution_input()
            )
            before = _database_dump(self.database_path)
            second = execute_assessment(
                self.database_path, _execution_input()
            )
            after = _database_dump(self.database_path)

        self.assertEqual(
            first.assessment_result.evidence_records,
            second.assessment_result.evidence_records,
        )
        self.assertIs(first.assessment_result.evaluated_at, EVALUATED_AT)
        self.assertIs(
            second.assessment_result.evaluated_at, later_evaluated_at
        )
        self.assertNotEqual(
            first.assessment_result.metric_results,
            second.assessment_result.metric_results,
        )
        self.assertNotEqual(
            first.assessment_result.policy_findings,
            second.assessment_result.policy_findings,
        )
        self.assertEqual(before, after)
        self.assertEqual(clock.call_count, 2)

    def test_changed_collection_timestamp_conflicts_before_evaluation(self):
        self._execute(_successful_responses())
        before = _database_dump(self.database_path)
        changed_input = replace(
            _execution_input(),
            collection_attempted_at=ATTEMPTED_AT + timedelta(seconds=1),
        )

        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=_successful_responses(),
        ) as transport, patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=AssertionError("clock must not run"),
        ) as clock:
            with self.assertRaises(SQLitePersistenceError) as raised:
                execute_assessment(self.database_path, changed_input)

        self.assertEqual(raised.exception.category, "conflicting_replay")
        transport.assert_called_once_with(REPOSITORY_ENDPOINT)
        clock.assert_not_called()
        self.assertEqual(_database_dump(self.database_path), before)

    def test_exact_replay_is_idempotent(self):
        execution_input = _execution_input()
        responses = _successful_responses()
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=responses + responses,
        ) as transport, patch.object(
            workflow,
            "_current_evaluation_time",
            return_value=EVALUATED_AT,
        ) as clock:
            first = execute_assessment(
                self.database_path, execution_input
            )
            before = _database_dump(self.database_path)
            second = execute_assessment(
                self.database_path, execution_input
            )
            after = _database_dump(self.database_path)

        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(transport.call_count, 10)
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(_row_counts(self.database_path)["evidence_records"], 4)

    def test_changed_remote_evidence_conflicts_without_mutation_or_evaluation(self):
        self._execute(_successful_responses())
        before = _database_dump(self.database_path)

        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            return_value=_archived_response(archived=True),
        ) as transport, patch.object(
            workflow,
            "evaluate_persisted_assessment",
            side_effect=AssertionError("evaluation must not run"),
        ) as evaluator, patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=AssertionError("clock must not run"),
        ) as clock:
            with self.assertRaises(SQLitePersistenceError) as raised:
                execute_assessment(
                    self.database_path, _execution_input()
                )

        self.assertEqual(raised.exception.category, "conflicting_replay")
        transport.assert_called_once_with(REPOSITORY_ENDPOINT)
        evaluator.assert_not_called()
        clock.assert_not_called()
        self.assertEqual(_database_dump(self.database_path), before)

    def test_evaluation_runs_once_only_after_four_authoritative_records(self):
        real_evaluator = evaluate_persisted_assessment

        def current_evaluation_time():
            self.assertEqual(
                _row_counts(self.database_path),
                {
                    "assessment_requests": 1,
                    "collection_attempts": 4,
                    "github_source_snapshots": 5,
                    "evidence_records": 4,
                    "github_source_observations": 2,
                },
            )
            return EVALUATED_AT

        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=_successful_responses(),
        ), patch.object(
            workflow,
            "evaluate_persisted_assessment",
            wraps=real_evaluator,
        ) as evaluator, patch.object(
            workflow,
            "_current_evaluation_time",
            side_effect=current_evaluation_time,
        ) as clock:
            result = execute_assessment(
                self.database_path, _execution_input()
            )

        evaluator.assert_called_once_with(
            self.database_path, ASSESSMENT_ID, EVALUATED_AT
        )
        clock.assert_called_once_with()
        self.assertIs(result.status, AssessmentExecutionStatus.COMPLETE)
        self.assertEqual(_row_counts(self.database_path)["evidence_records"], 4)

    def test_schema_remains_v4_and_derived_results_remain_transient(self):
        self._execute(_successful_responses())
        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        self.assertEqual(version, 4)
        self.assertEqual(
            tables,
            {
                "assessment_requests",
                "collection_attempts",
                "github_source_snapshots",
                "evidence_records",
                "github_source_observations",
            },
        )


if __name__ == "__main__":
    unittest.main()
