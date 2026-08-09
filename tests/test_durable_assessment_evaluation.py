"""Focused tests for read-only durable evidence evaluation integration."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.assessment as assessment
from engineering_due_diligence.assessment import (
    evaluate_assessment,
    evaluate_persisted_assessment,
)
from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
    collect_public_github_security_policy_presence,
)
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    MetricStatus,
    PolicyOutcome,
    RiskTolerance,
)
from engineering_due_diligence.persistence import (
    SQLitePersistenceError,
    load_verified_assessment_evidence,
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_github_security_policy_presence_collection,
    persist_valid_assessment_request,
)
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
    validate_assessment_request,
)
from tests.test_github_security_policy_collection import (
    _policy_response,
    _repository_response,
)
from tests.test_sqlite_latest_commit_persistence import (
    LATEST_AT,
    SHA,
    SOURCE_TIMESTAMP,
    _available as _latest_available,
)
from tests.test_sqlite_license_status_persistence import (
    _available_license,
)
from tests.test_sqlite_repository_archived_persistence import (
    _available as _archived_available,
)


ASSESSMENT_ID = "assessment-day-12"
REPOSITORY_IDENTITY = "github.com/Owner/Repository"
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


def _valid_request():
    return validate_assessment_request(
        AssessmentRequestInput(
            assessment_id=ASSESSMENT_ID,
            submitted_repository_locator=(
                "https://github.com/Owner/Repository"
            ),
            intended_use="Critical production authentication dependency",
            environment=Environment.PRODUCTION,
            criticality=Criticality.CRITICAL,
            expected_lifetime_days=1_825,
            risk_tolerance=RiskTolerance.LOW,
            submitted_by_actor_id="actor-submitter",
            responsible_reviewer_actor_id="actor-reviewer",
            submitted_at=SUBMITTED_AT,
            request_definition_version=REQUEST_DEFINITION_VERSION,
        )
    )


def _archived_result(*, unavailable=False, attempt_number=1):
    input_changes = {
        "assessment_id": ASSESSMENT_ID,
        "repository_identity": REPOSITORY_IDENTITY,
        "collection_attempt_id": (
            "collection-attempt-day-12-archived-{}".format(attempt_number)
        ),
        "attempt_number": attempt_number,
        "attempted_at": ATTEMPTED_AT,
    }
    if unavailable:
        request = GitHubRepositoryMetadataCollectionInput(**input_changes)
        return GitHubRepositoryMetadataCollectionResult(
            request=request,
            outcome=GitHubCollectionOutcome.UNAVAILABLE,
            evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
            collector_version="public-github-repository-metadata.v1",
            source_identity=(
                "https://api.github.com/repos/Owner/Repository"
            ),
            repository_source_id=None,
            archived=None,
            raw_snapshot=None,
            integrity_digest=None,
            response_status=404,
            response_etag=None,
            error=GitHubRepositoryMetadataCollectionError(
                category="repository_not_publicly_available",
                retryability="conditionally_retryable",
                message=(
                    "The repository is not available through the public "
                    "GitHub endpoint."
                ),
            ),
        )
    raw_text = (
        '{"id":8123,"full_name":"Owner/Repository",'
        '"archived":false,"unrelated":{"kept":true}}'
    )
    return _archived_available(raw_text=raw_text, **input_changes)


def _license_result():
    raw_text = json.dumps(
        {
            "id": 9123,
            "full_name": "Owner/Repository",
            "license": {
                "key": "mit",
                "name": "MIT License",
                "spdx_id": "MIT",
            },
            "unrelated": ["kept"],
        },
        separators=(",", ":"),
    )
    return _available_license(
        raw_text=raw_text,
        assessment_id=ASSESSMENT_ID,
        repository_identity=REPOSITORY_IDENTITY,
        collection_attempt_id="collection-attempt-day-12-license-1",
        attempt_number=1,
        attempted_at=ATTEMPTED_AT,
    )


def _latest_result():
    raw_text = json.dumps(
        [
            {
                "sha": SHA,
                "url": (
                    "https://api.github.com/repos/Owner/Repository/commits/"
                    + SHA
                ),
                "commit": {
                    "author": {"date": "1999-01-01T00:00:00Z"},
                    "committer": {"date": SOURCE_TIMESTAMP},
                },
                "unrelated": {"kept": True},
            }
        ],
        separators=(",", ":"),
    )
    return _latest_available(
        raw_text=raw_text,
        latest_commit_at=LATEST_AT,
        source_timestamp=SOURCE_TIMESTAMP,
        assessment_id=ASSESSMENT_ID,
        repository_identity=REPOSITORY_IDENTITY,
        collection_attempt_id="collection-attempt-day-12-latest-1",
        attempt_number=1,
        attempted_at=ATTEMPTED_AT,
    )


def _security_result():
    request = GitHubRepositoryMetadataCollectionInput(
        assessment_id=ASSESSMENT_ID,
        repository_identity=REPOSITORY_IDENTITY,
        collection_attempt_id="collection-attempt-day-12-security-1",
        attempt_number=1,
        attempted_at=ATTEMPTED_AT,
    )
    with patch(
        "engineering_due_diligence.github._get_public_github_repository",
        side_effect=[_repository_response(), _policy_response()],
    ):
        return collect_public_github_security_policy_presence(request)


class DurableAssessmentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-12.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _results(self, *, unavailable_archived=False):
        return {
            EvidenceKind.REPOSITORY_ARCHIVED: _archived_result(
                unavailable=unavailable_archived
            ),
            EvidenceKind.LICENSE_STATUS: _license_result(),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP: _latest_result(),
            EvidenceKind.SECURITY_POLICY_PRESENT: _security_result(),
        }

    def _persist(
        self,
        *,
        unavailable_archived=False,
        omit=None,
        order=None,
    ):
        request = _valid_request()
        persist_valid_assessment_request(self.database_path, request)
        results = self._results(
            unavailable_archived=unavailable_archived
        )
        persist_functions = {
            EvidenceKind.REPOSITORY_ARCHIVED: (
                persist_github_repository_metadata_collection
            ),
            EvidenceKind.LICENSE_STATUS: (
                persist_github_license_status_collection
            ),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP: (
                persist_github_latest_commit_collection
            ),
            EvidenceKind.SECURITY_POLICY_PRESENT: (
                persist_github_security_policy_presence_collection
            ),
        }
        selected_order = order or tuple(persist_functions)
        for kind in selected_order:
            if kind is not omit:
                persist_functions[kind](self.database_path, results[kind])
        return request, results

    def test_loads_four_available_records(self):
        request, _ = self._persist()
        loaded = load_verified_assessment_evidence(
            self.database_path, ASSESSMENT_ID
        )
        self.assertEqual(loaded.validation_result, request)
        self.assertEqual(len(loaded.evidence_records), 4)
        self.assertTrue(
            all(
                record.collection_outcome is EvidenceOutcome.AVAILABLE
                for record in loaded.evidence_records
            )
        )
        with self.assertRaises(FrozenInstanceError):
            loaded.evidence_records = ()

    def test_mixed_available_and_unavailable_records_are_complete(self):
        self._persist(unavailable_archived=True)
        loaded = load_verified_assessment_evidence(
            self.database_path, ASSESSMENT_ID
        )
        outcomes = tuple(
            record.collection_outcome for record in loaded.evidence_records
        )
        self.assertEqual(outcomes.count(EvidenceOutcome.UNAVAILABLE), 1)
        self.assertEqual(outcomes.count(EvidenceOutcome.AVAILABLE), 3)

    def test_evidence_is_returned_in_canonical_order(self):
        reversed_order = (
            EvidenceKind.SECURITY_POLICY_PRESENT,
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            EvidenceKind.LICENSE_STATUS,
            EvidenceKind.REPOSITORY_ARCHIVED,
        )
        self._persist(order=reversed_order)
        loaded = load_verified_assessment_evidence(
            self.database_path, ASSESSMENT_ID
        )
        self.assertEqual(
            tuple(record.evidence_kind for record in loaded.evidence_records),
            (
                EvidenceKind.REPOSITORY_ARCHIVED,
                EvidenceKind.LICENSE_STATUS,
                EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                EvidenceKind.SECURITY_POLICY_PRESENT,
            ),
        )

    def test_unavailable_evidence_produces_unavailable_metric_and_finding(self):
        self._persist(unavailable_archived=True)
        result = evaluate_persisted_assessment(
            self.database_path, ASSESSMENT_ID, EVALUATED_AT
        )
        archived_metric = next(
            metric
            for metric in result.metric_results
            if metric.metric_name == "repository_archived"
        )
        archived_finding = next(
            finding
            for finding in result.policy_findings
            if finding.requirement_id == "repository_not_archived"
        )
        self.assertIs(archived_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertIs(archived_finding.outcome, PolicyOutcome.NOT_EVALUABLE)

    def test_missing_kind_fails_as_incomplete(self):
        self._persist(omit=EvidenceKind.SECURITY_POLICY_PRESENT)
        with self.assertRaises(SQLitePersistenceError) as raised:
            load_verified_assessment_evidence(
                self.database_path, ASSESSMENT_ID
            )
        self.assertEqual(raised.exception.category, "evidence_set_incomplete")

    def test_duplicate_kind_fails_as_ambiguous(self):
        self._persist()
        persist_github_repository_metadata_collection(
            self.database_path,
            _archived_result(attempt_number=2),
        )
        with self.assertRaises(SQLitePersistenceError) as raised:
            load_verified_assessment_evidence(
                self.database_path, ASSESSMENT_ID
            )
        self.assertEqual(raised.exception.category, "evidence_set_ambiguous")

    def test_missing_assessment_uses_sanitized_not_found_error(self):
        self._persist()
        with self.assertRaises(SQLitePersistenceError) as raised:
            load_verified_assessment_evidence(
                self.database_path, "missing-assessment"
            )
        self.assertEqual(raised.exception.category, "request_not_found")
        self.assertNotIn(str(self.database_path), str(raised.exception))

    def test_nonexistent_database_is_not_created(self):
        missing = Path(self.temporary_directory.name) / "missing.sqlite3"
        with self.assertRaises(SQLitePersistenceError) as raised:
            load_verified_assessment_evidence(missing, ASSESSMENT_ID)
        self.assertEqual(raised.exception.category, "database_unavailable")
        self.assertFalse(missing.exists())

    def test_source_corruption_and_cross_repository_mismatch_fail_closed(self):
        for failure in ("source", "repository"):
            with self.subTest(failure=failure):
                path = Path(self.temporary_directory.name) / (
                    failure + ".sqlite3"
                )
                original = self.database_path
                self.database_path = path
                try:
                    self._persist()
                    with sqlite3.connect(path) as connection:
                        if failure == "source":
                            connection.execute(
                                "UPDATE github_source_snapshots "
                                "SET response_bytes = ? "
                                "WHERE collection_attempt_id = ?",
                                (
                                    b'[{"corrupted":true}]',
                                    "collection-attempt-day-12-latest-1",
                                ),
                            )
                        else:
                            connection.execute(
                                "UPDATE collection_attempts "
                                "SET repository_identity = ? "
                                "WHERE collection_attempt_id = ?",
                                (
                                    "github.com/Other/Repository",
                                    "collection-attempt-day-12-license-1",
                                ),
                            )
                        connection.commit()
                    with self.assertRaises(SQLitePersistenceError) as raised:
                        load_verified_assessment_evidence(path, ASSESSMENT_ID)
                    self.assertEqual(
                        raised.exception.category, "verification_failed"
                    )
                finally:
                    self.database_path = original

    def test_direct_and_persisted_evaluation_results_are_equal(self):
        self._persist()
        loaded = load_verified_assessment_evidence(
            self.database_path, ASSESSMENT_ID
        )
        direct = evaluate_assessment(
            loaded.validation_result.context,
            loaded.evidence_records,
            EVALUATED_AT,
        )
        persisted = evaluate_persisted_assessment(
            self.database_path, ASSESSMENT_ID, EVALUATED_AT
        )
        self.assertEqual(persisted, direct)

    def test_integration_loads_and_evaluates_exactly_once(self):
        self._persist()
        real_loader = assessment.load_verified_assessment_evidence
        real_evaluator = assessment.evaluate_assessment
        with patch.object(
            assessment,
            "load_verified_assessment_evidence",
            wraps=real_loader,
        ) as loader, patch.object(
            assessment,
            "evaluate_assessment",
            wraps=real_evaluator,
        ) as evaluator:
            evaluate_persisted_assessment(
                self.database_path, ASSESSMENT_ID, EVALUATED_AT
            )
        loader.assert_called_once_with(self.database_path, ASSESSMENT_ID)
        self.assertEqual(evaluator.call_count, 1)

    def test_exact_aware_evaluated_at_is_preserved(self):
        self._persist()
        evaluated_at = datetime(
            2026,
            8,
            10,
            7,
            45,
            tzinfo=timezone(timedelta(hours=-3, minutes=-30)),
        )
        result = evaluate_persisted_assessment(
            self.database_path, ASSESSMENT_ID, evaluated_at
        )
        self.assertIs(result.evaluated_at, evaluated_at)
        self.assertTrue(
            all(
                finding.evaluated_at is evaluated_at
                for finding in result.policy_findings
            )
        )

    def test_reads_leave_database_bytes_schema_and_content_unchanged(self):
        self._persist()
        before_bytes = self.database_path.read_bytes()
        with sqlite3.connect(self.database_path) as connection:
            before_version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            before_dump = tuple(connection.iterdump())
        load_verified_assessment_evidence(
            self.database_path, ASSESSMENT_ID
        )
        evaluate_persisted_assessment(
            self.database_path, ASSESSMENT_ID, EVALUATED_AT
        )
        with sqlite3.connect(self.database_path) as connection:
            after_version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            after_dump = tuple(connection.iterdump())
        self.assertEqual(self.database_path.read_bytes(), before_bytes)
        self.assertEqual((after_version, after_dump), (before_version, before_dump))

    def test_loading_and_evaluation_make_no_network_calls(self):
        self._persist()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            side_effect=AssertionError("network transport must not be called"),
        ) as transport:
            load_verified_assessment_evidence(
                self.database_path, ASSESSMENT_ID
            )
            evaluate_persisted_assessment(
                self.database_path, ASSESSMENT_ID, EVALUATED_AT
            )
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
