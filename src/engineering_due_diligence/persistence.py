"""Concrete SQLite persistence for repository evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple, Union

from .github import (
    GitHubCollectionOutcome,
    GitHubLicenseStatusCollectionResult,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
)
from .models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    EvidenceRecord,
    FreshnessStatus,
    LicenseStatus,
    RiskTolerance,
)
from .request import (
    AssessmentRequestInput,
    AssessmentRequestValidationResult,
    validate_assessment_request,
)


_DatabasePath = Union[str, os.PathLike[str]]

_SCHEMA_VERSION = 2
_SQLITE_SYNCHRONOUS_FULL = 2
_EVIDENCE_SCHEMA_VERSION = "evidence-record.v1"
_ARCHIVED_NORMALIZATION_VERSION = "repository-archived-normalization.v1"
_LICENSE_NORMALIZATION_VERSION = "license-status-normalization.v1"
_ARCHIVED_COLLECTOR_NAME = "public-github-repository-metadata"
_LICENSE_COLLECTOR_NAME = "public-github-license-status"
_SOURCE_SNAPSHOT_NAMESPACE = "github-source-snapshot.v1"
_ARCHIVED_EVIDENCE_NAMESPACE = "repository-archived-evidence.v1"
_LICENSE_EVIDENCE_NAMESPACE = "license-status-evidence.v1"
_SOURCE_SNAPSHOT_PREFIX = "github-source-snapshot-"
_ARCHIVED_EVIDENCE_PREFIX = "repository-archived-evidence-"
_LICENSE_EVIDENCE_PREFIX = "license-status-evidence-"

_ERROR_MESSAGES = {
    "invalid_input": "The persistence input is invalid.",
    "invalid_database_path": (
        "The database path must identify an on-disk SQLite database."
    ),
    "database_unavailable": "The SQLite database is unavailable.",
    "schema_incompatible": (
        "The SQLite persistence schema is incompatible."
    ),
    "request_not_found": "The persisted assessment request was not found.",
    "conflicting_replay": (
        "The persistence identity is already bound to different content."
    ),
    "write_failed": "The SQLite persistence transaction failed.",
    "verification_failed": (
        "The persisted content could not be verified."
    ),
}

_REQUEST_COLUMNS = (
    "assessment_id",
    "submitted_repository_locator",
    "intended_use",
    "environment",
    "criticality",
    "expected_lifetime_days",
    "risk_tolerance",
    "submitted_by_actor_id",
    "responsible_reviewer_actor_id",
    "submitted_at",
    "request_definition_version",
    "normalized_repository_identity",
)

_ATTEMPT_COLUMNS = (
    "collection_attempt_id",
    "assessment_id",
    "evidence_kind",
    "attempt_number",
    "attempted_at",
    "repository_identity",
    "collector_version",
    "source_identity",
    "outcome",
    "response_status",
    "response_etag",
    "error_category",
    "error_retryability",
    "error_message",
    "retry_after",
)

_SOURCE_SNAPSHOT_COLUMNS = (
    "source_snapshot_id",
    "collection_attempt_id",
    "response_bytes",
    "encoding",
    "media_type",
    "integrity_digest",
    "repository_source_id",
    "response_etag",
)

_EVIDENCE_COLUMNS_V1 = (
    "evidence_id",
    "assessment_id",
    "evidence_kind",
    "source_identity",
    "collector_name",
    "collector_version",
    "collection_attempt_id",
    "attempt_number",
    "attempted_at",
    "collection_outcome",
    "freshness_basis",
    "freshness_status_at_collection",
    "evidence_schema_version",
    "normalization_version",
    "provenance_json",
    "source_snapshot_id",
    "archived_value",
    "compact_snapshot",
    "integrity_digest",
    "unavailability_reason",
    "error_category",
)

_EVIDENCE_COLUMNS = (
    *_EVIDENCE_COLUMNS_V1[:17],
    "license_status_value",
    *_EVIDENCE_COLUMNS_V1[17:],
)

_EXPECTED_COLUMNS_V1 = {
    "assessment_requests": _REQUEST_COLUMNS,
    "collection_attempts": _ATTEMPT_COLUMNS,
    "github_source_snapshots": _SOURCE_SNAPSHOT_COLUMNS,
    "evidence_records": _EVIDENCE_COLUMNS_V1,
}

_SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE assessment_requests (
        assessment_id TEXT PRIMARY KEY
            CHECK (typeof(assessment_id) = 'text' AND length(assessment_id) > 0),
        submitted_repository_locator TEXT NOT NULL
            CHECK (typeof(submitted_repository_locator) = 'text'),
        intended_use TEXT NOT NULL
            CHECK (typeof(intended_use) = 'text' AND length(intended_use) > 0),
        environment TEXT NOT NULL
            CHECK (environment IN ('internal', 'production')),
        criticality TEXT NOT NULL
            CHECK (criticality IN ('low', 'critical')),
        expected_lifetime_days INTEGER NOT NULL
            CHECK (
                typeof(expected_lifetime_days) = 'integer'
                AND expected_lifetime_days > 0
            ),
        risk_tolerance TEXT NOT NULL
            CHECK (risk_tolerance IN ('tolerant', 'low')),
        submitted_by_actor_id TEXT NOT NULL
            CHECK (length(submitted_by_actor_id) > 0),
        responsible_reviewer_actor_id TEXT NOT NULL
            CHECK (length(responsible_reviewer_actor_id) > 0),
        submitted_at TEXT NOT NULL
            CHECK (typeof(submitted_at) = 'text' AND length(submitted_at) > 0),
        request_definition_version TEXT NOT NULL
            CHECK (length(request_definition_version) > 0),
        normalized_repository_identity TEXT NOT NULL
            CHECK (length(normalized_repository_identity) > 0)
    )
    """,
    """
    CREATE TABLE collection_attempts (
        collection_attempt_id TEXT PRIMARY KEY
            CHECK (length(collection_attempt_id) > 0),
        assessment_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL
            CHECK (evidence_kind = 'repository_archived'),
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number > 0),
        attempted_at TEXT NOT NULL
            CHECK (length(attempted_at) > 0),
        repository_identity TEXT NOT NULL
            CHECK (length(repository_identity) > 0),
        collector_version TEXT NOT NULL
            CHECK (length(collector_version) > 0),
        source_identity TEXT NOT NULL
            CHECK (length(source_identity) > 0),
        outcome TEXT NOT NULL
            CHECK (
                outcome IN (
                    'available',
                    'unavailable',
                    'failed_retryable',
                    'failed_nonretryable'
                )
            ),
        response_status INTEGER
            CHECK (
                response_status IS NULL
                OR (
                    typeof(response_status) = 'integer'
                    AND response_status BETWEEN 100 AND 599
                )
            ),
        response_etag TEXT,
        error_category TEXT,
        error_retryability TEXT,
        error_message TEXT,
        retry_after TEXT,
        FOREIGN KEY (assessment_id)
            REFERENCES assessment_requests(assessment_id),
        UNIQUE (assessment_id, evidence_kind, attempt_number),
        UNIQUE (collection_attempt_id, assessment_id),
        CHECK (
            (outcome = 'available'
                AND response_status = 200
                AND error_category IS NULL
                AND error_retryability IS NULL
                AND error_message IS NULL
                AND retry_after IS NULL)
            OR
            (outcome = 'unavailable'
                AND response_status = 404
                AND response_etag IS NULL
                AND error_category IS NOT NULL
                AND error_retryability IS NOT NULL
                AND error_message IS NOT NULL
                AND retry_after IS NULL)
            OR
            (outcome IN ('failed_retryable', 'failed_nonretryable')
                AND response_etag IS NULL
                AND error_category IS NOT NULL
                AND error_retryability IS NOT NULL
                AND error_message IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE github_source_snapshots (
        source_snapshot_id TEXT PRIMARY KEY
            CHECK (length(source_snapshot_id) > 0),
        collection_attempt_id TEXT NOT NULL UNIQUE,
        response_bytes BLOB NOT NULL
            CHECK (typeof(response_bytes) = 'blob'),
        encoding TEXT NOT NULL
            CHECK (encoding = 'utf-8'),
        media_type TEXT NOT NULL
            CHECK (media_type = 'application/json'),
        integrity_digest TEXT NOT NULL
            CHECK (length(integrity_digest) = 64),
        repository_source_id TEXT NOT NULL
            CHECK (length(repository_source_id) > 0),
        response_etag TEXT,
        FOREIGN KEY (collection_attempt_id)
            REFERENCES collection_attempts(collection_attempt_id),
        UNIQUE (source_snapshot_id, collection_attempt_id)
    )
    """,
    """
    CREATE TABLE evidence_records (
        evidence_id TEXT PRIMARY KEY
            CHECK (length(evidence_id) > 0),
        assessment_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL
            CHECK (evidence_kind = 'repository_archived'),
        source_identity TEXT NOT NULL
            CHECK (length(source_identity) > 0),
        collector_name TEXT NOT NULL
            CHECK (length(collector_name) > 0),
        collector_version TEXT NOT NULL
            CHECK (length(collector_version) > 0),
        collection_attempt_id TEXT NOT NULL UNIQUE,
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number > 0),
        attempted_at TEXT NOT NULL
            CHECK (length(attempted_at) > 0),
        collection_outcome TEXT NOT NULL
            CHECK (collection_outcome IN ('available', 'unavailable')),
        freshness_basis TEXT NOT NULL
            CHECK (length(freshness_basis) > 0),
        freshness_status_at_collection TEXT NOT NULL
            CHECK (
                freshness_status_at_collection IN (
                    'current', 'stale', 'unknown', 'not_applicable'
                )
            ),
        evidence_schema_version TEXT NOT NULL
            CHECK (length(evidence_schema_version) > 0),
        normalization_version TEXT NOT NULL
            CHECK (length(normalization_version) > 0),
        provenance_json TEXT NOT NULL
            CHECK (length(provenance_json) > 0),
        source_snapshot_id TEXT,
        archived_value INTEGER
            CHECK (
                archived_value IS NULL
                OR (
                    typeof(archived_value) = 'integer'
                    AND archived_value IN (0, 1)
                )
            ),
        compact_snapshot TEXT,
        integrity_digest TEXT,
        unavailability_reason TEXT,
        error_category TEXT,
        FOREIGN KEY (collection_attempt_id, assessment_id)
            REFERENCES collection_attempts(collection_attempt_id, assessment_id),
        FOREIGN KEY (source_snapshot_id, collection_attempt_id)
            REFERENCES github_source_snapshots(
                source_snapshot_id, collection_attempt_id
            ),
        CHECK (
            (collection_outcome = 'available'
                AND source_snapshot_id IS NOT NULL
                AND archived_value IS NOT NULL
                AND compact_snapshot IS NOT NULL
                AND integrity_digest IS NOT NULL
                AND unavailability_reason IS NULL
                AND error_category IS NULL)
            OR
            (collection_outcome = 'unavailable'
                AND source_snapshot_id IS NULL
                AND archived_value IS NULL
                AND compact_snapshot IS NULL
                AND integrity_digest IS NULL
                AND unavailability_reason IS NOT NULL
                AND error_category IS NOT NULL)
        )
    )
    """,
)

