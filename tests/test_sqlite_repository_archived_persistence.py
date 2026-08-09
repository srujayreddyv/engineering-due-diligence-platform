"""Focused tests for concrete SQLite repository-archived persistence."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engineering_due_diligence.persistence as persistence
from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
)
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    FreshnessStatus,
    RiskTolerance,
)
from engineering_due_diligence.persistence import (
    SQLitePersistenceError,
    persist_github_repository_metadata_collection,
    persist_valid_assessment_request,
)
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
    AssessmentRequestValidationResult,
    validate_assessment_request,
)


SUBMITTED_AT = datetime(2026, 8, 4, 9, 30, tzinfo=timezone.utc)
ATTEMPTED_AT = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
COLLECTOR_VERSION = "public-github-repository-metadata.v1"
SOURCE_IDENTITY = (
    "https://api.github.com/repos/example/reliable-library"
)


def _valid_request(
    **changes: object,
) -> AssessmentRequestValidationResult:
    values = {
        "assessment_id": "assessment-day-8",
        "submitted_repository_locator": (
            "https://github.com/example/reliable-library"
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
    return validate_assessment_request(AssessmentRequestInput(**values))


def _collection_input(
    **changes: object,
) -> GitHubRepositoryMetadataCollectionInput:
    values = {
        "assessment_id": "assessment-day-8",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-8-1",
        "attempt_number": 1,
        "attempted_at": ATTEMPTED_AT,
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _available(
    *,
    archived: bool = False,
    raw_text: str | None = None,
    response_etag: str | None = '"etag-day-8"',
    **input_changes: object,
) -> GitHubRepositoryMetadataCollectionResult:
    request = _collection_input(**input_changes)
    if raw_text is None:
        raw_text = (
            '{{"id":8123,"full_name":"example/reliable-library",'
            '"archived":{}}}'.format(str(archived).lower())
        )
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=COLLECTOR_VERSION,
        source_identity=(
            "https://api.github.com/repos/{}".format(
                request.repository_identity.removeprefix("github.com/")
            )
        ),
        repository_source_id="8123",
        archived=archived,
        raw_snapshot=raw_text,
        integrity_digest=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _collection_error(
    category: str,
    retryability: str,
    message: str,
    retry_after: str | None = None,
) -> GitHubRepositoryMetadataCollectionError:
    return GitHubRepositoryMetadataCollectionError(
        category=category,
        retryability=retryability,
        message=message,
        retry_after=retry_after,
    )


def _unavailable(
    **input_changes: object,
) -> GitHubRepositoryMetadataCollectionResult:
    request = _collection_input(**input_changes)
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=COLLECTOR_VERSION,
        source_identity=SOURCE_IDENTITY,
        repository_source_id=None,
        archived=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=404,
        response_etag=None,
        error=_collection_error(
            "repository_not_publicly_available",
            "conditionally_retryable",
            "The repository is not available through the public GitHub endpoint.",
        ),
    )


def _failure(
    *,
    category: str,
    retryability: str,
    message: str,
    status: int,
    retry_after: str | None = None,
    **input_changes: object,
) -> GitHubRepositoryMetadataCollectionResult:
    request = _collection_input(**input_changes)
    outcome = (
        GitHubCollectionOutcome.FAILED_RETRYABLE
        if retryability == "retryable"
        else GitHubCollectionOutcome.FAILED_NONRETRYABLE
    )
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=COLLECTOR_VERSION,
        source_identity=SOURCE_IDENTITY,
        repository_source_id=None,
        archived=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=status,
        response_etag=None,
        error=_collection_error(
            category,
            retryability,
            message,
            retry_after,
        ),
    )


def _row_counts(database_path: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database_path) as connection:
        return tuple(
            connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0]
            for table in (
                "assessment_requests",
                "collection_attempts",
                "github_source_snapshots",
                "evidence_records",
            )
        )


class SQLiteRepositoryArchivedPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "day-8.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _persist_request(
        self,
        result: AssessmentRequestValidationResult | None = None,
    ) -> AssessmentRequestValidationResult:
        supplied = result if result is not None else _valid_request()
        persist_valid_assessment_request(self.database_path, supplied)
        return supplied

    def test_request_is_durable_after_close_and_reopen_with_schema_and_foreign_keys(
        self,
    ) -> None:
        submitted_at = SUBMITTED_AT.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        request_result = _valid_request(submitted_at=submitted_at)

        returned = persist_valid_assessment_request(
            self.database_path, request_result
        )

        self.assertIs(returned, request_result)
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 4
            )
            row = connection.execute(
                "SELECT * FROM assessment_requests"
            ).fetchone()
        self.assertEqual(row["assessment_id"], "assessment-day-8")
        self.assertEqual(
            row["submitted_repository_locator"],
            "https://github.com/example/reliable-library",
        )
        self.assertEqual(row["intended_use"], request_result.request.intended_use)
        self.assertEqual(row["environment"], "production")
        self.assertEqual(row["criticality"], "critical")
        self.assertEqual(row["expected_lifetime_days"], 1_825)
        self.assertEqual(row["risk_tolerance"], "low")
        self.assertEqual(row["submitted_by_actor_id"], "actor-submitter")
        self.assertEqual(
            row["responsible_reviewer_actor_id"], "actor-reviewer"
        )
        self.assertEqual(row["submitted_at"], submitted_at.isoformat())
        self.assertTrue(row["submitted_at"].endswith("+05:30"))
        self.assertEqual(
            row["request_definition_version"], REQUEST_DEFINITION_VERSION
        )
        self.assertEqual(
            row["normalized_repository_identity"],
            "github.com/example/reliable-library",
        )
        private_connection = persistence._connect(str(self.database_path))
        try:
            self.assertEqual(
                private_connection.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                private_connection.execute(
                    "PRAGMA synchronous"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                private_connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0],
                4,
            )
        finally:
            private_connection.close()

    def test_invalid_request_and_memory_database_paths_are_safely_rejected(
        self,
    ) -> None:
        invalid_result = _valid_request(intended_use="")
        self.assertEqual(invalid_result.validation_status, "invalid")

        with self.assertRaises(SQLitePersistenceError) as invalid_context:
            persist_valid_assessment_request(
                self.database_path, invalid_result
            )
        self.assertEqual(invalid_context.exception.category, "invalid_input")
        self.assertEqual(str(invalid_context.exception), "The persistence input is invalid.")
        self.assertFalse(self.database_path.exists())

        valid_result = _valid_request()
        for memory_path in (":memory:", "file::memory:?cache=shared"):
            with self.subTest(memory_path=memory_path):
                with self.assertRaises(SQLitePersistenceError) as context:
                    persist_valid_assessment_request(memory_path, valid_result)
                self.assertEqual(
                    context.exception.category, "invalid_database_path"
                )
                self.assertNotIn(memory_path, str(context.exception))

        unavailable_path = (
            Path(self.temporary_directory.name) / "missing" / "database.sqlite3"
        )
        with self.assertRaises(SQLitePersistenceError) as context:
            persist_valid_assessment_request(unavailable_path, valid_result)
        self.assertEqual(context.exception.category, "database_unavailable")
        self.assertEqual(
            str(context.exception), "The SQLite database is unavailable."
        )
        self.assertNotIn(str(unavailable_path), str(context.exception))
        self.assertNotIn("unable to open", str(context.exception).casefold())

        unsupported_schema_path = (
            Path(self.temporary_directory.name) / "unsupported-schema.sqlite3"
        )
        with sqlite3.connect(unsupported_schema_path) as connection:
            connection.execute("PRAGMA user_version = 2")
        with self.assertRaises(SQLitePersistenceError) as context:
            persist_valid_assessment_request(
                unsupported_schema_path, valid_result
            )
        self.assertEqual(context.exception.category, "schema_incompatible")
        self.assertEqual(
            str(context.exception),
            "The SQLite persistence schema is incompatible.",
        )
        self.assertNotIn(
            str(unsupported_schema_path), str(context.exception)
        )

        tampered_collection = _available()
        object.__setattr__(tampered_collection.request, "attempt_number", 0)
        with self.assertRaises(SQLitePersistenceError) as context:
            persist_github_repository_metadata_collection(
                self.database_path, tampered_collection
            )
        self.assertEqual(context.exception.category, "invalid_input")

    def test_collection_requires_matching_persisted_request(self) -> None:
        result = _available()
        with self.assertRaises(SQLitePersistenceError) as missing_context:
            persist_github_repository_metadata_collection(
                self.database_path, result
            )
        self.assertEqual(
            missing_context.exception.category, "request_not_found"
        )

        self._persist_request()
        mismatched = _available(
            raw_text=(
                '{"id":8123,"full_name":"example/other-library",'
                '"archived":false}'
            ),
            repository_identity="github.com/example/other-library",
        )
        with self.assertRaises(SQLitePersistenceError) as mismatch_context:
            persist_github_repository_metadata_collection(
                self.database_path, mismatched
            )
        self.assertEqual(mismatch_context.exception.category, "invalid_input")
        self.assertEqual(_row_counts(self.database_path), (1, 0, 0, 0))

        original = _available()
        persist_github_repository_metadata_collection(
            self.database_path, original
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE collection_attempts
                SET repository_identity = 'github.com/example/other-library'
                """
            )
        evidence = None
        with self.assertRaises(SQLitePersistenceError) as context:
            evidence = persist_github_repository_metadata_collection(
                self.database_path, original
            )
        self.assertIsNone(evidence)
        self.assertEqual(context.exception.category, "verification_failed")

    def test_available_archived_result_returns_verified_evidence(self) -> None:
        self._persist_request()
        result = _available(archived=True)

        evidence = persist_github_repository_metadata_collection(
            self.database_path, result
        )

        self.assertIsNotNone(evidence)
        self.assertIs(evidence.collection_outcome, EvidenceOutcome.AVAILABLE)
        self.assertIs(evidence.evidence_kind, EvidenceKind.REPOSITORY_ARCHIVED)
        self.assertIs(evidence.value, True)
        self.assertEqual(evidence.assessment_id, "assessment-day-8")
        self.assertEqual(
            evidence.collection_attempt_id, "collection-attempt-day-8-1"
        )
        self.assertEqual(evidence.attempt_number, 1)
        self.assertEqual(evidence.attempted_at, ATTEMPTED_AT)
        self.assertEqual(evidence.source_identity, SOURCE_IDENTITY)
        self.assertEqual(
            evidence.collector_name, "public-github-repository-metadata"
        )
        self.assertEqual(evidence.collector_version, COLLECTOR_VERSION)
        self.assertEqual(evidence.evidence_schema_version, "evidence-record.v1")
        self.assertEqual(evidence.freshness_basis, "collection_time")
        self.assertIs(
            evidence.freshness_status_at_collection, FreshnessStatus.CURRENT
        )
        self.assertTrue(
            evidence.evidence_id.startswith("repository-archived-evidence-")
        )
        self.assertEqual(_row_counts(self.database_path), (1, 1, 1, 1))

    def test_available_unarchived_result_returns_strict_false(self) -> None:
        self._persist_request()

        evidence = persist_github_repository_metadata_collection(
            self.database_path, _available(archived=False)
        )

        self.assertIs(evidence.value, False)
        self.assertEqual(evidence.raw_snapshot, '{"value":false}')
        with sqlite3.connect(self.database_path) as connection:
            stored_value, stored_type = connection.execute(
                "SELECT archived_value, typeof(archived_value) FROM evidence_records"
            ).fetchone()
        self.assertEqual(stored_value, 0)
        self.assertEqual(stored_type, "integer")

    def test_available_result_preserves_exact_full_response_separately(
        self,
    ) -> None:
        self._persist_request()
        raw_text = (
            '{\n  "id": 8123, "full_name": "example/reliable-library",\n'
            '  "archived": false, "name": "reliable-library"\n}'
        )
        result = _available(raw_text=raw_text, response_etag='"source-etag"')

        evidence = persist_github_repository_metadata_collection(
            self.database_path, result
        )

        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            source = connection.execute(
                "SELECT * FROM github_source_snapshots"
            ).fetchone()
        self.assertEqual(source["response_bytes"], raw_text.encode("utf-8"))
        self.assertEqual(source["encoding"], "utf-8")
        self.assertEqual(source["media_type"], "application/json")
        self.assertEqual(source["integrity_digest"], result.integrity_digest)
        self.assertEqual(source["repository_source_id"], "8123")
        self.assertEqual(source["response_etag"], '"source-etag"')
        self.assertNotEqual(source["response_bytes"].decode("utf-8"), evidence.raw_snapshot)

    def test_available_result_preserves_compact_snapshot_integrity(self) -> None:
        self._persist_request()
        result = _available(archived=True)

        evidence = persist_github_repository_metadata_collection(
            self.database_path, result
        )

        expected_compact = '{"value":true}'
        expected_digest = hashlib.sha256(
            expected_compact.encode("utf-8")
        ).hexdigest()
        self.assertEqual(evidence.raw_snapshot, expected_compact)
        self.assertEqual(evidence.integrity_digest, expected_digest)
        self.assertEqual(
            evidence.provenance,
            (
                ("source_snapshot_id", evidence.provenance[0][1]),
                ("source_snapshot_integrity_digest", result.integrity_digest),
                ("repository_source_id", "8123"),
            ),
        )
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT compact_snapshot, integrity_digest,
                       normalization_version, source_snapshot_id
                FROM evidence_records
                """
            ).fetchone()
            source_id = connection.execute(
                "SELECT source_snapshot_id FROM github_source_snapshots"
            ).fetchone()[0]
        self.assertEqual(row[0], expected_compact)
        self.assertEqual(row[1], expected_digest)
        self.assertEqual(row[2], "repository-archived-normalization.v1")
        self.assertEqual(row[3], source_id)
        self.assertEqual(evidence.provenance[0][1], source_id)

    def test_unrelated_github_fields_survive_full_snapshot_round_trip(self) -> None:
        self._persist_request()
        raw_text = (
            '{"topics":["security","python"],"id":8123,'
            '"owner":{"login":"example","site_admin":false},'
            '"full_name":"example/reliable-library",'
            '"archived":false,"open_issues_count":7}'
        )

        persist_github_repository_metadata_collection(
            self.database_path, _available(raw_text=raw_text)
        )

        with sqlite3.connect(self.database_path) as connection:
            stored = connection.execute(
                "SELECT response_bytes FROM github_source_snapshots"
            ).fetchone()[0]
        self.assertEqual(stored, raw_text.encode("utf-8"))
        self.assertIn(b'"topics":["security","python"]', stored)
        self.assertIn(b'"owner":{"login":"example"', stored)

    def test_404_persists_unavailable_evidence_without_source_snapshot(
        self,
    ) -> None:
        self._persist_request()

        evidence = persist_github_repository_metadata_collection(
            self.database_path, _unavailable()
        )

        self.assertIsNotNone(evidence)
        self.assertIs(
            evidence.collection_outcome, EvidenceOutcome.UNAVAILABLE
        )
        self.assertIsNone(evidence.value)
        self.assertIsNone(evidence.raw_snapshot)
        self.assertIsNone(evidence.integrity_digest)
        self.assertEqual(
            evidence.unavailability_reason,
            "repository_not_publicly_available",
        )
        self.assertEqual(
            evidence.error_category, "repository_not_publicly_available"
        )
        self.assertEqual(
            evidence.provenance,
            (("collection_error_category", "repository_not_publicly_available"),),
        )
        self.assertEqual(_row_counts(self.database_path), (1, 1, 0, 1))

    def test_retryable_and_nonretryable_failures_persist_attempt_only(
        self,
    ) -> None:
        self._persist_request()
        retryable = _failure(
            category="github_server_error",
            retryability="retryable",
            message="GitHub could not complete the repository metadata request.",
            status=503,
            retry_after="30",
        )
        nonretryable = _failure(
            category="github_request_rejected",
            retryability="nonretryable",
            message="GitHub rejected the repository metadata request.",
            status=422,
            collection_attempt_id="collection-attempt-day-8-2",
            attempt_number=2,
        )

        self.assertIsNone(
            persist_github_repository_metadata_collection(
                self.database_path, retryable
            )
        )
        self.assertIsNone(
            persist_github_repository_metadata_collection(
                self.database_path, nonretryable
            )
        )
        self.assertIsNone(
            persist_github_repository_metadata_collection(
                self.database_path, retryable
            )
        )
        self.assertIsNone(
            persist_github_repository_metadata_collection(
                self.database_path, nonretryable
            )
        )

        changed_retry_guidance = _failure(
            category="github_server_error",
            retryability="retryable",
            message="GitHub could not complete the repository metadata request.",
            status=503,
            retry_after="60",
        )
        with self.assertRaises(SQLitePersistenceError) as context:
            persist_github_repository_metadata_collection(
                self.database_path, changed_retry_guidance
            )
        self.assertEqual(context.exception.category, "conflicting_replay")

        self.assertEqual(_row_counts(self.database_path), (1, 2, 0, 0))
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT outcome, response_status, error_category,
                       error_retryability, error_message, retry_after
                FROM collection_attempts
                ORDER BY attempt_number
                """
            ).fetchall()
        self.assertEqual(
            rows,
            [
                (
                    "failed_retryable",
                    503,
                    "github_server_error",
                    "retryable",
                    "GitHub could not complete the repository metadata request.",
                    "30",
                ),
                (
                    "failed_nonretryable",
                    422,
                    "github_request_rejected",
                    "nonretryable",
                    "GitHub rejected the repository metadata request.",
                    None,
                ),
            ],
        )

    def test_linked_write_failure_rolls_back_complete_collection_transaction(
        self,
    ) -> None:
        self._persist_request()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_evidence_insert
                BEFORE INSERT ON evidence_records
                BEGIN
                    SELECT RAISE(ABORT, 'secret sqlite trigger detail');
                END
                """
            )

        with self.assertRaises(SQLitePersistenceError) as context:
            persist_github_repository_metadata_collection(
                self.database_path, _available()
            )

        self.assertEqual(context.exception.category, "write_failed")
        self.assertEqual(
            str(context.exception),
            "The SQLite persistence transaction failed.",
        )
        self.assertNotIn("secret", str(context.exception).casefold())
        self.assertNotIn("trigger", str(context.exception).casefold())
        self.assertEqual(_row_counts(self.database_path), (1, 0, 0, 0))

    def test_exact_request_and_collection_replay_adds_no_rows(self) -> None:
        request_result = _valid_request()
        first_request = persist_valid_assessment_request(
            self.database_path, request_result
        )
        second_request = persist_valid_assessment_request(
            self.database_path, request_result
        )
        collection_result = _available(archived=False)
        first_evidence = persist_github_repository_metadata_collection(
            self.database_path, collection_result
        )
        second_evidence = persist_github_repository_metadata_collection(
            self.database_path, collection_result
        )

        self.assertIs(first_request, request_result)
        self.assertIs(second_request, request_result)
        self.assertEqual(first_evidence, second_evidence)
        self.assertEqual(_row_counts(self.database_path), (1, 1, 1, 1))

    def test_conflicting_request_attempt_and_collection_replays_are_rejected(
        self,
    ) -> None:
        self._persist_request()
        original = _available(archived=False)
        persist_github_repository_metadata_collection(
            self.database_path, original
        )

        conflicting_request = _valid_request(intended_use="Different use")
        with self.assertRaises(SQLitePersistenceError) as request_context:
            persist_valid_assessment_request(
                self.database_path, conflicting_request
            )
        self.assertEqual(
            request_context.exception.category, "conflicting_replay"
        )

        equivalent_submitted_at = SUBMITTED_AT.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        timestamp_request = _valid_request(
            submitted_at=equivalent_submitted_at
        )
        with self.assertRaises(SQLitePersistenceError) as timestamp_context:
            persist_valid_assessment_request(
                self.database_path, timestamp_request
            )
        self.assertEqual(
            timestamp_context.exception.category, "conflicting_replay"
        )

        reused_number = _available(
            collection_attempt_id="collection-attempt-day-8-other",
            attempt_number=1,
        )
        with self.assertRaises(SQLitePersistenceError) as number_context:
            persist_github_repository_metadata_collection(
                self.database_path, reused_number
            )
        self.assertEqual(
            number_context.exception.category, "conflicting_replay"
        )

        conflicting_collection = _available(archived=True)
        with self.assertRaises(SQLitePersistenceError) as collection_context:
            persist_github_repository_metadata_collection(
                self.database_path, conflicting_collection
            )
        self.assertEqual(
            collection_context.exception.category, "conflicting_replay"
        )

        equivalent_attempted_at = ATTEMPTED_AT.astimezone(
            timezone(timedelta(hours=-7))
        )
        timestamp_collection = _available(
            attempted_at=equivalent_attempted_at
        )
        with self.assertRaises(SQLitePersistenceError) as timestamp_context:
            persist_github_repository_metadata_collection(
                self.database_path, timestamp_collection
            )
        self.assertEqual(
            timestamp_context.exception.category, "conflicting_replay"
        )
        self.assertEqual(_row_counts(self.database_path), (1, 1, 1, 1))

        with sqlite3.connect(self.database_path) as connection:
            intended_use = connection.execute(
                "SELECT intended_use FROM assessment_requests"
            ).fetchone()[0]
            archived_value = connection.execute(
                "SELECT archived_value FROM evidence_records"
            ).fetchone()[0]
        self.assertEqual(
            intended_use,
            "Critical production authentication dependency",
        )
        self.assertEqual(archived_value, 0)

    def test_full_source_digest_corruption_fails_closed(self) -> None:
        self._persist_request()
        result = _available()
        persist_github_repository_metadata_collection(
            self.database_path, result
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE github_source_snapshots SET integrity_digest = ?",
                ("0" * 64,),
            )

        evidence = None
        with self.assertRaises(SQLitePersistenceError) as context:
            evidence = persist_github_repository_metadata_collection(
                self.database_path, result
            )

        self.assertIsNone(evidence)
        self.assertEqual(context.exception.category, "verification_failed")
        self.assertEqual(
            str(context.exception),
            "The persisted content could not be verified.",
        )

    def test_normalized_value_corruption_fails_closed(self) -> None:
        self._persist_request()
        result = _available(archived=False)
        persist_github_repository_metadata_collection(
            self.database_path, result
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE evidence_records SET archived_value = 1"
            )

        evidence = None
        with self.assertRaises(SQLitePersistenceError) as context:
            evidence = persist_github_repository_metadata_collection(
                self.database_path, result
            )

        self.assertIsNone(evidence)
        self.assertEqual(context.exception.category, "verification_failed")
        with sqlite3.connect(self.database_path) as connection:
            compact_snapshot = connection.execute(
                "SELECT compact_snapshot FROM evidence_records"
            ).fetchone()[0]
        self.assertEqual(compact_snapshot, '{"value":false}')


if __name__ == "__main__":
    unittest.main()
