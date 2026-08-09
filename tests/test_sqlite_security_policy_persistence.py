"""Focused tests for durable GitHub-effective security-policy evidence."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.persistence as persistence
from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubRepositoryMetadataCollectionInput,
    collect_public_github_security_policy_presence,
)
from engineering_due_diligence.models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    RiskTolerance,
)
from engineering_due_diligence.persistence import (
    SQLitePersistenceError,
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
    NOT_FOUND,
    _policy_response,
    _repository_response,
)
from tests.test_sqlite_latest_commit_persistence import (
    _available as _latest_available,
    _valid_request as _latest_request,
)
from tests.test_sqlite_license_status_persistence import (
    _available_license,
    _valid_request as _license_request,
)
from tests.test_sqlite_repository_archived_persistence import (
    _available as _archived_available,
    _valid_request as _archived_request,
)


def _valid_request():
    return validate_assessment_request(
        AssessmentRequestInput(
            assessment_id="assessment-day-11",
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
            submitted_at=datetime(2026, 8, 8, 13, 30, tzinfo=timezone.utc),
            request_definition_version=REQUEST_DEFINITION_VERSION,
        )
    )


def _input(**changes):
    values = {
        "assessment_id": "assessment-day-11",
        "repository_identity": "github.com/Owner/Repository",
        "collection_attempt_id": "collection-attempt-day-11-security-1",
        "attempt_number": 1,
        "attempted_at": datetime(2026, 8, 8, 14, 0, tzinfo=timezone.utc),
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _collect(responses, **input_changes):
    with patch(
        "engineering_due_diligence.github._get_public_github_repository",
        side_effect=responses,
    ):
        return collect_public_github_security_policy_presence(
            _input(**input_changes)
        )


def _create_v3_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in persistence._SCHEMA_V3_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()


def _table_rows(path, table, columns):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT {} FROM {} ORDER BY {}".format(
                ",".join(columns), table, columns[0]
            )
        ).fetchall()


class SQLiteSecurityPolicyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-11.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _persist_request(self):
        request = _valid_request()
        persist_valid_assessment_request(self.database_path, request)
        return request

    def _persist(self, responses):
        self._persist_request()
        result = _collect(responses)
        evidence = persist_github_security_policy_presence_collection(
            self.database_path, result
        )
        return result, evidence

    def test_fresh_schema_is_exact_version_four(self):
        self._persist_request()
        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            evidence_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(evidence_records)"
                )
            }
            snapshot_sql = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='github_source_snapshots'"
            ).fetchone()[0]
        self.assertEqual(version, 4)
        self.assertIn("github_source_observations", tables)
        self.assertIn("security_policy_present_value", evidence_columns)
        self.assertNotIn("collection_attempt_id TEXT NOT NULL UNIQUE", snapshot_sql)

    def test_exact_v3_migration_preserves_all_prior_kind_rows(self):
        sources = []
        for name, request, persist, result in (
            (
                "archived",
                _archived_request(),
                persist_github_repository_metadata_collection,
                _archived_available(),
            ),
            (
                "license",
                _license_request(),
                persist_github_license_status_collection,
                _available_license(),
            ),
            (
                "latest",
                _latest_request(),
                persist_github_latest_commit_collection,
                _latest_available(),
            ),
        ):
            path = Path(self.temporary_directory.name) / (name + ".sqlite3")
            persist_valid_assessment_request(path, request)
            persist(path, result)
            sources.append(path)

        table_columns = (
            ("assessment_requests", persistence._REQUEST_COLUMNS),
            ("collection_attempts", persistence._ATTEMPT_COLUMNS),
            ("github_source_snapshots", persistence._SOURCE_SNAPSHOT_COLUMNS),
            ("evidence_records", persistence._EVIDENCE_COLUMNS_V3),
        )
        captured = {table: [] for table, _ in table_columns}
        for source in sources:
            for table, columns in table_columns:
                captured[table].extend(_table_rows(source, table, columns))

        _create_v3_database(self.database_path)
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

        persist_valid_assessment_request(self.database_path, _archived_request())
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 4
            )
            for table, columns in table_columns:
                actual = connection.execute(
                    "SELECT {} FROM {} ORDER BY {}".format(
                        ",".join(columns), table, columns[0]
                    )
                ).fetchall()
                self.assertEqual(actual, sorted(captured[table]))

    def test_v3_migration_failure_rolls_back_and_leaves_v3_usable(self):
        _create_v3_database(self.database_path)
        original_verify = persistence._verify_schema_definition

        def fail_v4(connection, expected_columns, expected_sql):
            if expected_columns is persistence._EXPECTED_COLUMNS:
                raise SQLitePersistenceError("schema_incompatible")
            return original_verify(connection, expected_columns, expected_sql)

        with patch(
            "engineering_due_diligence.persistence._verify_schema_definition",
            side_effect=fail_v4,
        ):
            with self.assertRaises(SQLitePersistenceError):
                persist_valid_assessment_request(
                    self.database_path, _valid_request()
                )
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 3
            )
            self.assertNotIn(
                "github_source_observations",
                {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                },
            )
        persist_valid_assessment_request(self.database_path, _valid_request())

    def test_local_true_is_authoritative_with_two_snapshots_and_observations(self):
        result, evidence = self._persist(
            [_repository_response(), _policy_response()]
        )
        self.assertIs(evidence.collection_outcome, EvidenceOutcome.AVAILABLE)
        self.assertIs(evidence.value, True)
        self.assertEqual(evidence.raw_snapshot, '{"value":true}')
        with sqlite3.connect(self.database_path) as connection:
            snapshots = connection.execute(
                "SELECT COUNT(*) FROM github_source_snapshots"
            ).fetchone()[0]
            observations = connection.execute(
                "SELECT source_role, response_status "
                "FROM github_source_observations ORDER BY request_sequence"
            ).fetchall()
        self.assertEqual(snapshots, 2)
        self.assertEqual(observations, [("repository", 200), ("target_dotgithub", 200)])
        self.assertIn(("policy_scope", "repository_local"), evidence.provenance)
        self.assertEqual(result.policy_blob_sha, "a" * 40)

    def test_inherited_true_preserves_order_and_every_successful_response(self):
        _, evidence = self._persist(
            [
                _repository_response(),
                NOT_FOUND,
                NOT_FOUND,
                NOT_FOUND,
                _policy_response(repository=".github"),
            ]
        )
        self.assertIs(evidence.value, True)
        self.assertIn(("policy_scope", "inherited_default"), evidence.provenance)
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM github_source_snapshots"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM github_source_observations"
                ).fetchone()[0],
                5,
            )

    def test_complete_absence_is_available_false_with_ordered_404s(self):
        _, evidence = self._persist(
            [_repository_response()] + [NOT_FOUND] * 6
        )
        self.assertIs(evidence.value, False)
        self.assertEqual(evidence.raw_snapshot, '{"value":false}')
        with sqlite3.connect(self.database_path) as connection:
            statuses = connection.execute(
                "SELECT response_status FROM github_source_observations "
                "ORDER BY request_sequence"
            ).fetchall()
            snapshots = connection.execute(
                "SELECT COUNT(*) FROM github_source_snapshots"
            ).fetchone()[0]
        self.assertEqual(statuses, [(200,)] + [(404,)] * 6)
        self.assertEqual(snapshots, 1)

    def test_repository_404_is_unavailable_evidence(self):
        _, evidence = self._persist([NOT_FOUND])
        self.assertIs(evidence.collection_outcome, EvidenceOutcome.UNAVAILABLE)
        self.assertIsNone(evidence.value)
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM github_source_observations"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM github_source_snapshots"
                ).fetchone()[0],
                0,
            )

    def test_failed_search_persists_completed_observations_without_evidence(self):
        self._persist_request()
        result = _collect(
            [_repository_response(), NOT_FOUND, (503, None, ())]
        )
        evidence = persist_github_security_policy_presence_collection(
            self.database_path, result
        )
        self.assertIsNone(evidence)
        with sqlite3.connect(self.database_path) as connection:
            counts = tuple(
                connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "collection_attempts",
                    "github_source_snapshots",
                    "github_source_observations",
                    "evidence_records",
                )
            )
        self.assertEqual(counts, (1, 1, 3, 0))

    def test_malformed_http_200_is_preserved_but_never_becomes_evidence(self):
        self._persist_request()
        result = _collect(
            [_repository_response(), (200, b"\xffnot-utf8 exactly", ())]
        )
        evidence = persist_github_security_policy_presence_collection(
            self.database_path, result
        )
        self.assertIsNone(evidence)
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT response_bytes, encoding, repository_source_id "
                "FROM github_source_snapshots ORDER BY source_snapshot_id"
            ).fetchall()
            error_category = connection.execute(
                "SELECT error_category FROM github_source_observations "
                "WHERE request_sequence = 2"
            ).fetchone()[0]
            evidence_count = connection.execute(
                "SELECT COUNT(*) FROM evidence_records"
            ).fetchone()[0]
        self.assertIn((b"\xffnot-utf8 exactly", "binary", None), rows)
        self.assertEqual(error_category, "github_response_invalid")
        self.assertEqual(evidence_count, 0)

    def test_matching_durable_request_is_required(self):
        result = _collect([_repository_response(), _policy_response()])
        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_security_policy_presence_collection(
                self.database_path, result
            )
        self.assertEqual(raised.exception.category, "request_not_found")

    def test_linked_write_failure_rolls_back_all_security_rows(self):
        self._persist_request()
        result = _collect([_repository_response(), _policy_response()])
        original_insert = persistence._insert_values

        def fail_observation(connection, table, columns, values):
            if table == "github_source_observations":
                raise sqlite3.IntegrityError("private path")
            return original_insert(connection, table, columns, values)

        with patch(
            "engineering_due_diligence.persistence._insert_values",
            side_effect=fail_observation,
        ):
            with self.assertRaises(SQLitePersistenceError) as raised:
                persist_github_security_policy_presence_collection(
                    self.database_path, result
                )
        self.assertEqual(raised.exception.category, "write_failed")
        with sqlite3.connect(self.database_path) as connection:
            for table in (
                "collection_attempts",
                "github_source_snapshots",
                "github_source_observations",
                "evidence_records",
            ):
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM " + table
                    ).fetchone()[0],
                    0,
                )

    def test_exact_replay_is_idempotent_and_observation_change_conflicts(self):
        self._persist_request()
        result = _collect([_repository_response(), _policy_response()])
        first = persist_github_security_policy_presence_collection(
            self.database_path, result
        )
        second = persist_github_security_policy_presence_collection(
            self.database_path, result
        )
        self.assertEqual(first, second)
        changed_terminal = replace(
            result.observations[-1], response_etag='"different"'
        )
        changed = replace(
            result,
            observations=(*result.observations[:-1], changed_terminal),
        )
        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_github_security_policy_presence_collection(
                self.database_path, changed
            )
        self.assertEqual(raised.exception.category, "conflicting_replay")
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM github_source_observations"
                ).fetchone()[0],
                2,
            )

    def test_reopen_detects_source_observation_value_and_provenance_corruption(self):
        corruptions = (
            "UPDATE github_source_snapshots SET response_bytes = x'7b7d' "
            "WHERE repository_source_id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
            "UPDATE github_source_observations SET source_role = 'target_root' "
            "WHERE request_sequence = 2",
            "UPDATE evidence_records SET security_policy_present_value = 0",
            "UPDATE evidence_records SET provenance_json = '[[\"bad\",\"value\"]]'",
        )
        for index, statement in enumerate(corruptions):
            with self.subTest(index=index):
                path = Path(self.temporary_directory.name) / "corrupt-{}.sqlite3".format(index)
                persist_valid_assessment_request(path, _valid_request())
                result = _collect([_repository_response(), _policy_response()])
                persist_github_security_policy_presence_collection(path, result)
                with sqlite3.connect(path) as connection:
                    connection.execute(statement)
                    connection.commit()
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_github_security_policy_presence_collection(path, result)
                self.assertIn(
                    raised.exception.category,
                    ("verification_failed", "conflicting_replay"),
                )

    def test_archived_license_and_latest_persistence_regressions(self):
        cases = (
            (_archived_request(), persist_github_repository_metadata_collection, _archived_available()),
            (_license_request(), persist_github_license_status_collection, _available_license()),
            (_latest_request(), persist_github_latest_commit_collection, _latest_available()),
        )
        for index, (request, persist, result) in enumerate(cases):
            with self.subTest(kind=result.evidence_kind):
                path = Path(self.temporary_directory.name) / "regression-{}.sqlite3".format(index)
                persist_valid_assessment_request(path, request)
                evidence = persist(path, result)
                self.assertIs(evidence.evidence_kind, result.evidence_kind)

    def test_persistence_performs_no_network_call(self):
        self._persist_request()
        result = _collect([_repository_response(), _policy_response()])
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            side_effect=AssertionError("network not allowed"),
        ):
            evidence = persist_github_security_policy_presence_collection(
                self.database_path, result
            )
        self.assertIs(evidence.value, True)


if __name__ == "__main__":
    unittest.main()