_EXPECTED_SCHEMA_SQL_V1 = dict(
    zip(_EXPECTED_COLUMNS_V1, _SCHEMA_V1_STATEMENTS)
)

_SCHEMA_V2_STATEMENTS = (
    _SCHEMA_V1_STATEMENTS[0],
    """
    CREATE TABLE collection_attempts (
        collection_attempt_id TEXT PRIMARY KEY
            CHECK (length(collection_attempt_id) > 0),
        assessment_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL
            CHECK (evidence_kind IN ('repository_archived', 'license_status')),
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number > 0),
        attempted_at TEXT NOT NULL
            CHECK (length(attempted_at) > 0),
        repository_identity TEXT NOT NULL
            CHECK (length(repository_identity) > 0),
        collector_version TEXT NOT NULL
            CHECK (length(collector_version) > 0),
        source_identity TEXT NOT NULL
            CHECK (length(source_identity) > 0),
        outcome TEXT NOT NULL
            CHECK (
                outcome IN (
                    'available',
                    'unavailable',
                    'failed_retryable',
                    'failed_nonretryable'
                )
            ),
        response_status INTEGER
            CHECK (
                response_status IS NULL
                OR (
                    typeof(response_status) = 'integer'
                    AND response_status BETWEEN 100 AND 599
                )
            ),
        response_etag TEXT,
        error_category TEXT,
        error_retryability TEXT,
        error_message TEXT,
        retry_after TEXT,
        FOREIGN KEY (assessment_id)
            REFERENCES assessment_requests(assessment_id),
        UNIQUE (assessment_id, evidence_kind, attempt_number),
        UNIQUE (collection_attempt_id, assessment_id),
        CHECK (
            (outcome = 'available'
                AND response_status = 200
                AND error_category IS NULL
                AND error_retryability IS NULL
                AND error_message IS NULL
                AND retry_after IS NULL)
            OR
            (outcome = 'unavailable'
                AND response_status = 404
                AND response_etag IS NULL
                AND error_category IS NOT NULL
                AND error_retryability IS NOT NULL
                AND error_message IS NOT NULL
                AND retry_after IS NULL)
            OR
            (outcome IN ('failed_retryable', 'failed_nonretryable')
                AND response_etag IS NULL
                AND error_category IS NOT NULL
                AND error_retryability IS NOT NULL
                AND error_message IS NOT NULL)
        )
    )
    """,
    _SCHEMA_V1_STATEMENTS[2],
    """
    CREATE TABLE evidence_records (
        evidence_id TEXT PRIMARY KEY
            CHECK (length(evidence_id) > 0),
        assessment_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL
            CHECK (evidence_kind IN ('repository_archived', 'license_status')),
        source_identity TEXT NOT NULL
            CHECK (length(source_identity) > 0),
        collector_name TEXT NOT NULL
            CHECK (length(collector_name) > 0),
        collector_version TEXT NOT NULL
            CHECK (length(collector_version) > 0),
        collection_attempt_id TEXT NOT NULL UNIQUE,
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number > 0),
        attempted_at TEXT NOT NULL
            CHECK (length(attempted_at) > 0),
        collection_outcome TEXT NOT NULL
            CHECK (collection_outcome IN ('available', 'unavailable')),
        freshness_basis TEXT NOT NULL
            CHECK (length(freshness_basis) > 0),
        freshness_status_at_collection TEXT NOT NULL
            CHECK (
                freshness_status_at_collection IN (
                    'current', 'stale', 'unknown', 'not_applicable'
                )
            ),
        evidence_schema_version TEXT NOT NULL
            CHECK (length(evidence_schema_version) > 0),
        normalization_version TEXT NOT NULL
            CHECK (length(normalization_version) > 0),
        provenance_json TEXT NOT NULL
            CHECK (length(provenance_json) > 0),
        source_snapshot_id TEXT,
        archived_value INTEGER
            CHECK (
                archived_value IS NULL
                OR (
                    typeof(archived_value) = 'integer'
                    AND archived_value IN (0, 1)
                )
            ),
        license_status_value TEXT
            CHECK (
                license_status_value IS NULL
                OR license_status_value IN ('present', 'absent')
            ),
        compact_snapshot TEXT,
        integrity_digest TEXT,
        unavailability_reason TEXT,
        error_category TEXT,
        FOREIGN KEY (collection_attempt_id, assessment_id)
            REFERENCES collection_attempts(collection_attempt_id, assessment_id),
        FOREIGN KEY (source_snapshot_id, collection_attempt_id)
            REFERENCES github_source_snapshots(
                source_snapshot_id, collection_attempt_id
            ),
        CHECK (
            (collection_outcome = 'available'
                AND source_snapshot_id IS NOT NULL
                AND compact_snapshot IS NOT NULL
                AND integrity_digest IS NOT NULL
                AND unavailability_reason IS NULL
                AND error_category IS NULL
                AND (
                    (evidence_kind = 'repository_archived'
                        AND archived_value IS NOT NULL
                        AND license_status_value IS NULL)
                    OR
                    (evidence_kind = 'license_status'
                        AND archived_value IS NULL
                        AND license_status_value IS NOT NULL)
                ))
            OR
            (collection_outcome = 'unavailable'
                AND source_snapshot_id IS NULL
                AND archived_value IS NULL
                AND license_status_value IS NULL
                AND compact_snapshot IS NULL
                AND integrity_digest IS NULL
                AND unavailability_reason IS NOT NULL
                AND error_category IS NOT NULL)
        )
    )
    """,
)

