"""Focused tests for SQLite latest-commit persistence and schema v3."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.persistence as persistence
from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubLatestCommitCollectionResult,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
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
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_valid_assessment_request,
)
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
    validate_assessment_request,
)
from tests.test_sqlite_license_status_persistence import (
    _available_archived as _day9_available_archived,
    _available_license as _day9_available_license,
    _valid_request as _day9_valid_request,
)


SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE_TIMESTAMP = "2026-08-07T09:15:16-05:00"
LATEST_AT = datetime(2026, 8, 7, 9, 15, 16, tzinfo=timezone(timedelta(hours=-5)))
SOURCE_IDENTITY = (
    "https://api.github.com/repos/example/reliable-library/commits?per_page=1"
)
COLLECTOR_VERSION = "public-github-latest-commit.v1"


def _valid_request(**changes: object):
    values = {
        "assessment_id": "assessment-day-10",
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
        "submitted_at": datetime(
            2026, 8, 8, 8, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
        ),
        "request_definition_version": REQUEST_DEFINITION_VERSION,
    }
    values.update(changes)
    return validate_assessment_request(AssessmentRequestInput(**values))


def _input(**changes: object) -> GitHubRepositoryMetadataCollectionInput:
    values = {
        "assessment_id": "assessment-day-10",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-10-latest-1",
        "attempt_number": 1,
        "attempted_at": datetime(
            2026, 8, 8, 9, 0, tzinfo=timezone(timedelta(hours=-7))
        ),
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _raw(source_timestamp: str = SOURCE_TIMESTAMP, *, unrelated: bool = False) -> str:
    item = {
        "sha": SHA,
        "url": (
            "https://api.github.com/repos/example/reliable-library/commits/"
            + SHA
        ),
        "commit": {
            "author": {"date": "1999-01-01T00:00:00Z"},
            "committer": {"date": source_timestamp},
        },
    }
    if unrelated:
        item.update({"node_id": "node", "parents": [{"sha": "parent"}]})
        item["commit"]["message"] = "preserve whitespace exactly"
    return json.dumps([item], separators=(",", ":"))


def _source_identity(request: GitHubRepositoryMetadataCollectionInput) -> str:
    return "https://api.github.com/repos/{}/commits?per_page=1".format(
        request.repository_identity.removeprefix("github.com/")
    )


def _available(
    *,
    raw_text: str | None = None,
    latest_commit_at: datetime = LATEST_AT,
    source_timestamp: str = SOURCE_TIMESTAMP,
    response_etag: str | None = '"latest-etag"',
    **input_changes: object,
) -> GitHubLatestCommitCollectionResult:
    request = _input(**input_changes)
    raw_text = raw_text if raw_text is not None else _raw(source_timestamp)
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        commit_sha=SHA,
        latest_commit_at=latest_commit_at,
        source_timestamp=source_timestamp,
        raw_snapshot=raw_text,
        integrity_digest=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _safe_error(category: str) -> GitHubRepositoryMetadataCollectionError:
    definitions = {
        "repository_has_no_commits": (
            "conditionally_retryable",
            "GitHub returned no commits for the repository.",
        ),
        "repository_not_publicly_available": (
            "conditionally_retryable",
            "The repository is not available through the public GitHub endpoint.",
        ),
        "github_server_error": (
            "retryable",
            "GitHub could not complete the repository metadata request.",
        ),
        "github_request_rejected": (
            "nonretryable",
            "GitHub rejected the repository metadata request.",
        ),
    }
    retryability, message = definitions[category]
    return GitHubRepositoryMetadataCollectionError(
        category=category,
        retryability=retryability,
        message=message,
    )


def _unavailable(*, empty: bool, **input_changes: object):
    request = _input(**input_changes)
    category = (
        "repository_has_no_commits"
        if empty
        else "repository_not_publicly_available"
    )
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        commit_sha=None,
        latest_commit_at=None,
        source_timestamp=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=200 if empty else 404,
        response_etag=None,
        error=_safe_error(category),
    )


def _failed(*, retryable: bool, **input_changes: object):
    request = _input(**input_changes)
    category = "github_server_error" if retryable else "github_request_rejected"
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=(
            GitHubCollectionOutcome.FAILED_RETRYABLE
            if retryable
            else GitHubCollectionOutcome.FAILED_NONRETRYABLE
        ),
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        commit_sha=None,
        latest_commit_at=None,
        source_timestamp=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=503 if retryable else 409,
        response_etag=None,
        error=_safe_error(category),
    )


def _counts(path: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(path) as connection:
        return tuple(
            connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in (
                "assessment_requests",
                "collection_attempts",
                "github_source_snapshots",
                "evidence_records",
            )
        )


def _create_v2_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in persistence._SCHEMA_V2_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()


class SQLiteLatestCommitPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "day-10.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _persist_request(self):
        request = _valid_request()
        persist_valid_assessment_request(self.database_path, request)
        return request

    def _persist_available(self, **changes: object):
        self._persist_request()
        result = _available(**changes)
        return result, persist_github_latest_commit_collection(
            self.database_path, result
        )

    def test_fresh_schema_advances_to_exact_version_four(self) -> None:
        self._persist_request()
        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = tuple(
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(evidence_records)"
                ).fetchall()
            )
            attempts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='collection_attempts'"
            ).fetchone()[0]
        self.assertEqual(version, 4)
        self.assertIn("latest_commit_timestamp_value", columns)
        self.assertIn("latest_commit_timestamp", attempts_sql)

    def test_exact_v2_migration_preserves_archived_and_license_rows(self) -> None:
        source = Path(self.temporary_directory.name) / "source.sqlite3"
        request = _day9_valid_request()
        persist_valid_assessment_request(source, request)
        persist_github_repository_metadata_collection(
            source, _day9_available_archived()
        )
        persist_github_license_status_collection(
            source,
            _day9_available_license(attempt_number=2),
        )
        captured = {}
        table_columns = (
            ("assessment_requests", persistence._REQUEST_COLUMNS),
            ("collection_attempts", persistence._ATTEMPT_COLUMNS),
            ("github_source_snapshots", persistence._SOURCE_SNAPSHOT_COLUMNS),
            ("evidence_records", persistence._EVIDENCE_COLUMNS_V2),
        )
        with sqlite3.connect(source) as connection:
            for table, columns in table_columns:
                captured[table] = connection.execute(
                    "SELECT {} FROM {} ORDER BY {}".format(
                        ",".join(columns), table, columns[0]
                    )
                ).fetchall()

        _create_v2_database(self.database_path)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            for table, columns in table_columns:
                connection.executemany(
                    "INSERT INTO {} ({}) VALUES ({})".format(
                        table,
                        ",".join(columns),
                        ",".join("?" for _ in columns),
                    ),
                    captured[table],
                )
            connection.commit()

        persist_valid_assessment_request(self.database_path, request)

        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 4
            )
            for table, columns in table_columns:
                rows = connection.execute(
                    "SELECT {} FROM {} ORDER BY {}".format(
                        ",".join(columns), table, columns[0]
                    )
                ).fetchall()
                self.assertEqual(rows, captured[table])

    def test_v2_migration_failure_rolls_back_and_leaves_v2_usable(self) -> None:
        _create_v2_database(self.database_path)
        original_verify = persistence._verify_schema_definition

        def fail_v3(connection, expected_columns, expected_sql):
            if expected_columns is persistence._EXPECTED_COLUMNS_V3:
                raise SQLitePersistenceError("schema_incompatible")
            return original_verify(connection, expected_columns, expected_sql)

        with patch(
            "engineering_due_diligence.persistence._verify_schema_definition",
            side_effect=fail_v3,
        ):
            with self.assertRaises(SQLitePersistenceError):
                persist_valid_assessment_request(
                    self.database_path, _valid_request()
                )
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 2
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM assessment_requests"
                ).fetchone()[0],
                0,
            )
        persist_valid_assessment_request(self.database_path, _valid_request())

    def test_unsupported_and_altered_v2_schemas_fail_without_mutation(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA user_version = 9")
        with self.assertRaises(SQLitePersistenceError) as unsupported:
            persist_valid_assessment_request(self.database_path, _valid_request())
        self.assertEqual(unsupported.exception.category, "schema_incompatible")

        altered = Path(self.temporary_directory.name) / "altered.sqlite3"
        _create_v2_database(altered)
        with sqlite3.connect(altered) as connection:
            connection.execute("CREATE TABLE extra_owned_data (value TEXT)")
        with self.assertRaises(SQLitePersistenceError):
            persist_valid_assessment_request(altered, _valid_request())
        with sqlite3.connect(altered) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 2
            )
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='extra_owned_data'"
                ).fetchone()
            )

    def test_matching_durable_request_is_required(self) -> None:
        with self.assertRaises(SQLitePersistenceError) as missing:
            persist_github_latest_commit_collection(
                self.database_path, _available()
            )
        self.assertEqual(missing.exception.category, "request_not_found")

        self._persist_request()
        mismatched = _failed(
            retryable=False,
            repository_identity="github.com/example/other-repository"
        )
        with self.assertRaises(SQLitePersistenceError) as mismatch:
            persist_github_latest_commit_collection(
                self.database_path, mismatched
            )
        self.assertEqual(mismatch.exception.category, "invalid_input")

    def test_available_timestamp_is_durable_authoritative_and_current(self) -> None:
        result, evidence = self._persist_available()

        self.assertIsNotNone(evidence)
        self.assertIs(evidence.evidence_kind, EvidenceKind.LATEST_COMMIT_TIMESTAMP)
        self.assertIs(evidence.collection_outcome, EvidenceOutcome.AVAILABLE)
        self.assertEqual(evidence.value, LATEST_AT)
        self.assertEqual(evidence.attempted_at.isoformat(), result.request.attempted_at.isoformat())
        self.assertEqual(evidence.freshness_basis, "collection_time")
        self.assertIs(
            evidence.freshness_status_at_collection, FreshnessStatus.CURRENT
        )
        self.assertEqual(_counts(self.database_path), (1, 1, 1, 1))

    def test_old_commit_remains_current_evidence_at_collection_time(self) -> None:
        old_source = "2014-02-03T04:05:06Z"
        _, evidence = self._persist_available(
            raw_text=_raw(old_source),
            source_timestamp=old_source,
            latest_commit_at=datetime(
                2014, 2, 3, 4, 5, 6, tzinfo=timezone.utc
            ),
        )

        self.assertEqual(
            evidence.value,
            datetime(2014, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        )
        self.assertIs(
            evidence.freshness_status_at_collection, FreshnessStatus.CURRENT
        )

    def test_exact_response_compact_snapshot_sha_and_timestamp_survive(self) -> None:
        raw_text = _raw(unrelated=True)
        normalized_utc = datetime(
            2026, 8, 7, 14, 15, 16, tzinfo=timezone.utc
        )
        result, evidence = self._persist_available(
            raw_text=raw_text,
            latest_commit_at=normalized_utc,
        )

        with sqlite3.connect(self.database_path) as connection:
            source = connection.execute(
                "SELECT response_bytes, integrity_digest, repository_source_id "
                "FROM github_source_snapshots"
            ).fetchone()
            row = connection.execute(
                "SELECT compact_snapshot, integrity_digest, provenance_json, "
                "latest_commit_timestamp_value FROM evidence_records"
            ).fetchone()
        self.assertEqual(source[0], raw_text.encode("utf-8"))
        self.assertEqual(source[1], hashlib.sha256(raw_text.encode()).hexdigest())
        self.assertEqual(source[2], SHA)
        compact = json.dumps(
            {"value": normalized_utc.isoformat()},
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(row[0], compact)
        self.assertEqual(row[1], hashlib.sha256(compact.encode()).hexdigest())
        self.assertEqual(row[3], normalized_utc.isoformat())
        self.assertIn(SHA, row[2])
        self.assertIn(SOURCE_TIMESTAMP, row[2])
        self.assertEqual(result.source_timestamp, SOURCE_TIMESTAMP)
        self.assertEqual(evidence.value.isoformat(), normalized_utc.isoformat())
        self.assertEqual(evidence.raw_snapshot, compact)
        replayed = persist_github_latest_commit_collection(
            self.database_path, result
        )
        self.assertEqual(replayed.value.isoformat(), normalized_utc.isoformat())

    def test_empty_and_404_persist_unavailable_evidence_without_snapshot(self) -> None:
        self._persist_request()
        empty = _unavailable(empty=True)
        empty_evidence = persist_github_latest_commit_collection(
            self.database_path, empty
        )
        not_found = _unavailable(
            empty=False,
            collection_attempt_id="collection-attempt-day-10-latest-2",
            attempt_number=2,
        )
        missing_evidence = persist_github_latest_commit_collection(
            self.database_path, not_found
        )

        self.assertEqual(
            empty_evidence.unavailability_reason, "repository_has_no_commits"
        )
        self.assertEqual(
            missing_evidence.unavailability_reason,
            "repository_not_publicly_available",
        )
        self.assertIsNone(empty_evidence.value)
        self.assertIsNone(missing_evidence.raw_snapshot)
        self.assertEqual(_counts(self.database_path), (1, 2, 0, 2))

    def test_retryable_and_nonretryable_failures_persist_attempt_only(self) -> None:
        self._persist_request()
        self.assertIsNone(
            persist_github_latest_commit_collection(
                self.database_path, _failed(retryable=True)
            )
        )
        self.assertIsNone(
            persist_github_latest_commit_collection(
                self.database_path,
                _failed(
                    retryable=False,
                    collection_attempt_id="collection-attempt-day-10-latest-2",
                    attempt_number=2,
                ),
            )
        )
        self.assertEqual(_counts(self.database_path), (1, 2, 0, 0))

    def test_linked_write_failure_rolls_back_complete_transaction(self) -> None:
        self._persist_request()
        original_insert = persistence._insert_values

        def fail_evidence(connection, table, columns, values):
            if table == "evidence_records":
                raise sqlite3.OperationalError("private path")
            return original_insert(connection, table, columns, values)

        with patch(
            "engineering_due_diligence.persistence._insert_values",
            side_effect=fail_evidence,
        ):
            with self.assertRaises(SQLitePersistenceError) as raised:
                persist_github_latest_commit_collection(
                    self.database_path, _available()
                )
        self.assertEqual(raised.exception.category, "write_failed")
        self.assertNotIn("private", str(raised.exception))
        self.assertEqual(_counts(self.database_path), (1, 0, 0, 0))

    def test_exact_replay_is_idempotent_and_source_spelling_conflicts(self) -> None:
        self._persist_request()
        result = _available()
        first = persist_github_latest_commit_collection(
            self.database_path, result
        )
        before = _counts(self.database_path)
        second = persist_github_latest_commit_collection(
            self.database_path, result
        )
        self.assertEqual(first, second)
        self.assertEqual(_counts(self.database_path), before)

        equivalent_source = "2026-08-07T14:15:16Z"
        conflicting = _available(
            source_timestamp=equivalent_source,
            latest_commit_at=datetime(2026, 8, 7, 14, 15, 16, tzinfo=timezone.utc),
            raw_text=_raw(equivalent_source),
        )
        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_latest_commit_collection(
                self.database_path, conflicting
            )
        self.assertEqual(raised.exception.category, "conflicting_replay")
        self.assertEqual(_counts(self.database_path), before)

    def test_reused_attempt_number_conflicts_without_changing_history(self) -> None:
        self._persist_request()
        persist_github_latest_commit_collection(
            self.database_path, _available()
        )
        conflicting = _available(
            collection_attempt_id="collection-attempt-day-10-other"
        )
        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_latest_commit_collection(
                self.database_path, conflicting
            )
        self.assertEqual(raised.exception.category, "conflicting_replay")
        self.assertEqual(_counts(self.database_path), (1, 1, 1, 1))

    def test_source_and_normalized_corruption_fail_after_reopen(self) -> None:
        corruptions = (
            (
                "UPDATE github_source_snapshots SET response_bytes = ?",
                (b"[]",),
            ),
            (
                "UPDATE evidence_records SET latest_commit_timestamp_value = ?",
                ("2020-01-01T00:00:00+00:00",),
            ),
            (
                "UPDATE evidence_records SET compact_snapshot = ?, integrity_digest = ?",
                (
                    '{"value":"2020-01-01T00:00:00+00:00"}',
                    hashlib.sha256(
                        b'{"value":"2020-01-01T00:00:00+00:00"}'
                    ).hexdigest(),
                ),
            ),
        )
        for index, (sql, parameters) in enumerate(corruptions):
            with self.subTest(index=index):
                path = Path(self.temporary_directory.name) / "corrupt-{}.sqlite3".format(index)
                persist_valid_assessment_request(path, _valid_request())
                result = _available()
                persist_github_latest_commit_collection(path, result)
                with sqlite3.connect(path) as connection:
                    connection.execute(sql, parameters)
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_github_latest_commit_collection(path, result)
                self.assertEqual(raised.exception.category, "verification_failed")

    def test_provenance_relationship_and_version_corruption_fail_closed(self) -> None:
        corruptions = (
            ("provenance_json", '[["commit_sha","bad"]]'),
            ("assessment_id", "other-assessment"),
            ("normalization_version", "latest-commit-normalization.v999"),
        )
        for index, (column, value) in enumerate(corruptions):
            with self.subTest(column=column):
                path = Path(self.temporary_directory.name) / "metadata-{}.sqlite3".format(index)
                persist_valid_assessment_request(path, _valid_request())
                result = _available()
                persist_github_latest_commit_collection(path, result)
                with sqlite3.connect(path) as connection:
                    connection.execute("PRAGMA foreign_keys = OFF")
                    connection.execute(
                        "UPDATE evidence_records SET {} = ?".format(column),
                        (value,),
                    )
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_github_latest_commit_collection(path, result)
                self.assertEqual(raised.exception.category, "verification_failed")

    def test_archived_and_license_persistence_regressions_and_no_network(self) -> None:
        path = Path(self.temporary_directory.name) / "regression.sqlite3"
        request = _day9_valid_request()
        persist_valid_assessment_request(path, request)
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            side_effect=AssertionError("network must not be called"),
        ) as transport:
            archived = persist_github_repository_metadata_collection(
                path, _day9_available_archived()
            )
            license_evidence = persist_github_license_status_collection(
                path, _day9_available_license(attempt_number=2)
            )
        transport.assert_not_called()
        self.assertIs(archived.evidence_kind, EvidenceKind.REPOSITORY_ARCHIVED)
        self.assertIs(license_evidence.evidence_kind, EvidenceKind.LICENSE_STATUS)

    def test_latest_commit_persistence_performs_no_network_call(self) -> None:
        self._persist_request()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            side_effect=AssertionError("network must not be called"),
        ) as transport:
            evidence = persist_github_latest_commit_collection(
                self.database_path, _available()
            )
        transport.assert_not_called()
        self.assertIsNotNone(evidence)


if __name__ == "__main__":
    unittest.main()
