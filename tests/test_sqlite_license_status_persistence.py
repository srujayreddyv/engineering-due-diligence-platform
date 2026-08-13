"""Focused tests for SQLite license-status persistence and schema v2."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.persistence as persistence
from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubLicenseStatusCollectionResult,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
)
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    LicenseStatus,
    RiskTolerance,
)
from engineering_due_diligence.persistence import (
    SQLitePersistenceError,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_valid_assessment_request,
)
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
    validate_assessment_request,
)


SUBMITTED_AT = datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc)
ATTEMPTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
SOURCE_IDENTITY = "https://api.github.com/repos/example/reliable-library"
LICENSE_COLLECTOR_VERSION = "public-github-license-status.v1"
ARCHIVED_COLLECTOR_VERSION = "public-github-repository-metadata.v1"


def _valid_request(**changes: object):
    values = {
        "assessment_id": "assessment-day-9",
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


def _collection_input(**changes: object):
    values = {
        "assessment_id": "assessment-day-9",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-9-license-1",
        "attempt_number": 1,
        "attempted_at": ATTEMPTED_AT,
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _license_raw(status: LicenseStatus, *, unrelated: bool = False) -> str:
    license_metadata = (
        {
            "key": "mit",
            "name": "MIT License",
            "spdx_id": "MIT",
            **({"node_id": "license-node", "url": "https://example.invalid"}
               if unrelated else {}),
        }
        if status is LicenseStatus.PRESENT
        else None
    )
    payload = {
        "id": 9123,
        "full_name": "example/reliable-library",
        "license": license_metadata,
    }
    if unrelated:
        payload["topics"] = ["security", "python"]
    return json.dumps(payload, separators=(",", ":"))


def _available_license(
    status: LicenseStatus = LicenseStatus.PRESENT,
    *,
    raw_text: str | None = None,
    response_etag: str | None = '"etag-day-9"',
    **input_changes: object,
) -> GitHubLicenseStatusCollectionResult:
    request = _collection_input(**input_changes)
    raw_text = raw_text if raw_text is not None else _license_raw(status)
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=LICENSE_COLLECTOR_VERSION,
        source_identity=(
            "https://api.github.com/repos/{}".format(
                request.repository_identity.removeprefix("github.com/")
            )
        ),
        repository_source_id="9123",
        license_status=status,
        raw_snapshot=raw_text,
        integrity_digest=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _error(
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


def _unavailable_license(**input_changes: object):
    request = _collection_input(**input_changes)
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=LICENSE_COLLECTOR_VERSION,
        source_identity=SOURCE_IDENTITY,
        repository_source_id=None,
        license_status=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=404,
        response_etag=None,
        error=_error(
            "repository_not_publicly_available",
            "conditionally_retryable",
            "The repository is not available through the public GitHub endpoint.",
        ),
    )


def _failed_license(*, retryable: bool, **input_changes: object):
    request = _collection_input(**input_changes)
    if retryable:
        category = "github_server_error"
        retryability = "retryable"
        message = "GitHub could not complete the repository metadata request."
        status = 503
    else:
        category = "github_request_rejected"
        retryability = "nonretryable"
        message = "GitHub rejected the repository metadata request."
        status = 422
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=(
            GitHubCollectionOutcome.FAILED_RETRYABLE
            if retryable
            else GitHubCollectionOutcome.FAILED_NONRETRYABLE
        ),
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=LICENSE_COLLECTOR_VERSION,
        source_identity=SOURCE_IDENTITY,
        repository_source_id=None,
        license_status=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=status,
        response_etag=None,
        error=_error(category, retryability, message),
    )


def _available_archived(**input_changes: object):
    request = _collection_input(
        collection_attempt_id="collection-attempt-day-9-archived-1",
        **input_changes,
    )
    raw_text = (
        '{"id":9123,"full_name":"example/reliable-library",'
        '"archived":false}'
    )
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=ARCHIVED_COLLECTOR_VERSION,
        source_identity=SOURCE_IDENTITY,
        repository_source_id="9123",
        archived=False,
        raw_snapshot=raw_text,
        integrity_digest=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        response_status=200,
        response_etag='"archived-etag"',
        error=None,
    )


def _counts(path: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(path) as connection:
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


def _create_v1_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in persistence._SCHEMA_V1_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()


def _table_rows(path: Path, table: str, columns: tuple[str, ...]):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT {} FROM {} ORDER BY rowid".format(
                ", ".join(columns), table
            )
        ).fetchall()


class SQLiteLicenseStatusPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "day-9.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _persist_request(self):
        result = _valid_request()
        persist_valid_assessment_request(self.database_path, result)
        return result

    def test_fresh_schema_advances_to_version_four_with_typed_columns(self) -> None:
        self._persist_request()

        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = tuple(
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(evidence_records)"
                ).fetchall()
            )
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='evidence_records'"
            ).fetchone()[0]
        self.assertEqual(version, 5)
        self.assertIn("archived_value", columns)
        self.assertIn("license_status_value", columns)
        self.assertIn("'present', 'absent'", sql)

    def test_version_one_schema_migrates_transactionally(self) -> None:
        _create_v1_database(self.database_path)

        persist_valid_assessment_request(self.database_path, _valid_request())

        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 5
            )
            self.assertFalse(
                connection.execute("PRAGMA foreign_key_check").fetchall()
            )

    def test_migration_preserves_every_existing_archived_row_exactly(self) -> None:
        source = Path(self.temporary_directory.name) / "source-v2.sqlite3"
        request = _valid_request()
        persist_valid_assessment_request(source, request)
        persist_github_repository_metadata_collection(source, _available_archived())
        captured = {
            "assessment_requests": _table_rows(
                source, "assessment_requests", persistence._REQUEST_COLUMNS
            ),
            "collection_attempts": _table_rows(
                source, "collection_attempts", persistence._ATTEMPT_COLUMNS
            ),
            "github_source_snapshots": _table_rows(
                source,
                "github_source_snapshots",
                persistence._SOURCE_SNAPSHOT_COLUMNS,
            ),
            "evidence_records": _table_rows(
                source, "evidence_records", persistence._EVIDENCE_COLUMNS_V1
            ),
        }
        _create_v1_database(self.database_path)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            for table, columns in (
                ("assessment_requests", persistence._REQUEST_COLUMNS),
                ("collection_attempts", persistence._ATTEMPT_COLUMNS),
                ("github_source_snapshots", persistence._SOURCE_SNAPSHOT_COLUMNS),
                ("evidence_records", persistence._EVIDENCE_COLUMNS_V1),
            ):
                placeholders = ",".join("?" for _ in columns)
                connection.executemany(
                    "INSERT INTO {} ({}) VALUES ({})".format(
                        table, ",".join(columns), placeholders
                    ),
                    captured[table],
                )
            connection.commit()

        persist_valid_assessment_request(self.database_path, request)

        for table, columns in (
            ("assessment_requests", persistence._REQUEST_COLUMNS),
            ("collection_attempts", persistence._ATTEMPT_COLUMNS),
            ("github_source_snapshots", persistence._SOURCE_SNAPSHOT_COLUMNS),
            ("evidence_records", persistence._EVIDENCE_COLUMNS_V1),
        ):
            self.assertEqual(
                _table_rows(self.database_path, table, columns), captured[table]
            )

    def test_failed_migration_rolls_back_and_leaves_version_one(self) -> None:
        _create_v1_database(self.database_path)
        original_verify = persistence._verify_schema_definition

        def fail_v2_verification(
            connection: sqlite3.Connection,
            expected_columns: dict[str, tuple[str, ...]],
            expected_sql: dict[str, str],
        ) -> None:
            if expected_columns is persistence._EXPECTED_COLUMNS_V2:
                raise SQLitePersistenceError("schema_incompatible")
            original_verify(connection, expected_columns, expected_sql)

        with patch(
            "engineering_due_diligence.persistence._verify_schema_definition",
            side_effect=fail_v2_verification,
        ):
            with self.assertRaises(SQLitePersistenceError) as raised:
                persist_valid_assessment_request(
                    self.database_path, _valid_request()
                )

        self.assertEqual(raised.exception.category, "schema_incompatible")
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 1
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("collection_attempts", tables)
        self.assertIn("evidence_records", tables)
        self.assertNotIn("collection_attempts_v1", tables)
        self.assertNotIn("evidence_records_v1", tables)

        returned = persist_valid_assessment_request(
            self.database_path, _valid_request()
        )
        self.assertEqual(returned, _valid_request())

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA user_version = 99")

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_valid_assessment_request(self.database_path, _valid_request())

        self.assertEqual(raised.exception.category, "schema_incompatible")

        extra_table_path = (
            Path(self.temporary_directory.name) / "v1-with-extra-table.sqlite3"
        )
        _create_v1_database(extra_table_path)
        with sqlite3.connect(extra_table_path) as connection:
            connection.execute("CREATE TABLE unexpected_table (value TEXT)")
        with self.assertRaises(SQLitePersistenceError) as extra_table:
            persist_valid_assessment_request(extra_table_path, _valid_request())
        self.assertEqual(extra_table.exception.category, "schema_incompatible")
        with sqlite3.connect(extra_table_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 1
            )

    def test_valid_matching_request_is_required_before_license_persistence(self) -> None:
        with self.assertRaises(SQLitePersistenceError) as missing:
            persist_github_license_status_collection(
                self.database_path, _available_license()
            )
        self.assertEqual(missing.exception.category, "request_not_found")
        self._persist_request()
        with self.assertRaises(SQLitePersistenceError) as mismatch:
            persist_github_license_status_collection(
                self.database_path,
                _available_license(
                    repository_identity="github.com/example/other",
                    raw_text=(
                        '{"id":9123,"full_name":"example/other",'
                        '"license":{"key":"mit","name":"MIT License",'
                        '"spdx_id":"MIT"}}'
                    ),
                ),
            )
        self.assertEqual(mismatch.exception.category, "invalid_input")

    def test_present_license_is_durable_and_authoritative_after_reopen(self) -> None:
        self._persist_request()

        evidence = persist_github_license_status_collection(
            self.database_path, _available_license()
        )

        self.assertIs(evidence.value, LicenseStatus.PRESENT)
        self.assertIs(evidence.collection_outcome, EvidenceOutcome.AVAILABLE)
        self.assertIs(evidence.evidence_kind, EvidenceKind.LICENSE_STATUS)
        self.assertEqual(_counts(self.database_path), (1, 1, 1, 1))

    def test_absent_license_is_durable_and_authoritative_after_reopen(self) -> None:
        self._persist_request()

        evidence = persist_github_license_status_collection(
            self.database_path, _available_license(LicenseStatus.ABSENT)
        )

        self.assertIs(evidence.value, LicenseStatus.ABSENT)
        self.assertEqual(evidence.raw_snapshot, '{"value":"absent"}')

    def test_exact_full_response_bytes_and_digest_survive_reopen(self) -> None:
        raw_text = (
            '{\n "license":{"name":"MIT License","spdx_id":"MIT",'
            '"key":"mit"}, "full_name":"example/reliable-library",'
            '\n "id":9123}'
        )
        self._persist_request()

        persist_github_license_status_collection(
            self.database_path, _available_license(raw_text=raw_text)
        )

        with sqlite3.connect(self.database_path) as connection:
            response_bytes, digest = connection.execute(
                "SELECT response_bytes, integrity_digest "
                "FROM github_source_snapshots"
            ).fetchone()
        self.assertEqual(response_bytes, raw_text.encode("utf-8"))
        self.assertEqual(digest, hashlib.sha256(response_bytes).hexdigest())

    def test_compact_snapshot_and_digest_are_canonical(self) -> None:
        self._persist_request()
        evidence = persist_github_license_status_collection(
            self.database_path, _available_license()
        )

        self.assertEqual(evidence.raw_snapshot, '{"value":"present"}')
        self.assertEqual(
            evidence.integrity_digest,
            hashlib.sha256(evidence.raw_snapshot.encode("utf-8")).hexdigest(),
        )
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT archived_value, license_status_value "
                "FROM evidence_records"
            ).fetchone()
        self.assertEqual(row, (None, "present"))

    def test_unrelated_source_fields_survive_unchanged(self) -> None:
        raw_text = _license_raw(LicenseStatus.PRESENT, unrelated=True)
        self._persist_request()

        persist_github_license_status_collection(
            self.database_path, _available_license(raw_text=raw_text)
        )

        with sqlite3.connect(self.database_path) as connection:
            stored = connection.execute(
                "SELECT response_bytes FROM github_source_snapshots"
            ).fetchone()[0]
        self.assertEqual(stored.decode("utf-8"), raw_text)
        self.assertIn('"node_id":"license-node"', raw_text)

    def test_404_persists_unavailable_evidence_without_snapshot(self) -> None:
        self._persist_request()

        evidence = persist_github_license_status_collection(
            self.database_path, _unavailable_license()
        )

        self.assertIs(evidence.collection_outcome, EvidenceOutcome.UNAVAILABLE)
        self.assertIsNone(evidence.value)
        self.assertEqual(_counts(self.database_path), (1, 1, 0, 1))

    def test_retryable_and_nonretryable_failures_persist_attempts_only(self) -> None:
        self._persist_request()
        for number, retryable in ((1, True), (2, False)):
            result = _failed_license(
                retryable=retryable,
                attempt_number=number,
                collection_attempt_id="license-failure-{}".format(number),
            )
            self.assertIsNone(
                persist_github_license_status_collection(
                    self.database_path, result
                )
            )

        self.assertEqual(_counts(self.database_path), (1, 2, 0, 0))

    def test_linked_write_failure_rolls_back_all_license_rows(self) -> None:
        self._persist_request()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_license_evidence "
                "BEFORE INSERT ON evidence_records "
                "WHEN NEW.evidence_kind = 'license_status' "
                "BEGIN SELECT RAISE(ABORT, 'private'); END"
            )
        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_license_status_collection(
                self.database_path, _available_license()
            )

        self.assertEqual(raised.exception.category, "write_failed")
        self.assertEqual(_counts(self.database_path), (1, 0, 0, 0))

    def test_exact_replay_adds_no_rows(self) -> None:
        self._persist_request()
        result = _available_license()
        first = persist_github_license_status_collection(
            self.database_path, result
        )
        second = persist_github_license_status_collection(
            self.database_path, result
        )

        self.assertEqual(first, second)
        self.assertEqual(_counts(self.database_path), (1, 1, 1, 1))

    def test_conflicting_replay_preserves_existing_history(self) -> None:
        self._persist_request()
        persist_github_license_status_collection(
            self.database_path, _available_license()
        )
        conflicts = (
            _available_license(LicenseStatus.ABSENT),
            _available_license(
                collection_attempt_id="different-attempt-same-number"
            ),
        )
        for conflict in conflicts:
            with self.subTest(attempt=conflict.request.collection_attempt_id):
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_github_license_status_collection(
                        self.database_path, conflict
                    )
                self.assertEqual(
                    raised.exception.category, "conflicting_replay"
                )
        self.assertEqual(_counts(self.database_path), (1, 1, 1, 1))

    def test_timestamp_representation_difference_is_a_conflict(self) -> None:
        self._persist_request()
        original = _available_license()
        persist_github_license_status_collection(self.database_path, original)
        equivalent = ATTEMPTED_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_license_status_collection(
                self.database_path,
                _available_license(attempted_at=equivalent),
            )

        self.assertEqual(raised.exception.category, "conflicting_replay")

    def test_full_response_corruption_is_detected_after_reopen(self) -> None:
        self._persist_request()
        result = _available_license()
        persist_github_license_status_collection(self.database_path, result)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE github_source_snapshots SET response_bytes = ?",
                (b'{"id":9123,"full_name":"example/reliable-library",'
                 b'"license":null}',),
            )

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_license_status_collection(self.database_path, result)

        self.assertEqual(raised.exception.category, "verification_failed")

    def test_compact_snapshot_corruption_is_detected_after_reopen(self) -> None:
        self._persist_request()
        result = _available_license()
        persist_github_license_status_collection(self.database_path, result)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE evidence_records SET compact_snapshot = ?",
                ('{"value":"absent"}',),
            )

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_license_status_collection(self.database_path, result)

        self.assertEqual(raised.exception.category, "verification_failed")

    def test_normalized_license_value_corruption_is_detected_after_reopen(self) -> None:
        self._persist_request()
        result = _available_license()
        persist_github_license_status_collection(self.database_path, result)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE evidence_records SET license_status_value = 'absent'"
            )

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_license_status_collection(self.database_path, result)

        self.assertEqual(raised.exception.category, "verification_failed")

    def test_provenance_relationship_and_version_corruption_is_detected(self) -> None:
        corrupted = json.dumps(
            [["source_snapshot_id", "wrong"]], separators=(",", ":")
        )
        corruptions = (
            ("provenance_json", corrupted),
            ("source_snapshot_id", "wrong-source-snapshot"),
            ("normalization_version", "license-status-normalization.v999"),
            ("evidence_schema_version", "evidence-record.v999"),
        )
        for index, (column, value) in enumerate(corruptions, start=1):
            with self.subTest(column=column):
                database_path = (
                    Path(self.temporary_directory.name)
                    / "license-corruption-{}.sqlite3".format(index)
                )
                result = _available_license()
                persist_valid_assessment_request(
                    database_path, _valid_request()
                )
                persist_github_license_status_collection(
                    database_path, result
                )
                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "UPDATE evidence_records SET {} = ?".format(column),
                        (value,),
                    )

                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_github_license_status_collection(
                        database_path, result
                    )

                self.assertEqual(
                    raised.exception.category, "verification_failed"
                )

    def test_persistence_makes_no_network_calls(self) -> None:
        self._persist_request()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            side_effect=AssertionError("network must not be called"),
        ) as transport:
            evidence = persist_github_license_status_collection(
                self.database_path, _available_license()
            )

        transport.assert_not_called()
        self.assertIs(evidence.value, LicenseStatus.PRESENT)

        with patch(
            "engineering_due_diligence.persistence._license_expected_evidence",
            side_effect=RuntimeError("programmer error"),
        ):
            with self.assertRaisesRegex(RuntimeError, "programmer error"):
                persist_github_license_status_collection(
                    self.database_path, _available_license()
                )

    def test_existing_archived_persistence_remains_fully_functional(self) -> None:
        self._persist_request()

        evidence = persist_github_repository_metadata_collection(
            self.database_path, _available_archived()
        )

        self.assertIs(evidence.evidence_kind, EvidenceKind.REPOSITORY_ARCHIVED)
        self.assertIs(evidence.value, False)
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT archived_value, license_status_value "
                "FROM evidence_records"
            ).fetchone()
        self.assertEqual(row, (0, None))


if __name__ == "__main__":
    unittest.main()