_EXPECTED_COLUMNS = {
    "assessment_requests": _REQUEST_COLUMNS,
    "collection_attempts": _ATTEMPT_COLUMNS,
    "github_source_snapshots": _SOURCE_SNAPSHOT_COLUMNS,
    "evidence_records": _EVIDENCE_COLUMNS,
}

_EXPECTED_SCHEMA_SQL = dict(
    zip(_EXPECTED_COLUMNS, _SCHEMA_V2_STATEMENTS)
)


class SQLitePersistenceError(Exception):
    """A stable sanitized failure from the concrete SQLite boundary."""

    def __init__(self, category: str) -> None:
        message = _ERROR_MESSAGES.get(category)
        if message is None:
            raise ValueError("unsupported persistence error category")
        self.category = category
        self.message = message
        super().__init__(message)


def _error(category: str) -> SQLitePersistenceError:
    return SQLitePersistenceError(category)


def _database_filename(database_path: _DatabasePath) -> str:
    try:
        filename = os.fspath(database_path)
    except (OSError, TypeError, ValueError):
        raise _error("invalid_database_path") from None
    if (
        type(filename) is not str
        or not filename
        or "\x00" in filename
        or filename.strip().casefold() == ":memory:"
        or filename.casefold().startswith("file:")
    ):
        raise _error("invalid_database_path")
    return filename


def _connect(filename: str) -> sqlite3.Connection:
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(filename)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        foreign_keys = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]
        synchronous = connection.execute(
            "PRAGMA synchronous"
        ).fetchone()[0]
        database_file = connection.execute(
            "PRAGMA database_list"
        ).fetchone()[2]
        if not database_file:
            connection.close()
            raise _error("invalid_database_path")
        if foreign_keys != 1 or synchronous != _SQLITE_SYNCHRONOUS_FULL:
            connection.close()
            raise _error("database_unavailable")
        _ensure_schema(connection)
        return connection
    except SQLitePersistenceError:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        raise
    except sqlite3.Error:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        raise _error("database_unavailable") from None


def _rollback_safely(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        pass


def _close_safely(connection: sqlite3.Connection) -> None:
    try:
        connection.close()
    except sqlite3.Error:
        pass


def _ensure_schema(connection: sqlite3.Connection) -> None:
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            existing_tables = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
            if existing_tables:
                raise _error("schema_incompatible")
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _SCHEMA_V2_STATEMENTS:
                    connection.execute(statement)
                _verify_schema_definition(
                    connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
                )
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise _error("schema_incompatible")
                connection.execute("PRAGMA user_version = 2")
                connection.commit()
            except Exception:
                _rollback_safely(connection)
                raise
        elif version == 1:
            _verify_schema_definition(
                connection,
                _EXPECTED_COLUMNS_V1,
                _EXPECTED_SCHEMA_SQL_V1,
            )
            _migrate_schema_v1_to_v2(connection)
        elif version != _SCHEMA_VERSION:
            raise _error("schema_incompatible")

        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
        )
        if connection.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise _error("schema_incompatible")
    except SQLitePersistenceError:
        raise
    except sqlite3.Error:
        raise _error("schema_incompatible") from None


def _verify_schema_definition(
    connection: sqlite3.Connection,
    expected_columns_by_table: dict[str, Tuple[str, ...]],
    expected_sql_by_table: dict[str, str],
) -> None:
    table_rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    actual_tables = tuple(row[0] for row in table_rows)
    if actual_tables != tuple(sorted(expected_columns_by_table)):
        raise _error("schema_incompatible")
    for table_name, expected_columns in expected_columns_by_table.items():
        rows = connection.execute(
            "PRAGMA table_info({})".format(table_name)
        ).fetchall()
        actual_columns = tuple(row[1] for row in rows)
        if actual_columns != expected_columns:
            raise _error("schema_incompatible")
        schema_rows = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchall()
        if len(schema_rows) != 1:
            raise _error("schema_incompatible")
        stored_sql = schema_rows[0][0]
        expected_sql = expected_sql_by_table[table_name]
        if (
            type(stored_sql) is not str
            or " ".join(stored_sql.split())
            != " ".join(expected_sql.split())
        ):
            raise _error("schema_incompatible")


def _migrate_schema_v1_to_v2(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "ALTER TABLE evidence_records RENAME TO evidence_records_v1"
        )
        connection.execute(
            "ALTER TABLE github_source_snapshots "
            "RENAME TO github_source_snapshots_v1"
        )
        connection.execute(
            "ALTER TABLE collection_attempts RENAME TO collection_attempts_v1"
        )
        connection.execute(_SCHEMA_V2_STATEMENTS[1])
        connection.execute(_SCHEMA_V2_STATEMENTS[2])
        connection.execute(_SCHEMA_V2_STATEMENTS[3])

        connection.execute(
            "INSERT INTO collection_attempts ({0}) "
            "SELECT {0} FROM collection_attempts_v1".format(
                ", ".join(_ATTEMPT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO github_source_snapshots ({0}) "
            "SELECT {0} FROM github_source_snapshots_v1".format(
                ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO evidence_records ({0}) "
            "SELECT {1}, NULL, {2} FROM evidence_records_v1".format(
                ", ".join(_EVIDENCE_COLUMNS),
                ", ".join(_EVIDENCE_COLUMNS_V1[:17]),
                ", ".join(_EVIDENCE_COLUMNS_V1[17:]),
            )
        )

        for old_table, new_table, columns in (
            (
                "collection_attempts_v1",
                "collection_attempts",
                _ATTEMPT_COLUMNS,
            ),
            (
                "github_source_snapshots_v1",
                "github_source_snapshots",
                _SOURCE_SNAPSHOT_COLUMNS,
            ),
            (
                "evidence_records_v1",
                "evidence_records",
                _EVIDENCE_COLUMNS_V1,
            ),
        ):
            selected = ", ".join(columns)
            primary_key = columns[0]
            old_rows = connection.execute(
                "SELECT {} FROM {} ORDER BY {}".format(
                    selected, old_table, primary_key
                )
            ).fetchall()
            new_rows = connection.execute(
                "SELECT {} FROM {} ORDER BY {}".format(
                    selected, new_table, primary_key
                )
            ).fetchall()
            if [tuple(row) for row in old_rows] != [
                tuple(row) for row in new_rows
            ]:
                raise _error("schema_incompatible")

        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("DROP TABLE evidence_records_v1")
        connection.execute("DROP TABLE github_source_snapshots_v1")
        connection.execute("DROP TABLE collection_attempts_v1")
        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except Exception:
        _rollback_safely(connection)
        raise


def _validated_request_result(
    validation_result: object,
) -> AssessmentRequestValidationResult:
    if type(validation_result) is not AssessmentRequestValidationResult:
        raise _error("invalid_input")
    try:
        reconstructed = AssessmentRequestValidationResult(
            request=validation_result.request,
            validation_status=validation_result.validation_status,
            normalized_repository_identity=(
                validation_result.normalized_repository_identity
            ),
            context=validation_result.context,
            validation_errors=validation_result.validation_errors,
        )
        revalidated = validate_assessment_request(validation_result.request)
    except (AttributeError, TypeError, ValueError):
        raise _error("invalid_input") from None
    if (
        reconstructed.validation_status != "valid"
        or revalidated != reconstructed
    ):
        raise _error("invalid_input")
    return reconstructed


def _request_values(
    validation_result: AssessmentRequestValidationResult,
) -> Tuple[object, ...]:
    request = validation_result.request
    return (
        request.assessment_id,
        request.submitted_repository_locator,
        request.intended_use,
        request.environment.value,
        request.criticality.value,
        request.expected_lifetime_days,
        request.risk_tolerance.value,
        request.submitted_by_actor_id,
        request.responsible_reviewer_actor_id,
        request.submitted_at.isoformat(),
        request.request_definition_version,
        validation_result.normalized_repository_identity,
    )


def _row_values(
    row: sqlite3.Row, columns: Tuple[str, ...]
) -> Tuple[object, ...]:
    return tuple(row[column] for column in columns)


def _parse_stored_datetime(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("stored timestamp must be text")
    parsed = datetime.fromisoformat(value)
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.isoformat() != value
    ):
        raise ValueError("stored timestamp is not canonical and aware")
    return parsed


def _request_result_from_row(
    row: sqlite3.Row,
) -> AssessmentRequestValidationResult:
    request = AssessmentRequestInput(
        assessment_id=row["assessment_id"],
        submitted_repository_locator=row["submitted_repository_locator"],
        intended_use=row["intended_use"],
        environment=Environment(row["environment"]),
        criticality=Criticality(row["criticality"]),
        expected_lifetime_days=row["expected_lifetime_days"],
        risk_tolerance=RiskTolerance(row["risk_tolerance"]),
        submitted_by_actor_id=row["submitted_by_actor_id"],
        responsible_reviewer_actor_id=row[
            "responsible_reviewer_actor_id"
        ],
        submitted_at=_parse_stored_datetime(row["submitted_at"]),
        request_definition_version=row["request_definition_version"],
    )
    result = validate_assessment_request(request)
    if (
        result.validation_status != "valid"
        or result.normalized_repository_identity
        != row["normalized_repository_identity"]
        or _request_values(result) != _row_values(row, _REQUEST_COLUMNS)
    ):
        raise ValueError("stored request does not reconstruct exactly")
    return result


def _read_request(
    connection: sqlite3.Connection,
    assessment_id: str,
) -> Tuple[sqlite3.Row, AssessmentRequestValidationResult]:
    rows = connection.execute(
        """
        SELECT {}
        FROM assessment_requests
        WHERE assessment_id = ?
        """.format(", ".join(_REQUEST_COLUMNS)),
        (assessment_id,),
    ).fetchall()
    if not rows:
        raise _error("request_not_found")
    if len(rows) != 1:
        raise _error("verification_failed")
    try:
        result = _request_result_from_row(rows[0])
    except (TypeError, ValueError):
        raise _error("verification_failed") from None
    return rows[0], result


def _verify_request_after_reopen(
    filename: str,
    expected: AssessmentRequestValidationResult,
) -> None:
    connection = _connect(filename)
    try:
        row, reconstructed = _read_request(
            connection, expected.request.assessment_id
        )
        if (
            _row_values(row, _REQUEST_COLUMNS) != _request_values(expected)
            or reconstructed != expected
        ):
            raise _error("verification_failed")
    except SQLitePersistenceError as exc:
        if exc.category == "request_not_found":
            raise _error("verification_failed") from None
        raise
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _close_safely(connection)


def persist_valid_assessment_request(
    database_path: _DatabasePath,
    validation_result: AssessmentRequestValidationResult,
) -> AssessmentRequestValidationResult:
    """Persist and reopen-verify one complete valid Day 5 request."""

    filename = _database_filename(database_path)
    expected = _validated_request_result(validation_result)
    try:
        expected_values = _request_values(expected)
    except (TypeError, ValueError):
        raise _error("invalid_input") from None
    connection = _connect(filename)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT {}
            FROM assessment_requests
            WHERE assessment_id = ?
            """.format(", ".join(_REQUEST_COLUMNS)),
            (expected.request.assessment_id,),
        ).fetchall()
        if rows:
            if len(rows) != 1:
                raise _error("verification_failed")
            try:
                _request_result_from_row(rows[0])
            except (TypeError, ValueError):
                raise _error("verification_failed") from None
            if _row_values(rows[0], _REQUEST_COLUMNS) != expected_values:
                raise _error("conflicting_replay")
        else:
            placeholders = ", ".join("?" for _ in _REQUEST_COLUMNS)
            connection.execute(
                "INSERT INTO assessment_requests ({}) VALUES ({})".format(
                    ", ".join(_REQUEST_COLUMNS), placeholders
                ),
                expected_values,
            )
        connection.commit()
    except SQLitePersistenceError:
        _rollback_safely(connection)
        raise
    except sqlite3.Error:
        _rollback_safely(connection)
        raise _error("write_failed") from None
    finally:
        _close_safely(connection)

    _verify_request_after_reopen(filename, expected)
    return validation_result


def _validated_collection_result(
    collection_result: object,
) -> GitHubRepositoryMetadataCollectionResult:
    if type(collection_result) is not GitHubRepositoryMetadataCollectionResult:
        raise _error("invalid_input")
    try:
        supplied_request = collection_result.request
        reconstructed_request = GitHubRepositoryMetadataCollectionInput(
            assessment_id=supplied_request.assessment_id,
            repository_identity=supplied_request.repository_identity,
            collection_attempt_id=supplied_request.collection_attempt_id,
            attempt_number=supplied_request.attempt_number,
            attempted_at=supplied_request.attempted_at,
        )
        error = collection_result.error
        reconstructed_error = None
        if error is not None:
            if type(error) is not GitHubRepositoryMetadataCollectionError:
                raise ValueError("invalid collection error")
            reconstructed_error = GitHubRepositoryMetadataCollectionError(
                category=error.category,
                retryability=error.retryability,
                message=error.message,
                retry_after=error.retry_after,
            )
        reconstructed = GitHubRepositoryMetadataCollectionResult(
            request=reconstructed_request,
            outcome=collection_result.outcome,
            evidence_kind=collection_result.evidence_kind,
            collector_version=collection_result.collector_version,
            source_identity=collection_result.source_identity,
            repository_source_id=collection_result.repository_source_id,
            archived=collection_result.archived,
            raw_snapshot=collection_result.raw_snapshot,
            integrity_digest=collection_result.integrity_digest,
            response_status=collection_result.response_status,
            response_etag=collection_result.response_etag,
            error=reconstructed_error,
        )
    except (AttributeError, TypeError, ValueError):
        raise _error("invalid_input") from None
    if reconstructed != collection_result:
        raise _error("invalid_input")
    return reconstructed


def _validated_license_collection_result(
    collection_result: object,
) -> GitHubLicenseStatusCollectionResult:
    if type(collection_result) is not GitHubLicenseStatusCollectionResult:
        raise _error("invalid_input")
    try:
        supplied_request = collection_result.request
        reconstructed_request = GitHubRepositoryMetadataCollectionInput(
            assessment_id=supplied_request.assessment_id,
            repository_identity=supplied_request.repository_identity,
            collection_attempt_id=supplied_request.collection_attempt_id,
            attempt_number=supplied_request.attempt_number,
            attempted_at=supplied_request.attempted_at,
        )
        error = collection_result.error
        reconstructed_error = None
        if error is not None:
            if type(error) is not GitHubRepositoryMetadataCollectionError:
                raise ValueError("invalid collection error")
            reconstructed_error = GitHubRepositoryMetadataCollectionError(
                category=error.category,
                retryability=error.retryability,
                message=error.message,
                retry_after=error.retry_after,
            )
        reconstructed = GitHubLicenseStatusCollectionResult(
            request=reconstructed_request,
            outcome=collection_result.outcome,
            evidence_kind=collection_result.evidence_kind,
            collector_version=collection_result.collector_version,
            source_identity=collection_result.source_identity,
            repository_source_id=collection_result.repository_source_id,
            license_status=collection_result.license_status,
            raw_snapshot=collection_result.raw_snapshot,
            integrity_digest=collection_result.integrity_digest,
            response_status=collection_result.response_status,
            response_etag=collection_result.response_etag,
            error=reconstructed_error,
        )
    except (AttributeError, TypeError, ValueError):
        raise _error("invalid_input") from None
    if reconstructed != collection_result:
        raise _error("invalid_input")
    return reconstructed


def _deterministic_identifier(
    namespace: str,
    prefix: str,
    assessment_id: str,
    evidence_kind: EvidenceKind,
    collection_attempt_id: str,
) -> str:
    material = "\0".join(
        (
            namespace,
            assessment_id,
            evidence_kind.value,
            collection_attempt_id,
        )
    ).encode("utf-8")
    return prefix + hashlib.sha256(material).hexdigest()


def _source_snapshot_id(
    request: GitHubRepositoryMetadataCollectionInput,
    evidence_kind: EvidenceKind = EvidenceKind.REPOSITORY_ARCHIVED,
) -> str:
    return _deterministic_identifier(
        _SOURCE_SNAPSHOT_NAMESPACE,
        _SOURCE_SNAPSHOT_PREFIX,
        request.assessment_id,
        evidence_kind,
        request.collection_attempt_id,
    )


def _evidence_id(
    request: GitHubRepositoryMetadataCollectionInput,
    evidence_kind: EvidenceKind = EvidenceKind.REPOSITORY_ARCHIVED,
) -> str:
    if evidence_kind is EvidenceKind.REPOSITORY_ARCHIVED:
        namespace = _ARCHIVED_EVIDENCE_NAMESPACE
        prefix = _ARCHIVED_EVIDENCE_PREFIX
    elif evidence_kind is EvidenceKind.LICENSE_STATUS:
        namespace = _LICENSE_EVIDENCE_NAMESPACE
        prefix = _LICENSE_EVIDENCE_PREFIX
    else:
        raise _error("verification_failed")
    return _deterministic_identifier(
        namespace,
        prefix,
        request.assessment_id,
        evidence_kind,
        request.collection_attempt_id,
    )


def _canonical_provenance_json(
    provenance: Tuple[Tuple[str, str], ...],
) -> str:
    return json.dumps(provenance, separators=(",", ":"))


def _parse_provenance(value: object) -> Tuple[Tuple[str, str], ...]:
    if type(value) is not str:
        raise ValueError("provenance must be text")
    parsed = json.loads(value)
    if type(parsed) is not list or not parsed:
        raise ValueError("provenance must be a nonempty list")
    provenance = []
    for item in parsed:
        if (
            type(item) is not list
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            or not item[0]
            or not item[1]
        ):
            raise ValueError("provenance entry is invalid")
        provenance.append((item[0], item[1]))
    result = tuple(provenance)
    if _canonical_provenance_json(result) != value:
        raise ValueError("provenance is not canonical")
    return result


def _expected_evidence(
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Optional[EvidenceRecord]:
    request = collection_result.request
    if collection_result.outcome is GitHubCollectionOutcome.AVAILABLE:
        if (
            type(collection_result.archived) is not bool
            or collection_result.integrity_digest is None
            or collection_result.repository_source_id is None
        ):
            raise _error("verification_failed")
        snapshot_id = _source_snapshot_id(request)
        provenance = (
            ("source_snapshot_id", snapshot_id),
            (
                "source_snapshot_integrity_digest",
                collection_result.integrity_digest,
            ),
            ("repository_source_id", collection_result.repository_source_id),
        )
        compact_snapshot = json.dumps(
            {"value": collection_result.archived},
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(request),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
                source_identity=collection_result.source_identity,
                collector_name=_ARCHIVED_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.AVAILABLE,
                freshness_basis="collection_time",
                freshness_status_at_collection=FreshnessStatus.CURRENT,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                value=collection_result.archived,
                raw_snapshot=compact_snapshot,
                integrity_digest=hashlib.sha256(
                    compact_snapshot.encode("utf-8")
                ).hexdigest(),
            )
        except ValueError:
            raise _error("verification_failed") from None

    if collection_result.outcome is GitHubCollectionOutcome.UNAVAILABLE:
        if collection_result.error is None:
            raise _error("verification_failed")
        provenance = (("collection_error_category", collection_result.error.category),)
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(request),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
                source_identity=collection_result.source_identity,
                collector_name=_ARCHIVED_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.UNAVAILABLE,
                freshness_basis="unknown",
                freshness_status_at_collection=FreshnessStatus.UNKNOWN,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                unavailability_reason="repository_not_publicly_available",
                error_category="repository_not_publicly_available",
            )
        except ValueError:
            raise _error("verification_failed") from None

    return None


def _attempt_values(
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Tuple[object, ...]:
    request = collection_result.request
    error = collection_result.error
    return (
        request.collection_attempt_id,
        request.assessment_id,
        collection_result.evidence_kind.value,
        request.attempt_number,
        request.attempted_at.isoformat(),
        request.repository_identity,
        collection_result.collector_version,
        collection_result.source_identity,
        collection_result.outcome.value,
        collection_result.response_status,
        collection_result.response_etag,
        error.category if error is not None else None,
        error.retryability if error is not None else None,
        error.message if error is not None else None,
        error.retry_after if error is not None else None,
    )


def _source_snapshot_values(
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Tuple[object, ...]:
    if (
        collection_result.raw_snapshot is None
        or collection_result.integrity_digest is None
        or collection_result.repository_source_id is None
    ):
        raise _error("verification_failed")
    return (
        _source_snapshot_id(collection_result.request),
        collection_result.request.collection_attempt_id,
        sqlite3.Binary(collection_result.raw_snapshot.encode("utf-8")),
        "utf-8",
        "application/json",
        collection_result.integrity_digest,
        collection_result.repository_source_id,
        collection_result.response_etag,
    )


def _license_expected_evidence(
    collection_result: GitHubLicenseStatusCollectionResult,
) -> Optional[EvidenceRecord]:
    request = collection_result.request
    if collection_result.outcome is GitHubCollectionOutcome.AVAILABLE:
        if (
            type(collection_result.license_status) is not LicenseStatus
            or collection_result.integrity_digest is None
            or collection_result.repository_source_id is None
        ):
            raise _error("verification_failed")
        snapshot_id = _source_snapshot_id(
            request, EvidenceKind.LICENSE_STATUS
        )
        provenance = (
            ("source_snapshot_id", snapshot_id),
            (
                "source_snapshot_integrity_digest",
                collection_result.integrity_digest,
            ),
            ("repository_source_id", collection_result.repository_source_id),
        )
        compact_snapshot = json.dumps(
            {"value": collection_result.license_status.value},
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.LICENSE_STATUS
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.LICENSE_STATUS,
                source_identity=collection_result.source_identity,
                collector_name=_LICENSE_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.AVAILABLE,
                freshness_basis="collection_time",
                freshness_status_at_collection=FreshnessStatus.CURRENT,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                value=collection_result.license_status,
                raw_snapshot=compact_snapshot,
                integrity_digest=hashlib.sha256(
                    compact_snapshot.encode("utf-8")
                ).hexdigest(),
            )
        except ValueError:
            raise _error("verification_failed") from None

    if collection_result.outcome is GitHubCollectionOutcome.UNAVAILABLE:
        if collection_result.error is None:
            raise _error("verification_failed")
        provenance = (
            ("collection_error_category", collection_result.error.category),
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.LICENSE_STATUS
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.LICENSE_STATUS,
                source_identity=collection_result.source_identity,
                collector_name=_LICENSE_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.UNAVAILABLE,
                freshness_basis="unknown",
                freshness_status_at_collection=FreshnessStatus.UNKNOWN,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                unavailability_reason="repository_not_publicly_available",
                error_category="repository_not_publicly_available",
            )
        except ValueError:
            raise _error("verification_failed") from None
    return None


def _license_source_snapshot_values(
    collection_result: GitHubLicenseStatusCollectionResult,
) -> Tuple[object, ...]:
    if (
        collection_result.raw_snapshot is None
        or collection_result.integrity_digest is None
        or collection_result.repository_source_id is None
    ):
        raise _error("verification_failed")
    return (
        _source_snapshot_id(
            collection_result.request, EvidenceKind.LICENSE_STATUS
        ),
        collection_result.request.collection_attempt_id,
        sqlite3.Binary(collection_result.raw_snapshot.encode("utf-8")),
        "utf-8",
        "application/json",
        collection_result.integrity_digest,
        collection_result.repository_source_id,
        collection_result.response_etag,
    )


def _license_evidence_values(evidence: EvidenceRecord) -> Tuple[object, ...]:
    is_available = evidence.collection_outcome is EvidenceOutcome.AVAILABLE
    return (
        evidence.evidence_id,
        evidence.assessment_id,
        evidence.evidence_kind.value,
        evidence.source_identity,
        evidence.collector_name,
        evidence.collector_version,
        evidence.collection_attempt_id,
        evidence.attempt_number,
        evidence.attempted_at.isoformat(),
        evidence.collection_outcome.value,
        evidence.freshness_basis,
        evidence.freshness_status_at_collection.value,
        evidence.evidence_schema_version,
        _LICENSE_NORMALIZATION_VERSION,
        _canonical_provenance_json(evidence.provenance),
        evidence.provenance[0][1] if is_available else None,
        None,
        evidence.value.value if is_available else None,
        evidence.raw_snapshot,
        evidence.integrity_digest,
        evidence.unavailability_reason,
        evidence.error_category,
    )


def _evidence_values(evidence: EvidenceRecord) -> Tuple[object, ...]:
    is_available = evidence.collection_outcome is EvidenceOutcome.AVAILABLE
    return (
        evidence.evidence_id,
        evidence.assessment_id,
        evidence.evidence_kind.value,
        evidence.source_identity,
        evidence.collector_name,
        evidence.collector_version,
        evidence.collection_attempt_id,
        evidence.attempt_number,
        evidence.attempted_at.isoformat(),
        evidence.collection_outcome.value,
        evidence.freshness_basis,
        evidence.freshness_status_at_collection.value,
        evidence.evidence_schema_version,
        _ARCHIVED_NORMALIZATION_VERSION,
        _canonical_provenance_json(evidence.provenance),
        (
            evidence.provenance[0][1]
            if is_available
            else None
        ),
        int(evidence.value) if is_available else None,
        None,
        evidence.raw_snapshot,
        evidence.integrity_digest,
        evidence.unavailability_reason,
        evidence.error_category,
    )


def _insert_values(
    connection: sqlite3.Connection,
    table: str,
    columns: Tuple[str, ...],
    values: Tuple[object, ...],
) -> None:
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        "INSERT INTO {} ({}) VALUES ({})".format(
            table, ", ".join(columns), placeholders
        ),
        values,
    )


def _collection_result_from_rows(
    attempt: sqlite3.Row,
    snapshots: Tuple[sqlite3.Row, ...],
) -> GitHubRepositoryMetadataCollectionResult:
    request = GitHubRepositoryMetadataCollectionInput(
        assessment_id=attempt["assessment_id"],
        repository_identity=attempt["repository_identity"],
        collection_attempt_id=attempt["collection_attempt_id"],
        attempt_number=attempt["attempt_number"],
        attempted_at=_parse_stored_datetime(attempt["attempted_at"]),
    )
    outcome = GitHubCollectionOutcome(attempt["outcome"])
    error = None
    if attempt["error_category"] is not None:
        error = GitHubRepositoryMetadataCollectionError(
            category=attempt["error_category"],
            retryability=attempt["error_retryability"],
            message=attempt["error_message"],
            retry_after=attempt["retry_after"],
        )

    repository_source_id = None
    archived = None
    raw_snapshot = None
    integrity_digest = None
    if outcome is GitHubCollectionOutcome.AVAILABLE:
        if len(snapshots) != 1:
            raise ValueError("available attempt requires one source snapshot")
        snapshot = snapshots[0]
        response_bytes = snapshot["response_bytes"]
        if type(response_bytes) is not bytes:
            raise ValueError("source response must be bytes")
        raw_snapshot = response_bytes.decode("utf-8")
        calculated_digest = hashlib.sha256(response_bytes).hexdigest()
        if (
            snapshot["encoding"] != "utf-8"
            or snapshot["media_type"] != "application/json"
            or snapshot["integrity_digest"] != calculated_digest
            or snapshot["response_etag"] != attempt["response_etag"]
            or snapshot["source_snapshot_id"] != _source_snapshot_id(request)
        ):
            raise ValueError("source snapshot verification failed")
        repository_source_id = snapshot["repository_source_id"]
        integrity_digest = snapshot["integrity_digest"]
        payload = json.loads(raw_snapshot)
        if type(payload) is not dict or type(payload.get("archived")) is not bool:
            raise ValueError("source payload cannot supply archived value")
        archived = payload["archived"]
    elif snapshots:
        raise ValueError("nonavailable attempt cannot have a source snapshot")

    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind(attempt["evidence_kind"]),
        collector_version=attempt["collector_version"],
        source_identity=attempt["source_identity"],
        repository_source_id=repository_source_id,
        archived=archived,
        raw_snapshot=raw_snapshot,
        integrity_digest=integrity_digest,
        response_status=attempt["response_status"],
        response_etag=attempt["response_etag"],
        error=error,
    )


def _evidence_from_row(row: sqlite3.Row) -> EvidenceRecord:
    evidence_kind = EvidenceKind(row["evidence_kind"])
    expected_normalization_version = (
        _ARCHIVED_NORMALIZATION_VERSION
        if evidence_kind is EvidenceKind.REPOSITORY_ARCHIVED
        else _LICENSE_NORMALIZATION_VERSION
        if evidence_kind is EvidenceKind.LICENSE_STATUS
        else None
    )
    if row["normalization_version"] != expected_normalization_version:
        raise ValueError("normalization version is not supported")
    provenance = _parse_provenance(row["provenance_json"])
    outcome = EvidenceOutcome(row["collection_outcome"])
    if outcome is EvidenceOutcome.AVAILABLE:
        if evidence_kind is EvidenceKind.REPOSITORY_ARCHIVED:
            archived_value = row["archived_value"]
            if (
                type(archived_value) is not int
                or archived_value not in (0, 1)
                or row["license_status_value"] is not None
            ):
                raise ValueError("stored archived value is invalid")
            value = bool(archived_value)
        elif evidence_kind is EvidenceKind.LICENSE_STATUS:
            if row["archived_value"] is not None:
                raise ValueError("stored license value is invalid")
            value = LicenseStatus(row["license_status_value"])
        else:
            raise ValueError("stored evidence kind is unsupported")
    else:
        value = None
    return EvidenceRecord(
        evidence_id=row["evidence_id"],
        assessment_id=row["assessment_id"],
        evidence_kind=evidence_kind,
        source_identity=row["source_identity"],
        collector_name=row["collector_name"],
        collector_version=row["collector_version"],
        collection_attempt_id=row["collection_attempt_id"],
        attempt_number=row["attempt_number"],
        attempted_at=_parse_stored_datetime(row["attempted_at"]),
        collection_outcome=outcome,
        freshness_basis=row["freshness_basis"],
        freshness_status_at_collection=FreshnessStatus(
            row["freshness_status_at_collection"]
        ),
        evidence_schema_version=row["evidence_schema_version"],
        provenance=provenance,
        value=value,
        raw_snapshot=row["compact_snapshot"],
        integrity_digest=row["integrity_digest"],
        unavailability_reason=row["unavailability_reason"],
        error_category=row["error_category"],
    )


def _verify_collection_after_reopen(
    filename: str,
    collection_attempt_id: str,
) -> Tuple[
    GitHubRepositoryMetadataCollectionResult,
    Optional[EvidenceRecord],
]:
    connection = _connect(filename)
    try:
        attempt_rows = connection.execute(
            """
            SELECT {}
            FROM collection_attempts
            WHERE collection_attempt_id = ?
            """.format(", ".join(_ATTEMPT_COLUMNS)),
            (collection_attempt_id,),
        ).fetchall()
        if len(attempt_rows) != 1:
            raise _error("verification_failed")
        attempt = attempt_rows[0]
        try:
            _, request_result = _read_request(
                connection, attempt["assessment_id"]
            )
        except SQLitePersistenceError as exc:
            if exc.category == "request_not_found":
                raise _error("verification_failed") from None
            raise
        if (
            request_result.normalized_repository_identity
            != attempt["repository_identity"]
        ):
            raise ValueError(
                "collection repository does not match persisted request"
            )

        snapshot_rows = tuple(
            connection.execute(
                """
                SELECT {}
                FROM github_source_snapshots
                WHERE collection_attempt_id = ?
                """.format(", ".join(_SOURCE_SNAPSHOT_COLUMNS)),
                (collection_attempt_id,),
            ).fetchall()
        )
        evidence_rows = tuple(
            connection.execute(
                """
                SELECT {}
                FROM evidence_records
                WHERE collection_attempt_id = ?
                """.format(", ".join(_EVIDENCE_COLUMNS)),
                (collection_attempt_id,),
            ).fetchall()
        )

        reconstructed_result = _collection_result_from_rows(
            attempt, snapshot_rows
        )
        if _attempt_values(reconstructed_result) != _row_values(
            attempt, _ATTEMPT_COLUMNS
        ):
            raise ValueError("collection attempt does not reconstruct exactly")

        expected_evidence = _expected_evidence(reconstructed_result)
        if expected_evidence is None:
            if evidence_rows:
                raise ValueError("failed attempt cannot have evidence")
            evidence = None
        else:
            if len(evidence_rows) != 1:
                raise ValueError("evidence outcome requires one evidence row")
            evidence = _evidence_from_row(evidence_rows[0])
            if (
                evidence != expected_evidence
                or _evidence_values(evidence)
                != _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
            ):
                raise ValueError("evidence does not reconstruct exactly")

        if reconstructed_result.outcome is GitHubCollectionOutcome.AVAILABLE:
            expected_snapshot = _source_snapshot_values(reconstructed_result)
            if _row_values(
                snapshot_rows[0], _SOURCE_SNAPSHOT_COLUMNS
            ) != tuple(expected_snapshot):
                raise ValueError("source snapshot does not reconstruct exactly")
        elif snapshot_rows:
            raise ValueError("unexpected source snapshot")

        foreign_key_failures = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_failures:
            raise ValueError("foreign key verification failed")
        return reconstructed_result, evidence
    except SQLitePersistenceError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise _error("verification_failed") from None
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _close_safely(connection)


def _license_collection_result_from_rows(
    attempt: sqlite3.Row,
    snapshots: Tuple[sqlite3.Row, ...],
) -> GitHubLicenseStatusCollectionResult:
    request = GitHubRepositoryMetadataCollectionInput(
        assessment_id=attempt["assessment_id"],
        repository_identity=attempt["repository_identity"],
        collection_attempt_id=attempt["collection_attempt_id"],
        attempt_number=attempt["attempt_number"],
        attempted_at=_parse_stored_datetime(attempt["attempted_at"]),
    )
    outcome = GitHubCollectionOutcome(attempt["outcome"])
    error = None
    if attempt["error_category"] is not None:
        error = GitHubRepositoryMetadataCollectionError(
            category=attempt["error_category"],
            retryability=attempt["error_retryability"],
            message=attempt["error_message"],
            retry_after=attempt["retry_after"],
        )

    repository_source_id = None
    license_status = None
    raw_snapshot = None
    integrity_digest = None
    if outcome is GitHubCollectionOutcome.AVAILABLE:
        if len(snapshots) != 1:
            raise ValueError("available attempt requires one source snapshot")
        snapshot = snapshots[0]
        response_bytes = snapshot["response_bytes"]
        if type(response_bytes) is not bytes:
            raise ValueError("source response must be bytes")
        raw_snapshot = response_bytes.decode("utf-8")
        calculated_digest = hashlib.sha256(response_bytes).hexdigest()
        if (
            snapshot["encoding"] != "utf-8"
            or snapshot["media_type"] != "application/json"
            or snapshot["integrity_digest"] != calculated_digest
            or snapshot["response_etag"] != attempt["response_etag"]
            or snapshot["source_snapshot_id"]
            != _source_snapshot_id(request, EvidenceKind.LICENSE_STATUS)
        ):
            raise ValueError("source snapshot verification failed")
        repository_source_id = snapshot["repository_source_id"]
        integrity_digest = snapshot["integrity_digest"]
        payload = json.loads(raw_snapshot)
        if type(payload) is not dict or "license" not in payload:
            raise ValueError("source payload cannot supply license value")
        license_status = (
            LicenseStatus.ABSENT
            if payload["license"] is None
            else LicenseStatus.PRESENT
        )
    elif snapshots:
        raise ValueError("nonavailable attempt cannot have a source snapshot")

    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind(attempt["evidence_kind"]),
        collector_version=attempt["collector_version"],
        source_identity=attempt["source_identity"],
        repository_source_id=repository_source_id,
        license_status=license_status,
        raw_snapshot=raw_snapshot,
        integrity_digest=integrity_digest,
        response_status=attempt["response_status"],
        response_etag=attempt["response_etag"],
        error=error,
    )


def _verify_license_collection_after_reopen(
    filename: str,
    collection_attempt_id: str,
) -> Tuple[GitHubLicenseStatusCollectionResult, Optional[EvidenceRecord]]:
    connection = _connect(filename)
    try:
        attempt_rows = connection.execute(
            """
            SELECT {}
            FROM collection_attempts
            WHERE collection_attempt_id = ?
            """.format(", ".join(_ATTEMPT_COLUMNS)),
            (collection_attempt_id,),
        ).fetchall()
        if len(attempt_rows) != 1:
            raise _error("verification_failed")
        attempt = attempt_rows[0]
        try:
            _, request_result = _read_request(
                connection, attempt["assessment_id"]
            )
        except SQLitePersistenceError as exc:
            if exc.category == "request_not_found":
                raise _error("verification_failed") from None
            raise
        if (
            request_result.normalized_repository_identity
            != attempt["repository_identity"]
        ):
            raise ValueError(
                "collection repository does not match persisted request"
            )

        snapshot_rows = tuple(
            connection.execute(
                """
                SELECT {}
                FROM github_source_snapshots
                WHERE collection_attempt_id = ?
                """.format(", ".join(_SOURCE_SNAPSHOT_COLUMNS)),
                (collection_attempt_id,),
            ).fetchall()
        )
        evidence_rows = tuple(
            connection.execute(
                """
                SELECT {}
                FROM evidence_records
                WHERE collection_attempt_id = ?
                """.format(", ".join(_EVIDENCE_COLUMNS)),
                (collection_attempt_id,),
            ).fetchall()
        )

        reconstructed_result = _license_collection_result_from_rows(
            attempt, snapshot_rows
        )
        if _attempt_values(reconstructed_result) != _row_values(
            attempt, _ATTEMPT_COLUMNS
        ):
            raise ValueError("collection attempt does not reconstruct exactly")

        expected_evidence = _license_expected_evidence(reconstructed_result)
        if expected_evidence is None:
            if evidence_rows:
                raise ValueError("failed attempt cannot have evidence")
            evidence = None
        else:
            if len(evidence_rows) != 1:
                raise ValueError("evidence outcome requires one evidence row")
            evidence = _evidence_from_row(evidence_rows[0])
            if (
                evidence != expected_evidence
                or _license_evidence_values(evidence)
                != _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
            ):
                raise ValueError("evidence does not reconstruct exactly")

        if reconstructed_result.outcome is GitHubCollectionOutcome.AVAILABLE:
            expected_snapshot = _license_source_snapshot_values(
                reconstructed_result
            )
            if _row_values(
                snapshot_rows[0], _SOURCE_SNAPSHOT_COLUMNS
            ) != tuple(expected_snapshot):
                raise ValueError("source snapshot does not reconstruct exactly")
        elif snapshot_rows:
            raise ValueError("unexpected source snapshot")

        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key verification failed")
        return reconstructed_result, evidence
    except SQLitePersistenceError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise _error("verification_failed") from None
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _close_safely(connection)


def persist_github_repository_metadata_collection(
    database_path: _DatabasePath,
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Optional[EvidenceRecord]:
    """Persist one terminal Day 6 outcome and return only verified evidence."""

    filename = _database_filename(database_path)
    expected_result = _validated_collection_result(collection_result)
    try:
        expected_evidence = _expected_evidence(expected_result)
        expected_attempt_values = _attempt_values(expected_result)
    except SQLitePersistenceError:
        raise
    except (TypeError, ValueError):
        raise _error("invalid_input") from None
    connection = _connect(filename)
    replay = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        request_row, request_result = _read_request(
            connection, expected_result.request.assessment_id
        )
        if (
            request_result.normalized_repository_identity
            != expected_result.request.repository_identity
            or request_result.context is None
            or request_result.context.assessment_id
            != expected_result.request.assessment_id
            or _row_values(request_row, _REQUEST_COLUMNS)
            != _request_values(request_result)
        ):
            raise _error("invalid_input")

        existing_attempts = connection.execute(
            """
            SELECT {}
            FROM collection_attempts
            WHERE collection_attempt_id = ?
            """.format(", ".join(_ATTEMPT_COLUMNS)),
            (expected_result.request.collection_attempt_id,),
        ).fetchall()
        if existing_attempts:
            if len(existing_attempts) != 1:
                raise _error("verification_failed")
            replay = True
            _rollback_safely(connection)
        else:
            reused_number = connection.execute(
                """
                SELECT collection_attempt_id
                FROM collection_attempts
                WHERE assessment_id = ?
                    AND evidence_kind = ?
                    AND attempt_number = ?
                """,
                (
                    expected_result.request.assessment_id,
                    expected_result.evidence_kind.value,
                    expected_result.request.attempt_number,
                ),
            ).fetchall()
            if reused_number:
                raise _error("conflicting_replay")

            _insert_values(
                connection,
                "collection_attempts",
                _ATTEMPT_COLUMNS,
                expected_attempt_values,
            )
            if expected_result.outcome is GitHubCollectionOutcome.AVAILABLE:
                _insert_values(
                    connection,
                    "github_source_snapshots",
                    _SOURCE_SNAPSHOT_COLUMNS,
                    _source_snapshot_values(expected_result),
                )
            if expected_evidence is not None:
                _insert_values(
                    connection,
                    "evidence_records",
                    _EVIDENCE_COLUMNS,
                    _evidence_values(expected_evidence),
                )
            connection.commit()
    except SQLitePersistenceError:
        _rollback_safely(connection)
        raise
    except sqlite3.Error:
        _rollback_safely(connection)
        raise _error("write_failed") from None
    finally:
        _close_safely(connection)

    stored_result, stored_evidence = _verify_collection_after_reopen(
        filename, expected_result.request.collection_attempt_id
    )
    if stored_result != expected_result or stored_evidence != expected_evidence:
        raise _error("conflicting_replay" if replay else "verification_failed")
    if (
        stored_result.request.attempted_at.isoformat()
        != expected_result.request.attempted_at.isoformat()
    ):
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored_evidence


def persist_github_license_status_collection(
    database_path: _DatabasePath,
    collection_result: GitHubLicenseStatusCollectionResult,
) -> Optional[EvidenceRecord]:
    """Persist one terminal license outcome and return verified evidence."""

    filename = _database_filename(database_path)
    expected_result = _validated_license_collection_result(collection_result)
    try:
        expected_evidence = _license_expected_evidence(expected_result)
        expected_attempt_values = _attempt_values(expected_result)
    except SQLitePersistenceError:
        raise
    except (TypeError, ValueError):
        raise _error("invalid_input") from None
    connection = _connect(filename)
    replay = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        request_row, request_result = _read_request(
            connection, expected_result.request.assessment_id
        )
        if (
            request_result.normalized_repository_identity
            != expected_result.request.repository_identity
            or request_result.context is None
            or request_result.context.assessment_id
            != expected_result.request.assessment_id
            or _row_values(request_row, _REQUEST_COLUMNS)
            != _request_values(request_result)
        ):
            raise _error("invalid_input")

        existing_attempts = connection.execute(
            """
            SELECT {}
            FROM collection_attempts
            WHERE collection_attempt_id = ?
            """.format(", ".join(_ATTEMPT_COLUMNS)),
            (expected_result.request.collection_attempt_id,),
        ).fetchall()
        if existing_attempts:
            if len(existing_attempts) != 1:
                raise _error("verification_failed")
            replay = True
            _rollback_safely(connection)
        else:
            reused_number = connection.execute(
                """
                SELECT collection_attempt_id
                FROM collection_attempts
                WHERE assessment_id = ?
                    AND evidence_kind = ?
                    AND attempt_number = ?
                """,
                (
                    expected_result.request.assessment_id,
                    expected_result.evidence_kind.value,
                    expected_result.request.attempt_number,
                ),
            ).fetchall()
            if reused_number:
                raise _error("conflicting_replay")

            _insert_values(
                connection,
                "collection_attempts",
                _ATTEMPT_COLUMNS,
                expected_attempt_values,
            )
            if expected_result.outcome is GitHubCollectionOutcome.AVAILABLE:
                _insert_values(
                    connection,
                    "github_source_snapshots",
                    _SOURCE_SNAPSHOT_COLUMNS,
                    _license_source_snapshot_values(expected_result),
                )
            if expected_evidence is not None:
                _insert_values(
                    connection,
                    "evidence_records",
                    _EVIDENCE_COLUMNS,
                    _license_evidence_values(expected_evidence),
                )
            connection.commit()
    except SQLitePersistenceError:
        _rollback_safely(connection)
        raise
    except sqlite3.Error:
        _rollback_safely(connection)
        raise _error("write_failed") from None
    finally:
        _close_safely(connection)

    stored_result, stored_evidence = _verify_license_collection_after_reopen(
        filename, expected_result.request.collection_attempt_id
    )
    if stored_result != expected_result or stored_evidence != expected_evidence:
        raise _error("conflicting_replay" if replay else "verification_failed")
    if (
        stored_result.request.attempted_at.isoformat()
        != expected_result.request.attempted_at.isoformat()
    ):
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored_evidence
