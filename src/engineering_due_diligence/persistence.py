"""Concrete SQLite persistence for repository evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Union

from .github import (
    GitHubCollectionOutcome,
    GitHubLatestCommitCollectionResult,
    GitHubLicenseStatusCollectionResult,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
    GitHubSecurityPolicyPresenceCollectionResult,
    GitHubSecurityPolicySourceObservation,
)
from .models import (
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    EvidenceRecord,
    FreshnessStatus,
    HUMAN_DECISION_SCHEMA_VERSION,
    HumanDecision,
    HumanDecisionDisposition,
    LicenseStatus,
    PolicyOutcome,
    RiskTolerance,
)
from .request import (
    AssessmentRequestInput,
    AssessmentRequestValidationResult,
    validate_assessment_request,
)


_DatabasePath = Union[str, os.PathLike[str]]

_SCHEMA_VERSION = 5
_SQLITE_SYNCHRONOUS_FULL = 2
_EVIDENCE_SCHEMA_VERSION = "evidence-record.v1"
_ARCHIVED_NORMALIZATION_VERSION = "repository-archived-normalization.v1"
_LICENSE_NORMALIZATION_VERSION = "license-status-normalization.v1"
_LATEST_COMMIT_NORMALIZATION_VERSION = "latest-commit-normalization.v1"
_SECURITY_POLICY_NORMALIZATION_VERSION = (
    "security-policy-presence-normalization.v1"
)
_ARCHIVED_COLLECTOR_NAME = "public-github-repository-metadata"
_LICENSE_COLLECTOR_NAME = "public-github-license-status"
_LATEST_COMMIT_COLLECTOR_NAME = "public-github-latest-commit"
_SECURITY_POLICY_COLLECTOR_NAME = "public-github-security-policy-presence"
_SOURCE_SNAPSHOT_NAMESPACE = "github-source-snapshot.v1"
_ARCHIVED_EVIDENCE_NAMESPACE = "repository-archived-evidence.v1"
_LICENSE_EVIDENCE_NAMESPACE = "license-status-evidence.v1"
_LATEST_COMMIT_EVIDENCE_NAMESPACE = "latest-commit-evidence.v1"
_SECURITY_POLICY_EVIDENCE_NAMESPACE = "security-policy-evidence.v1"
_SECURITY_OBSERVATION_NAMESPACE = "github-security-source-observation.v1"
_SOURCE_SNAPSHOT_PREFIX = "github-source-snapshot-"
_ARCHIVED_EVIDENCE_PREFIX = "repository-archived-evidence-"
_LICENSE_EVIDENCE_PREFIX = "license-status-evidence-"
_LATEST_COMMIT_EVIDENCE_PREFIX = "latest-commit-evidence-"
_SECURITY_POLICY_EVIDENCE_PREFIX = "security-policy-evidence-"
_SECURITY_OBSERVATION_PREFIX = "github-security-source-observation-"

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
    "evidence_set_incomplete": (
        "The persisted assessment evidence set is incomplete."
    ),
    "evidence_set_ambiguous": (
        "The persisted assessment evidence set is ambiguous."
    ),
    "evaluation_not_found": (
        "The persisted assessment evaluation was not found."
    ),
    "decision_not_found": "The persisted human decision was not found.",
    "conflicting_replay": (
        "The persistence identity is already bound to different content."
    ),
    "write_failed": "The SQLite persistence transaction failed.",
    "verification_failed": (
        "The persisted content could not be verified."
    ),
}

_VERIFIED_EVIDENCE_KINDS = (
    EvidenceKind.REPOSITORY_ARCHIVED,
    EvidenceKind.LICENSE_STATUS,
    EvidenceKind.LATEST_COMMIT_TIMESTAMP,
    EvidenceKind.SECURITY_POLICY_PRESENT,
)

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

_SOURCE_OBSERVATION_COLUMNS = (
    "source_observation_id",
    "collection_attempt_id",
    "request_sequence",
    "source_role",
    "source_identity",
    "response_status",
    "response_etag",
    "error_category",
    "source_snapshot_id",
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

_EVIDENCE_COLUMNS_V2 = (
    *_EVIDENCE_COLUMNS_V1[:17],
    "license_status_value",
    *_EVIDENCE_COLUMNS_V1[17:],
)

_EVIDENCE_COLUMNS_V3 = (
    *_EVIDENCE_COLUMNS_V2[:18],
    "latest_commit_timestamp_value",
    *_EVIDENCE_COLUMNS_V2[18:],
)

_EVIDENCE_COLUMNS = (
    *_EVIDENCE_COLUMNS_V3[:19],
    "security_policy_present_value",
    *_EVIDENCE_COLUMNS_V3[19:],
)

_ASSESSMENT_EVALUATION_COLUMNS = (
    "assessment_evaluation_id",
    "assessment_id",
    "snapshot_json",
    "integrity_digest",
)

_HUMAN_DECISION_COLUMNS = (
    "human_decision_id",
    "assessment_id",
    "assessment_evaluation_id",
    "decision_maker_actor_id",
    "disposition",
    "rationale",
    "conditions_json",
    "information_requests_json",
    "acknowledged_policy_finding_ids_json",
    "recorded_at",
    "decision_schema_version",
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

_EXPECTED_COLUMNS_V2 = {
    "assessment_requests": _REQUEST_COLUMNS,
    "collection_attempts": _ATTEMPT_COLUMNS,
    "github_source_snapshots": _SOURCE_SNAPSHOT_COLUMNS,
    "evidence_records": _EVIDENCE_COLUMNS_V2,
}

_EXPECTED_SCHEMA_SQL_V2 = dict(
    zip(_EXPECTED_COLUMNS_V2, _SCHEMA_V2_STATEMENTS)
)

_SCHEMA_V3_STATEMENTS = (
    _SCHEMA_V2_STATEMENTS[0],
    _SCHEMA_V2_STATEMENTS[1]
    .replace(
        "evidence_kind IN ('repository_archived', 'license_status')",
        "evidence_kind IN (\n"
        "                'repository_archived',\n"
        "                'license_status',\n"
        "                'latest_commit_timestamp'\n"
        "            )",
    )
    .replace(
        "outcome = 'unavailable'\n                AND response_status = 404",
        "outcome = 'unavailable'\n"
        "                AND (\n"
        "                    (evidence_kind = 'latest_commit_timestamp'\n"
        "                        AND response_status IN (200, 404))\n"
        "                    OR\n"
        "                    (evidence_kind IN (\n"
        "                            'repository_archived', 'license_status'\n"
        "                        )\n"
        "                        AND response_status = 404)\n"
        "                )",
    ),
    _SCHEMA_V2_STATEMENTS[2],
    _SCHEMA_V2_STATEMENTS[3]
    .replace(
        "evidence_kind IN ('repository_archived', 'license_status')",
        "evidence_kind IN (\n"
        "                'repository_archived',\n"
        "                'license_status',\n"
        "                'latest_commit_timestamp'\n"
        "            )",
    )
    .replace(
        "        compact_snapshot TEXT,",
        "        latest_commit_timestamp_value TEXT\n"
        "            CHECK (\n"
        "                latest_commit_timestamp_value IS NULL\n"
        "                OR (\n"
        "                    typeof(latest_commit_timestamp_value) = 'text'\n"
        "                    AND length(latest_commit_timestamp_value) > 0\n"
        "                )\n"
        "            ),\n"
        "        compact_snapshot TEXT,",
    )
    .replace(
        "AND license_status_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'license_status'",
        "AND license_status_value IS NULL\n"
        "                        AND latest_commit_timestamp_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'license_status'",
    )
    .replace(
        "AND license_status_value IS NOT NULL)\n"
        "                ))",
        "AND license_status_value IS NOT NULL\n"
        "                        AND latest_commit_timestamp_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'latest_commit_timestamp'\n"
        "                        AND archived_value IS NULL\n"
        "                        AND license_status_value IS NULL\n"
        "                        AND latest_commit_timestamp_value IS NOT NULL)\n"
        "                ))",
    )
    .replace(
        "AND license_status_value IS NULL\n"
        "                AND compact_snapshot IS NULL",
        "AND license_status_value IS NULL\n"
        "                AND latest_commit_timestamp_value IS NULL\n"
        "                AND compact_snapshot IS NULL",
    ),
)

_EXPECTED_COLUMNS_V3 = {
    "assessment_requests": _REQUEST_COLUMNS,
    "collection_attempts": _ATTEMPT_COLUMNS,
    "github_source_snapshots": _SOURCE_SNAPSHOT_COLUMNS,
    "evidence_records": _EVIDENCE_COLUMNS_V3,
}

_EXPECTED_SCHEMA_SQL_V3 = dict(
    zip(_EXPECTED_COLUMNS_V3, _SCHEMA_V3_STATEMENTS)
)

_SCHEMA_V4_STATEMENTS = (
    _SCHEMA_V3_STATEMENTS[0],
    _SCHEMA_V3_STATEMENTS[1]
    .replace(
        "'latest_commit_timestamp'\n            )",
        "'latest_commit_timestamp',\n"
        "                'security_policy_present'\n"
        "            )",
    )
    .replace(
        "(outcome = 'available'\n                AND response_status = 200",
        "(outcome = 'available'\n"
        "                AND (\n"
        "                    (evidence_kind = 'security_policy_present'\n"
        "                        AND response_status IN (200, 404))\n"
        "                    OR\n"
        "                    (evidence_kind != 'security_policy_present'\n"
        "                        AND response_status = 200)\n"
        "                )",
    )
    .replace(
        "'repository_archived', 'license_status'\n                        )",
        "'repository_archived', 'license_status',\n"
        "                            'security_policy_present'\n"
        "                        )",
    ),
    _SCHEMA_V3_STATEMENTS[2].replace(
        "collection_attempt_id TEXT NOT NULL UNIQUE,",
        "collection_attempt_id TEXT NOT NULL,",
    ).replace(
        "CHECK (encoding = 'utf-8')",
        "CHECK (encoding IN ('utf-8', 'binary'))",
    ).replace(
        "repository_source_id TEXT NOT NULL\n"
        "            CHECK (length(repository_source_id) > 0),",
        "repository_source_id TEXT\n"
        "            CHECK (\n"
        "                repository_source_id IS NULL\n"
        "                OR (\n"
        "                    typeof(repository_source_id) = 'text'\n"
        "                    AND length(repository_source_id) > 0\n"
        "                )\n"
        "            ),",
    ),
    _SCHEMA_V3_STATEMENTS[3]
    .replace(
        "'latest_commit_timestamp'\n            )",
        "'latest_commit_timestamp',\n"
        "                'security_policy_present'\n"
        "            )",
    )
    .replace(
        "        compact_snapshot TEXT,",
        "        security_policy_present_value INTEGER\n"
        "            CHECK (\n"
        "                security_policy_present_value IS NULL\n"
        "                OR (\n"
        "                    typeof(security_policy_present_value) = 'integer'\n"
        "                    AND security_policy_present_value IN (0, 1)\n"
        "                )\n"
        "            ),\n"
        "        compact_snapshot TEXT,",
    )
    .replace(
        "AND latest_commit_timestamp_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'license_status'",
        "AND latest_commit_timestamp_value IS NULL\n"
        "                        AND security_policy_present_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'license_status'",
    )
    .replace(
        "AND latest_commit_timestamp_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'latest_commit_timestamp'",
        "AND latest_commit_timestamp_value IS NULL\n"
        "                        AND security_policy_present_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'latest_commit_timestamp'",
    )
    .replace(
        "AND latest_commit_timestamp_value IS NOT NULL)\n"
        "                ))",
        "AND latest_commit_timestamp_value IS NOT NULL\n"
        "                        AND security_policy_present_value IS NULL)\n"
        "                    OR\n"
        "                    (evidence_kind = 'security_policy_present'\n"
        "                        AND archived_value IS NULL\n"
        "                        AND license_status_value IS NULL\n"
        "                        AND latest_commit_timestamp_value IS NULL\n"
        "                        AND security_policy_present_value IS NOT NULL)\n"
        "                ))",
    )
    .replace(
        "AND latest_commit_timestamp_value IS NULL\n"
        "                AND compact_snapshot IS NULL",
        "AND latest_commit_timestamp_value IS NULL\n"
        "                AND security_policy_present_value IS NULL\n"
        "                AND compact_snapshot IS NULL",
    ),
    """
    CREATE TABLE github_source_observations (
        source_observation_id TEXT PRIMARY KEY
            CHECK (length(source_observation_id) > 0),
        collection_attempt_id TEXT NOT NULL,
        request_sequence INTEGER NOT NULL
            CHECK (typeof(request_sequence) = 'integer' AND request_sequence > 0),
        source_role TEXT NOT NULL
            CHECK (source_role IN (
                'repository',
                'target_dotgithub',
                'target_root',
                'target_docs',
                'default_dotgithub',
                'default_root',
                'default_docs'
            )),
        source_identity TEXT NOT NULL
            CHECK (length(source_identity) > 0),
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
        source_snapshot_id TEXT,
        FOREIGN KEY (collection_attempt_id)
            REFERENCES collection_attempts(collection_attempt_id),
        FOREIGN KEY (source_snapshot_id, collection_attempt_id)
            REFERENCES github_source_snapshots(
                source_snapshot_id, collection_attempt_id
            ),
        UNIQUE (collection_attempt_id, request_sequence),
        UNIQUE (source_observation_id, collection_attempt_id),
        CHECK (
            (response_status = 200
                AND (
                    source_snapshot_id IS NOT NULL
                    OR error_category IS NOT NULL
                ))
            OR
            (response_status = 404
                AND source_snapshot_id IS NULL
                AND response_etag IS NULL)
            OR
            (error_category IS NOT NULL
                AND (response_status IS NULL OR response_status != 200)
                AND source_snapshot_id IS NULL
                AND response_etag IS NULL)
        )
    )
    """,
)

_EXPECTED_COLUMNS_V4 = {
    "assessment_requests": _REQUEST_COLUMNS,
    "collection_attempts": _ATTEMPT_COLUMNS,
    "github_source_snapshots": _SOURCE_SNAPSHOT_COLUMNS,
    "evidence_records": _EVIDENCE_COLUMNS,
    "github_source_observations": _SOURCE_OBSERVATION_COLUMNS,
}

_EXPECTED_SCHEMA_SQL_V4 = dict(
    zip(_EXPECTED_COLUMNS_V4, _SCHEMA_V4_STATEMENTS)
)

_SCHEMA_V5_STATEMENTS = (
    *_SCHEMA_V4_STATEMENTS,
    """
    CREATE TABLE assessment_evaluation_snapshots (
        assessment_evaluation_id TEXT PRIMARY KEY
            CHECK (
                typeof(assessment_evaluation_id) = 'text'
                AND length(assessment_evaluation_id) = 86
                AND assessment_evaluation_id LIKE 'assessment-evaluation-%'
            ),
        assessment_id TEXT NOT NULL UNIQUE
            CHECK (typeof(assessment_id) = 'text' AND length(assessment_id) > 0),
        snapshot_json TEXT NOT NULL
            CHECK (typeof(snapshot_json) = 'text' AND length(snapshot_json) > 0),
        integrity_digest TEXT NOT NULL
            CHECK (
                typeof(integrity_digest) = 'text'
                AND length(integrity_digest) = 64
                AND integrity_digest = lower(integrity_digest)
                AND integrity_digest NOT GLOB '*[^0-9a-f]*'
            ),
        FOREIGN KEY (assessment_id)
            REFERENCES assessment_requests(assessment_id),
        UNIQUE (assessment_evaluation_id, assessment_id)
    )
    """,
    """
    CREATE TABLE human_decisions (
        human_decision_id TEXT PRIMARY KEY
            CHECK (
                typeof(human_decision_id) = 'text'
                AND length(human_decision_id) = 79
                AND human_decision_id LIKE 'human-decision-%'
            ),
        assessment_id TEXT NOT NULL UNIQUE
            CHECK (typeof(assessment_id) = 'text' AND length(assessment_id) > 0),
        assessment_evaluation_id TEXT NOT NULL UNIQUE
            CHECK (
                typeof(assessment_evaluation_id) = 'text'
                AND length(assessment_evaluation_id) > 0
            ),
        decision_maker_actor_id TEXT NOT NULL
            CHECK (
                typeof(decision_maker_actor_id) = 'text'
                AND length(decision_maker_actor_id) > 0
            ),
        disposition TEXT NOT NULL
            CHECK (disposition IN (
                'approve',
                'approve_with_conditions',
                'needs_more_information',
                'reject'
            )),
        rationale TEXT NOT NULL
            CHECK (typeof(rationale) = 'text' AND length(rationale) > 0),
        conditions_json TEXT NOT NULL
            CHECK (typeof(conditions_json) = 'text'),
        information_requests_json TEXT NOT NULL
            CHECK (typeof(information_requests_json) = 'text'),
        acknowledged_policy_finding_ids_json TEXT NOT NULL
            CHECK (typeof(acknowledged_policy_finding_ids_json) = 'text'),
        recorded_at TEXT NOT NULL
            CHECK (typeof(recorded_at) = 'text' AND length(recorded_at) > 0),
        decision_schema_version TEXT NOT NULL
            CHECK (decision_schema_version = 'human-decision.v1'),
        FOREIGN KEY (assessment_id)
            REFERENCES assessment_requests(assessment_id),
        FOREIGN KEY (assessment_evaluation_id, assessment_id)
            REFERENCES assessment_evaluation_snapshots(
                assessment_evaluation_id, assessment_id
            ),
        CHECK (
            (disposition = 'approve'
                AND conditions_json = '[]'
                AND information_requests_json = '[]')
            OR
            (disposition = 'approve_with_conditions'
                AND conditions_json != '[]'
                AND information_requests_json = '[]')
            OR
            (disposition = 'needs_more_information'
                AND conditions_json = '[]'
                AND information_requests_json != '[]'
                AND acknowledged_policy_finding_ids_json = '[]')
            OR
            (disposition = 'reject'
                AND conditions_json = '[]'
                AND information_requests_json = '[]'
                AND acknowledged_policy_finding_ids_json = '[]')
        )
    )
    """,
)

_EXPECTED_COLUMNS = {
    **_EXPECTED_COLUMNS_V4,
    "assessment_evaluation_snapshots": _ASSESSMENT_EVALUATION_COLUMNS,
    "human_decisions": _HUMAN_DECISION_COLUMNS,
}

_EXPECTED_SCHEMA_SQL = dict(
    zip(_EXPECTED_COLUMNS, _SCHEMA_V5_STATEMENTS)
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


@dataclass(frozen=True)
class VerifiedAssessmentEvidenceSet:
    """One valid durable request and its complete verified evidence set."""

    validation_result: AssessmentRequestValidationResult
    evidence_records: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        validation_result = self.validation_result
        if (
            not isinstance(
                validation_result, AssessmentRequestValidationResult
            )
            or validation_result.validation_status != "valid"
            or validation_result.context is None
            or validation_result.normalized_repository_identity is None
            or validation_result.validation_errors
        ):
            raise ValueError(
                "validation_result must be one complete valid request"
            )
        if (
            type(self.evidence_records) is not tuple
            or not all(
                type(record) is EvidenceRecord
                for record in self.evidence_records
            )
            or tuple(record.evidence_kind for record in self.evidence_records)
            != _VERIFIED_EVIDENCE_KINDS
        ):
            raise ValueError(
                "evidence_records must contain the four canonical kinds"
            )
        if validate_assessment_request(
            validation_result.request
        ) != validation_result:
            raise ValueError(
                "validation_result must reconstruct from its request"
            )
        assessment_id = validation_result.request.assessment_id
        if any(
            record.assessment_id != assessment_id
            for record in self.evidence_records
        ):
            raise ValueError(
                "evidence_records must belong to the validated request"
            )
        if len(
            {record.evidence_id for record in self.evidence_records}
        ) != len(self.evidence_records) or len(
            {
                record.collection_attempt_id
                for record in self.evidence_records
            }
        ) != len(self.evidence_records):
            raise ValueError(
                "evidence_records must have unique evidence and attempt IDs"
            )


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


def _connect_read_only_v5(filename: str) -> sqlite3.Connection:
    connection: Optional[sqlite3.Connection] = None
    try:
        database_uri = Path(filename).absolute().as_uri() + "?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        foreign_keys = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]
        query_only = connection.execute("PRAGMA query_only").fetchone()[0]
        database_file = connection.execute(
            "PRAGMA database_list"
        ).fetchone()[2]
        if not database_file or foreign_keys != 1 or query_only != 1:
            raise _error("database_unavailable")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 5:
            raise _error("schema_incompatible")
        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("verification_failed")
        return connection
    except SQLitePersistenceError:
        if connection is not None:
            _rollback_safely(connection)
            _close_safely(connection)
        raise
    except (OSError, ValueError, sqlite3.Error):
        if connection is not None:
            _rollback_safely(connection)
            _close_safely(connection)
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
                for statement in _SCHEMA_V5_STATEMENTS:
                    connection.execute(statement)
                _verify_schema_definition(
                    connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
                )
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise _error("schema_incompatible")
                connection.execute("PRAGMA user_version = 5")
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
        elif version not in (2, 3, 4, _SCHEMA_VERSION):
            raise _error("schema_incompatible")

        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            _verify_schema_definition(
                connection,
                _EXPECTED_COLUMNS_V2,
                _EXPECTED_SCHEMA_SQL_V2,
            )
            _migrate_schema_v2_to_v3(connection)
        elif version not in (3, 4, _SCHEMA_VERSION):
            raise _error("schema_incompatible")

        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 3:
            _verify_schema_definition(
                connection,
                _EXPECTED_COLUMNS_V3,
                _EXPECTED_SCHEMA_SQL_V3,
            )
            _migrate_schema_v3_to_v4(connection)
        elif version not in (4, _SCHEMA_VERSION):
            raise _error("schema_incompatible")

        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 4:
            _verify_schema_definition(
                connection,
                _EXPECTED_COLUMNS_V4,
                _EXPECTED_SCHEMA_SQL_V4,
            )
            _migrate_schema_v4_to_v5(connection)
        elif version != _SCHEMA_VERSION:
            raise _error("schema_incompatible")

        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
        )
        if connection.execute("PRAGMA user_version").fetchone()[0] != 5:
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
                ", ".join(_EVIDENCE_COLUMNS_V2),
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
            connection, _EXPECTED_COLUMNS_V2, _EXPECTED_SCHEMA_SQL_V2
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except Exception:
        _rollback_safely(connection)
        raise


def _migrate_schema_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "ALTER TABLE evidence_records RENAME TO evidence_records_v2"
        )
        connection.execute(
            "ALTER TABLE github_source_snapshots "
            "RENAME TO github_source_snapshots_v2"
        )
        connection.execute(
            "ALTER TABLE collection_attempts RENAME TO collection_attempts_v2"
        )
        connection.execute(_SCHEMA_V3_STATEMENTS[1])
        connection.execute(_SCHEMA_V3_STATEMENTS[2])
        connection.execute(_SCHEMA_V3_STATEMENTS[3])

        connection.execute(
            "INSERT INTO collection_attempts ({0}) "
            "SELECT {0} FROM collection_attempts_v2".format(
                ", ".join(_ATTEMPT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO github_source_snapshots ({0}) "
            "SELECT {0} FROM github_source_snapshots_v2".format(
                ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO evidence_records ({0}) "
            "SELECT {1}, NULL, {2} FROM evidence_records_v2".format(
                ", ".join(_EVIDENCE_COLUMNS_V3),
                ", ".join(_EVIDENCE_COLUMNS_V2[:18]),
                ", ".join(_EVIDENCE_COLUMNS_V2[18:]),
            )
        )

        for old_table, new_table, columns in (
            (
                "collection_attempts_v2",
                "collection_attempts",
                _ATTEMPT_COLUMNS,
            ),
            (
                "github_source_snapshots_v2",
                "github_source_snapshots",
                _SOURCE_SNAPSHOT_COLUMNS,
            ),
            (
                "evidence_records_v2",
                "evidence_records",
                _EVIDENCE_COLUMNS_V2,
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
        connection.execute("DROP TABLE evidence_records_v2")
        connection.execute("DROP TABLE github_source_snapshots_v2")
        connection.execute("DROP TABLE collection_attempts_v2")
        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS_V3, _EXPECTED_SCHEMA_SQL_V3
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    except Exception:
        _rollback_safely(connection)
        raise


def _migrate_schema_v3_to_v4(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "ALTER TABLE evidence_records RENAME TO evidence_records_v3"
        )
        connection.execute(
            "ALTER TABLE github_source_snapshots "
            "RENAME TO github_source_snapshots_v3"
        )
        connection.execute(
            "ALTER TABLE collection_attempts RENAME TO collection_attempts_v3"
        )
        connection.execute(_SCHEMA_V4_STATEMENTS[1])
        connection.execute(_SCHEMA_V4_STATEMENTS[2])
        connection.execute(_SCHEMA_V4_STATEMENTS[3])
        connection.execute(_SCHEMA_V4_STATEMENTS[4])

        connection.execute(
            "INSERT INTO collection_attempts ({0}) "
            "SELECT {0} FROM collection_attempts_v3".format(
                ", ".join(_ATTEMPT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO github_source_snapshots ({0}) "
            "SELECT {0} FROM github_source_snapshots_v3".format(
                ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
            )
        )
        connection.execute(
            "INSERT INTO evidence_records ({0}) "
            "SELECT {1}, NULL, {2} FROM evidence_records_v3".format(
                ", ".join(_EVIDENCE_COLUMNS),
                ", ".join(_EVIDENCE_COLUMNS_V3[:19]),
                ", ".join(_EVIDENCE_COLUMNS_V3[19:]),
            )
        )

        for old_table, new_table, columns in (
            (
                "collection_attempts_v3",
                "collection_attempts",
                _ATTEMPT_COLUMNS,
            ),
            (
                "github_source_snapshots_v3",
                "github_source_snapshots",
                _SOURCE_SNAPSHOT_COLUMNS,
            ),
            (
                "evidence_records_v3",
                "evidence_records",
                _EVIDENCE_COLUMNS_V3,
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
        connection.execute("DROP TABLE evidence_records_v3")
        connection.execute("DROP TABLE github_source_snapshots_v3")
        connection.execute("DROP TABLE collection_attempts_v3")
        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS_V4, _EXPECTED_SCHEMA_SQL_V4
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
    except Exception:
        _rollback_safely(connection)
        raise


def _migrate_schema_v4_to_v5(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        preserved_rows = {}
        for table_name, columns in _EXPECTED_COLUMNS_V4.items():
            selected = ", ".join(columns)
            primary_key = columns[0]
            preserved_rows[table_name] = [
                tuple(row)
                for row in connection.execute(
                    "SELECT {} FROM {} ORDER BY {}".format(
                        selected, table_name, primary_key
                    )
                ).fetchall()
            ]

        connection.execute(_SCHEMA_V5_STATEMENTS[-2])
        connection.execute(_SCHEMA_V5_STATEMENTS[-1])

        for table_name, columns in _EXPECTED_COLUMNS_V4.items():
            selected = ", ".join(columns)
            primary_key = columns[0]
            migrated_rows = [
                tuple(row)
                for row in connection.execute(
                    "SELECT {} FROM {} ORDER BY {}".format(
                        selected, table_name, primary_key
                    )
                ).fetchall()
            ]
            if migrated_rows != preserved_rows[table_name]:
                raise _error("schema_incompatible")

        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        _verify_schema_definition(
            connection, _EXPECTED_COLUMNS, _EXPECTED_SCHEMA_SQL
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _error("schema_incompatible")
        connection.execute("PRAGMA user_version = 5")
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


def _validated_latest_commit_collection_result(
    collection_result: object,
) -> GitHubLatestCommitCollectionResult:
    if type(collection_result) is not GitHubLatestCommitCollectionResult:
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
        reconstructed = GitHubLatestCommitCollectionResult(
            request=reconstructed_request,
            outcome=collection_result.outcome,
            evidence_kind=collection_result.evidence_kind,
            collector_version=collection_result.collector_version,
            source_identity=collection_result.source_identity,
            commit_sha=collection_result.commit_sha,
            latest_commit_at=collection_result.latest_commit_at,
            source_timestamp=collection_result.source_timestamp,
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


def _validated_security_policy_collection_result(
    collection_result: object,
) -> GitHubSecurityPolicyPresenceCollectionResult:
    if type(collection_result) is not GitHubSecurityPolicyPresenceCollectionResult:
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
        reconstructed_observations = []
        for observation in collection_result.observations:
            observation_error = observation.error
            reconstructed_observation_error = None
            if observation_error is not None:
                reconstructed_observation_error = (
                    GitHubRepositoryMetadataCollectionError(
                        category=observation_error.category,
                        retryability=observation_error.retryability,
                        message=observation_error.message,
                        retry_after=observation_error.retry_after,
                    )
                )
            reconstructed_observations.append(
                GitHubSecurityPolicySourceObservation(
                    sequence=observation.sequence,
                    role=observation.role,
                    source_identity=observation.source_identity,
                    response_status=observation.response_status,
                    source_object_id=observation.source_object_id,
                    raw_response_bytes=observation.raw_response_bytes,
                    raw_snapshot=observation.raw_snapshot,
                    integrity_digest=observation.integrity_digest,
                    response_etag=observation.response_etag,
                    error=reconstructed_observation_error,
                )
            )
        result_error = collection_result.error
        reconstructed_result_error = None
        if result_error is not None:
            reconstructed_result_error = GitHubRepositoryMetadataCollectionError(
                category=result_error.category,
                retryability=result_error.retryability,
                message=result_error.message,
                retry_after=result_error.retry_after,
            )
        reconstructed = GitHubSecurityPolicyPresenceCollectionResult(
            request=reconstructed_request,
            outcome=collection_result.outcome,
            evidence_kind=collection_result.evidence_kind,
            collector_version=collection_result.collector_version,
            source_identity=collection_result.source_identity,
            repository_source_id=collection_result.repository_source_id,
            security_policy_present=collection_result.security_policy_present,
            policy_scope=collection_result.policy_scope,
            policy_path=collection_result.policy_path,
            policy_blob_sha=collection_result.policy_blob_sha,
            observations=tuple(reconstructed_observations),
            response_status=collection_result.response_status,
            error=reconstructed_result_error,
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


def _security_sequence_identifier(
    namespace: str,
    prefix: str,
    request: GitHubRepositoryMetadataCollectionInput,
    sequence: int,
) -> str:
    material = "\0".join(
        (
            namespace,
            request.assessment_id,
            EvidenceKind.SECURITY_POLICY_PRESENT.value,
            request.collection_attempt_id,
            str(sequence),
        )
    ).encode("utf-8")
    return prefix + hashlib.sha256(material).hexdigest()


def _security_observation_id(
    request: GitHubRepositoryMetadataCollectionInput,
    sequence: int,
) -> str:
    return _security_sequence_identifier(
        _SECURITY_OBSERVATION_NAMESPACE,
        _SECURITY_OBSERVATION_PREFIX,
        request,
        sequence,
    )


def _security_source_snapshot_id(
    request: GitHubRepositoryMetadataCollectionInput,
    sequence: int,
) -> str:
    return _security_sequence_identifier(
        _SOURCE_SNAPSHOT_NAMESPACE,
        _SOURCE_SNAPSHOT_PREFIX,
        request,
        sequence,
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
    elif evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
        namespace = _LATEST_COMMIT_EVIDENCE_NAMESPACE
        prefix = _LATEST_COMMIT_EVIDENCE_PREFIX
    elif evidence_kind is EvidenceKind.SECURITY_POLICY_PRESENT:
        namespace = _SECURITY_POLICY_EVIDENCE_NAMESPACE
        prefix = _SECURITY_POLICY_EVIDENCE_PREFIX
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


def _latest_commit_expected_evidence(
    collection_result: GitHubLatestCommitCollectionResult,
) -> Optional[EvidenceRecord]:
    request = collection_result.request
    if collection_result.outcome is GitHubCollectionOutcome.AVAILABLE:
        if (
            not isinstance(collection_result.latest_commit_at, datetime)
            or collection_result.integrity_digest is None
            or collection_result.commit_sha is None
            or collection_result.source_timestamp is None
        ):
            raise _error("verification_failed")
        snapshot_id = _source_snapshot_id(
            request, EvidenceKind.LATEST_COMMIT_TIMESTAMP
        )
        provenance = (
            ("source_snapshot_id", snapshot_id),
            (
                "source_snapshot_integrity_digest",
                collection_result.integrity_digest,
            ),
            ("commit_sha", collection_result.commit_sha),
            ("source_committer_date", collection_result.source_timestamp),
        )
        compact_snapshot = json.dumps(
            {"value": collection_result.latest_commit_at.isoformat()},
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.LATEST_COMMIT_TIMESTAMP
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                source_identity=collection_result.source_identity,
                collector_name=_LATEST_COMMIT_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.AVAILABLE,
                freshness_basis="collection_time",
                freshness_status_at_collection=FreshnessStatus.CURRENT,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                value=collection_result.latest_commit_at,
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
        reason = collection_result.error.category
        provenance = (("collection_error_category", reason),)
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.LATEST_COMMIT_TIMESTAMP
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                source_identity=collection_result.source_identity,
                collector_name=_LATEST_COMMIT_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.UNAVAILABLE,
                freshness_basis="unknown",
                freshness_status_at_collection=FreshnessStatus.UNKNOWN,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                unavailability_reason=reason,
                error_category=reason,
            )
        except ValueError:
            raise _error("verification_failed") from None
    return None


def _latest_commit_source_snapshot_values(
    collection_result: GitHubLatestCommitCollectionResult,
) -> Tuple[object, ...]:
    if (
        collection_result.raw_snapshot is None
        or collection_result.integrity_digest is None
        or collection_result.commit_sha is None
    ):
        raise _error("verification_failed")
    return (
        _source_snapshot_id(
            collection_result.request,
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        ),
        collection_result.request.collection_attempt_id,
        sqlite3.Binary(collection_result.raw_snapshot.encode("utf-8")),
        "utf-8",
        "application/json",
        collection_result.integrity_digest,
        collection_result.commit_sha,
        collection_result.response_etag,
    )


def _security_policy_expected_evidence(
    collection_result: GitHubSecurityPolicyPresenceCollectionResult,
) -> Optional[EvidenceRecord]:
    request = collection_result.request
    observation_provenance = []
    for observation in collection_result.observations:
        prefix = "observation_{:02d}".format(observation.sequence)
        observation_provenance.extend(
            (
                (prefix + "_id", _security_observation_id(request, observation.sequence)),
                (prefix + "_role", observation.role),
                (prefix + "_source_identity", observation.source_identity),
                (
                    prefix + "_status",
                    str(observation.response_status)
                    if observation.response_status is not None
                    else "none",
                ),
            )
        )
        if observation.integrity_digest is not None:
            observation_provenance.append(
                (prefix + "_digest", observation.integrity_digest)
            )
    if collection_result.outcome is GitHubCollectionOutcome.AVAILABLE:
        if (
            type(collection_result.security_policy_present) is not bool
            or collection_result.repository_source_id is None
        ):
            raise _error("verification_failed")
        decisive = (
            collection_result.observations[-1]
            if collection_result.security_policy_present
            else collection_result.observations[0]
        )
        if decisive.raw_snapshot is None:
            raise _error("verification_failed")
        snapshot_id = _security_source_snapshot_id(
            request, decisive.sequence
        )
        provenance = (
            ("source_snapshot_id", snapshot_id),
            ("repository_source_id", collection_result.repository_source_id),
            ("observation_count", str(len(collection_result.observations))),
            *observation_provenance,
        )
        if collection_result.security_policy_present:
            if (
                collection_result.policy_scope is None
                or collection_result.policy_path is None
                or collection_result.policy_blob_sha is None
            ):
                raise _error("verification_failed")
            provenance = (
                *provenance,
                ("policy_scope", collection_result.policy_scope),
                ("policy_path", collection_result.policy_path),
                ("policy_blob_sha", collection_result.policy_blob_sha),
            )
        compact_snapshot = json.dumps(
            {"value": collection_result.security_policy_present},
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.SECURITY_POLICY_PRESENT
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.SECURITY_POLICY_PRESENT,
                source_identity=collection_result.source_identity,
                collector_name=_SECURITY_POLICY_COLLECTOR_NAME,
                collector_version=collection_result.collector_version,
                collection_attempt_id=request.collection_attempt_id,
                attempt_number=request.attempt_number,
                attempted_at=request.attempted_at,
                collection_outcome=EvidenceOutcome.AVAILABLE,
                freshness_basis="collection_time",
                freshness_status_at_collection=FreshnessStatus.CURRENT,
                evidence_schema_version=_EVIDENCE_SCHEMA_VERSION,
                provenance=provenance,
                value=collection_result.security_policy_present,
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
            ("observation_count", str(len(collection_result.observations))),
            *observation_provenance,
        )
        try:
            return EvidenceRecord(
                evidence_id=_evidence_id(
                    request, EvidenceKind.SECURITY_POLICY_PRESENT
                ),
                assessment_id=request.assessment_id,
                evidence_kind=EvidenceKind.SECURITY_POLICY_PRESENT,
                source_identity=collection_result.source_identity,
                collector_name=_SECURITY_POLICY_COLLECTOR_NAME,
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


def _security_policy_attempt_values(
    collection_result: GitHubSecurityPolicyPresenceCollectionResult,
) -> Tuple[object, ...]:
    request = collection_result.request
    error = collection_result.error
    terminal = collection_result.observations[-1]
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
        terminal.response_etag
        if collection_result.outcome is GitHubCollectionOutcome.AVAILABLE
        else None,
        error.category if error is not None else None,
        error.retryability if error is not None else None,
        error.message if error is not None else None,
        error.retry_after if error is not None else None,
    )


def _security_policy_snapshot_values(
    request: GitHubRepositoryMetadataCollectionInput,
    observation: GitHubSecurityPolicySourceObservation,
) -> Tuple[object, ...]:
    if (
        observation.raw_response_bytes is None
        or observation.integrity_digest is None
    ):
        raise _error("verification_failed")
    return (
        _security_source_snapshot_id(request, observation.sequence),
        request.collection_attempt_id,
        sqlite3.Binary(observation.raw_response_bytes),
        "utf-8" if observation.raw_snapshot is not None else "binary",
        "application/json",
        observation.integrity_digest,
        observation.source_object_id,
        observation.response_etag,
    )


def _security_policy_observation_values(
    request: GitHubRepositoryMetadataCollectionInput,
    observation: GitHubSecurityPolicySourceObservation,
) -> Tuple[object, ...]:
    return (
        _security_observation_id(request, observation.sequence),
        request.collection_attempt_id,
        observation.sequence,
        observation.role,
        observation.source_identity,
        observation.response_status,
        observation.response_etag,
        observation.error.category if observation.error is not None else None,
        _security_source_snapshot_id(request, observation.sequence)
        if observation.raw_response_bytes is not None
        else None,
    )


def _security_policy_evidence_values(
    evidence: EvidenceRecord,
) -> Tuple[object, ...]:
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
        _SECURITY_POLICY_NORMALIZATION_VERSION,
        _canonical_provenance_json(evidence.provenance),
        evidence.provenance[0][1] if is_available else None,
        None,
        None,
        None,
        int(evidence.value) if is_available else None,
        evidence.raw_snapshot,
        evidence.integrity_digest,
        evidence.unavailability_reason,
        evidence.error_category,
    )


def _latest_commit_evidence_values(
    evidence: EvidenceRecord,
) -> Tuple[object, ...]:
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
        _LATEST_COMMIT_NORMALIZATION_VERSION,
        _canonical_provenance_json(evidence.provenance),
        evidence.provenance[0][1] if is_available else None,
        None,
        None,
        evidence.value.isoformat() if is_available else None,
        None,
        evidence.raw_snapshot,
        evidence.integrity_digest,
        evidence.unavailability_reason,
        evidence.error_category,
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
        None,
        None,
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
        None,
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
        else _LATEST_COMMIT_NORMALIZATION_VERSION
        if evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP
        else _SECURITY_POLICY_NORMALIZATION_VERSION
        if evidence_kind is EvidenceKind.SECURITY_POLICY_PRESENT
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
                or row["latest_commit_timestamp_value"] is not None
                or row["security_policy_present_value"] is not None
            ):
                raise ValueError("stored archived value is invalid")
            value = bool(archived_value)
        elif evidence_kind is EvidenceKind.LICENSE_STATUS:
            if (
                row["archived_value"] is not None
                or row["latest_commit_timestamp_value"] is not None
                or row["security_policy_present_value"] is not None
            ):
                raise ValueError("stored license value is invalid")
            value = LicenseStatus(row["license_status_value"])
        elif evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
            if (
                row["archived_value"] is not None
                or row["license_status_value"] is not None
                or row["security_policy_present_value"] is not None
            ):
                raise ValueError("stored latest commit value is invalid")
            value = _parse_stored_datetime(
                row["latest_commit_timestamp_value"]
            )
        elif evidence_kind is EvidenceKind.SECURITY_POLICY_PRESENT:
            security_value = row["security_policy_present_value"]
            if (
                type(security_value) is not int
                or security_value not in (0, 1)
                or row["archived_value"] is not None
                or row["license_status_value"] is not None
                or row["latest_commit_timestamp_value"] is not None
            ):
                raise ValueError("stored security policy value is invalid")
            value = bool(security_value)
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


def _latest_commit_collection_result_from_rows(
    attempt: sqlite3.Row,
    snapshots: Tuple[sqlite3.Row, ...],
    evidence_rows: Tuple[sqlite3.Row, ...],
) -> GitHubLatestCommitCollectionResult:
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

    commit_sha = None
    latest_commit_at = None
    source_timestamp = None
    raw_snapshot = None
    integrity_digest = None
    if outcome is GitHubCollectionOutcome.AVAILABLE:
        if len(snapshots) != 1:
            raise ValueError("available attempt requires one source snapshot")
        if len(evidence_rows) != 1:
            raise ValueError("available attempt requires one evidence row")
        snapshot = snapshots[0]
        evidence_row = evidence_rows[0]
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
            != _source_snapshot_id(
                request, EvidenceKind.LATEST_COMMIT_TIMESTAMP
            )
        ):
            raise ValueError("source snapshot verification failed")
        payload = json.loads(raw_snapshot)
        if type(payload) is not list or len(payload) != 1:
            raise ValueError("source payload cannot supply latest commit")
        item = payload[0]
        if type(item) is not dict or type(item.get("commit")) is not dict:
            raise ValueError("source payload cannot supply latest commit")
        committer = item["commit"].get("committer")
        if type(committer) is not dict:
            raise ValueError("source payload cannot supply committer date")
        commit_sha = snapshot["repository_source_id"]
        if item.get("sha") != commit_sha:
            raise ValueError("source commit ID does not match snapshot")
        source_timestamp = committer.get("date")
        if type(source_timestamp) is not str:
            raise ValueError("source committer date is invalid")
        parsed_timestamp = (
            source_timestamp[:-1] + "+00:00"
            if source_timestamp.endswith("Z")
            else source_timestamp
        )
        source_commit_at = datetime.fromisoformat(parsed_timestamp)
        latest_commit_at = _parse_stored_datetime(
            evidence_row["latest_commit_timestamp_value"]
        )
        if source_commit_at.astimezone(
            timezone.utc
        ) != latest_commit_at.astimezone(timezone.utc):
            raise ValueError(
                "stored latest commit value does not match source instant"
            )
        integrity_digest = snapshot["integrity_digest"]
    elif snapshots:
        raise ValueError("nonavailable attempt cannot have a source snapshot")

    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind(attempt["evidence_kind"]),
        collector_version=attempt["collector_version"],
        source_identity=attempt["source_identity"],
        commit_sha=commit_sha,
        latest_commit_at=latest_commit_at,
        source_timestamp=source_timestamp,
        raw_snapshot=raw_snapshot,
        integrity_digest=integrity_digest,
        response_status=attempt["response_status"],
        response_etag=attempt["response_etag"],
        error=error,
    )


def _verify_latest_commit_collection_after_reopen(
    filename: str,
    collection_attempt_id: str,
) -> Tuple[GitHubLatestCommitCollectionResult, Optional[EvidenceRecord]]:
    connection = _connect(filename)
    try:
        attempt_rows = connection.execute(
            "SELECT {} FROM collection_attempts "
            "WHERE collection_attempt_id = ?".format(
                ", ".join(_ATTEMPT_COLUMNS)
            ),
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
                "SELECT {} FROM github_source_snapshots "
                "WHERE collection_attempt_id = ?".format(
                    ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
                ),
                (collection_attempt_id,),
            ).fetchall()
        )
        evidence_rows = tuple(
            connection.execute(
                "SELECT {} FROM evidence_records "
                "WHERE collection_attempt_id = ?".format(
                    ", ".join(_EVIDENCE_COLUMNS)
                ),
                (collection_attempt_id,),
            ).fetchall()
        )

        reconstructed_result = _latest_commit_collection_result_from_rows(
            attempt, snapshot_rows, evidence_rows
        )
        if _attempt_values(reconstructed_result) != _row_values(
            attempt, _ATTEMPT_COLUMNS
        ):
            raise ValueError("collection attempt does not reconstruct exactly")

        expected_evidence = _latest_commit_expected_evidence(
            reconstructed_result
        )
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
                or _latest_commit_evidence_values(evidence)
                != _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
            ):
                raise ValueError("evidence does not reconstruct exactly")

        if reconstructed_result.outcome is GitHubCollectionOutcome.AVAILABLE:
            expected_snapshot = _latest_commit_source_snapshot_values(
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


def _security_policy_collection_result_from_rows(
    attempt: sqlite3.Row,
    observation_rows: Tuple[sqlite3.Row, ...],
    snapshot_rows: Tuple[sqlite3.Row, ...],
) -> GitHubSecurityPolicyPresenceCollectionResult:
    request = GitHubRepositoryMetadataCollectionInput(
        assessment_id=attempt["assessment_id"],
        repository_identity=attempt["repository_identity"],
        collection_attempt_id=attempt["collection_attempt_id"],
        attempt_number=attempt["attempt_number"],
        attempted_at=_parse_stored_datetime(attempt["attempted_at"]),
    )
    snapshot_by_id = {}
    for snapshot in snapshot_rows:
        snapshot_id = snapshot["source_snapshot_id"]
        if snapshot_id in snapshot_by_id:
            raise ValueError("duplicate security source snapshot")
        response_bytes = snapshot["response_bytes"]
        if type(response_bytes) is not bytes:
            raise ValueError("security source response must be bytes")
        try:
            response_bytes.decode("utf-8")
            expected_encoding = "utf-8"
        except UnicodeDecodeError:
            expected_encoding = "binary"
        if (
            snapshot["encoding"] != expected_encoding
            or snapshot["media_type"] != "application/json"
            or snapshot["integrity_digest"]
            != hashlib.sha256(response_bytes).hexdigest()
        ):
            raise ValueError("security source snapshot verification failed")
        snapshot_by_id[snapshot_id] = snapshot

    result_error = None
    if attempt["error_category"] is not None:
        result_error = GitHubRepositoryMetadataCollectionError(
            category=attempt["error_category"],
            retryability=attempt["error_retryability"],
            message=attempt["error_message"],
            retry_after=attempt["retry_after"],
        )
    observations = []
    referenced_snapshot_ids = set()
    for row in observation_rows:
        sequence = row["request_sequence"]
        if row["source_observation_id"] != _security_observation_id(
            request, sequence
        ):
            raise ValueError("security observation identity is invalid")
        snapshot_id = row["source_snapshot_id"]
        raw_response_bytes = None
        raw_snapshot = None
        integrity_digest = None
        source_object_id = None
        if snapshot_id is not None:
            if snapshot_id != _security_source_snapshot_id(request, sequence):
                raise ValueError("security snapshot identity is invalid")
            snapshot = snapshot_by_id.get(snapshot_id)
            if snapshot is None:
                raise ValueError("security observation snapshot is missing")
            referenced_snapshot_ids.add(snapshot_id)
            raw_response_bytes = snapshot["response_bytes"]
            try:
                raw_snapshot = raw_response_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raw_snapshot = None
            integrity_digest = snapshot["integrity_digest"]
            source_object_id = snapshot["repository_source_id"]
            if snapshot["response_etag"] != row["response_etag"]:
                raise ValueError("security observation ETag is inconsistent")
        observation_error = None
        if row["error_category"] is not None:
            if result_error is None or row["error_category"] != result_error.category:
                raise ValueError("security observation error is inconsistent")
            observation_error = result_error
        observations.append(
            GitHubSecurityPolicySourceObservation(
                sequence=sequence,
                role=row["source_role"],
                source_identity=row["source_identity"],
                response_status=row["response_status"],
                source_object_id=source_object_id,
                raw_response_bytes=raw_response_bytes,
                raw_snapshot=raw_snapshot,
                integrity_digest=integrity_digest,
                response_etag=row["response_etag"],
                error=observation_error,
            )
        )
    if referenced_snapshot_ids != set(snapshot_by_id):
        raise ValueError("unreferenced security source snapshot")
    observation_tuple = tuple(observations)
    if not observation_tuple:
        raise ValueError("security attempt requires observations")
    outcome = GitHubCollectionOutcome(attempt["outcome"])
    repository_source_id = observation_tuple[0].source_object_id
    security_policy_present = None
    policy_scope = None
    policy_path = None
    policy_blob_sha = None
    if outcome is GitHubCollectionOutcome.AVAILABLE:
        terminal = observation_tuple[-1]
        security_policy_present = terminal.response_status == 200
        if security_policy_present:
            policy_scope = (
                "repository_local"
                if terminal.role.startswith("target_")
                else "inherited_default"
            )
            policy_path = {
                "target_dotgithub": ".github/SECURITY.md",
                "target_root": "SECURITY.md",
                "target_docs": "docs/SECURITY.md",
                "default_dotgithub": ".github/SECURITY.md",
                "default_root": "SECURITY.md",
                "default_docs": "docs/SECURITY.md",
            }.get(terminal.role)
            policy_blob_sha = terminal.source_object_id
    return GitHubSecurityPolicyPresenceCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind(attempt["evidence_kind"]),
        collector_version=attempt["collector_version"],
        source_identity=attempt["source_identity"],
        repository_source_id=repository_source_id,
        security_policy_present=security_policy_present,
        policy_scope=policy_scope,
        policy_path=policy_path,
        policy_blob_sha=policy_blob_sha,
        observations=observation_tuple,
        response_status=attempt["response_status"],
        error=result_error,
    )


def _verify_security_policy_collection_after_reopen(
    filename: str,
    collection_attempt_id: str,
) -> Tuple[
    GitHubSecurityPolicyPresenceCollectionResult,
    Optional[EvidenceRecord],
]:
    connection = _connect(filename)
    try:
        attempt_rows = connection.execute(
            "SELECT {} FROM collection_attempts "
            "WHERE collection_attempt_id = ?".format(
                ", ".join(_ATTEMPT_COLUMNS)
            ),
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
                "security collection repository does not match request"
            )
        observation_rows = tuple(
            connection.execute(
                "SELECT {} FROM github_source_observations "
                "WHERE collection_attempt_id = ? ORDER BY request_sequence".format(
                    ", ".join(_SOURCE_OBSERVATION_COLUMNS)
                ),
                (collection_attempt_id,),
            ).fetchall()
        )
        snapshot_rows = tuple(
            connection.execute(
                "SELECT {} FROM github_source_snapshots "
                "WHERE collection_attempt_id = ? ORDER BY source_snapshot_id".format(
                    ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
                ),
                (collection_attempt_id,),
            ).fetchall()
        )
        evidence_rows = tuple(
            connection.execute(
                "SELECT {} FROM evidence_records "
                "WHERE collection_attempt_id = ?".format(
                    ", ".join(_EVIDENCE_COLUMNS)
                ),
                (collection_attempt_id,),
            ).fetchall()
        )
        reconstructed = _security_policy_collection_result_from_rows(
            attempt, observation_rows, snapshot_rows
        )
        if _security_policy_attempt_values(reconstructed) != _row_values(
            attempt, _ATTEMPT_COLUMNS
        ):
            raise ValueError("security attempt does not reconstruct exactly")
        for observation, row in zip(reconstructed.observations, observation_rows):
            if _security_policy_observation_values(
                reconstructed.request, observation
            ) != _row_values(row, _SOURCE_OBSERVATION_COLUMNS):
                raise ValueError("security observation does not reconstruct")
            if observation.raw_response_bytes is not None:
                expected_snapshot = _security_policy_snapshot_values(
                    reconstructed.request, observation
                )
                matching = [
                    snapshot
                    for snapshot in snapshot_rows
                    if snapshot["source_snapshot_id"]
                    == expected_snapshot[0]
                ]
                if (
                    len(matching) != 1
                    or _row_values(matching[0], _SOURCE_SNAPSHOT_COLUMNS)
                    != tuple(expected_snapshot)
                ):
                    raise ValueError("security snapshot does not reconstruct")

        expected_evidence = _security_policy_expected_evidence(reconstructed)
        if expected_evidence is None:
            if evidence_rows:
                raise ValueError("failed security attempt cannot have evidence")
            evidence = None
        else:
            if len(evidence_rows) != 1:
                raise ValueError("security outcome requires one evidence row")
            evidence = _evidence_from_row(evidence_rows[0])
            if (
                evidence != expected_evidence
                or _security_policy_evidence_values(evidence)
                != _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
            ):
                raise ValueError("security evidence does not reconstruct")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key verification failed")
        return reconstructed, evidence
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


def persist_github_latest_commit_collection(
    database_path: _DatabasePath,
    collection_result: GitHubLatestCommitCollectionResult,
) -> Optional[EvidenceRecord]:
    """Persist one terminal latest-commit outcome and return verified evidence."""

    filename = _database_filename(database_path)
    expected_result = _validated_latest_commit_collection_result(
        collection_result
    )
    try:
        expected_evidence = _latest_commit_expected_evidence(expected_result)
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
            "SELECT {} FROM collection_attempts "
            "WHERE collection_attempt_id = ?".format(
                ", ".join(_ATTEMPT_COLUMNS)
            ),
            (expected_result.request.collection_attempt_id,),
        ).fetchall()
        if existing_attempts:
            if len(existing_attempts) != 1:
                raise _error("verification_failed")
            replay = True
            _rollback_safely(connection)
        else:
            reused_number = connection.execute(
                "SELECT collection_attempt_id FROM collection_attempts "
                "WHERE assessment_id = ? AND evidence_kind = ? "
                "AND attempt_number = ?",
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
                    _latest_commit_source_snapshot_values(expected_result),
                )
            if expected_evidence is not None:
                _insert_values(
                    connection,
                    "evidence_records",
                    _EVIDENCE_COLUMNS,
                    _latest_commit_evidence_values(expected_evidence),
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

    stored_result, stored_evidence = (
        _verify_latest_commit_collection_after_reopen(
            filename, expected_result.request.collection_attempt_id
        )
    )
    if stored_result != expected_result or stored_evidence != expected_evidence:
        raise _error("conflicting_replay" if replay else "verification_failed")
    if (
        stored_result.request.attempted_at.isoformat()
        != expected_result.request.attempted_at.isoformat()
        or (
            stored_result.source_timestamp
            != expected_result.source_timestamp
        )
    ):
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored_evidence


def persist_github_security_policy_presence_collection(
    database_path: _DatabasePath,
    collection_result: GitHubSecurityPolicyPresenceCollectionResult,
) -> Optional[EvidenceRecord]:
    """Persist one terminal effective-security-policy collection outcome."""

    filename = _database_filename(database_path)
    expected_result = _validated_security_policy_collection_result(
        collection_result
    )
    try:
        expected_evidence = _security_policy_expected_evidence(expected_result)
        expected_attempt_values = _security_policy_attempt_values(
            expected_result
        )
        expected_snapshot_values = tuple(
            _security_policy_snapshot_values(expected_result.request, item)
            for item in expected_result.observations
            if item.raw_response_bytes is not None
        )
        expected_observation_values = tuple(
            _security_policy_observation_values(expected_result.request, item)
            for item in expected_result.observations
        )
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
            "SELECT {} FROM collection_attempts "
            "WHERE collection_attempt_id = ?".format(
                ", ".join(_ATTEMPT_COLUMNS)
            ),
            (expected_result.request.collection_attempt_id,),
        ).fetchall()
        if existing_attempts:
            if len(existing_attempts) != 1:
                raise _error("verification_failed")
            replay = True
            _rollback_safely(connection)
        else:
            reused_number = connection.execute(
                "SELECT collection_attempt_id FROM collection_attempts "
                "WHERE assessment_id = ? AND evidence_kind = ? "
                "AND attempt_number = ?",
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
            for values in expected_snapshot_values:
                _insert_values(
                    connection,
                    "github_source_snapshots",
                    _SOURCE_SNAPSHOT_COLUMNS,
                    values,
                )
            for values in expected_observation_values:
                _insert_values(
                    connection,
                    "github_source_observations",
                    _SOURCE_OBSERVATION_COLUMNS,
                    values,
                )
            if expected_evidence is not None:
                _insert_values(
                    connection,
                    "evidence_records",
                    _EVIDENCE_COLUMNS,
                    _security_policy_evidence_values(expected_evidence),
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

    stored_result, stored_evidence = (
        _verify_security_policy_collection_after_reopen(
            filename, expected_result.request.collection_attempt_id
        )
    )
    if stored_result != expected_result or stored_evidence != expected_evidence:
        raise _error("conflicting_replay" if replay else "verification_failed")
    if (
        stored_result.request.attempted_at.isoformat()
        != expected_result.request.attempted_at.isoformat()
    ):
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored_evidence


def _verified_evidence_from_connection(
    connection: sqlite3.Connection,
    evidence_row: sqlite3.Row,
    validation_result: AssessmentRequestValidationResult,
) -> EvidenceRecord:
    evidence_kind = EvidenceKind(evidence_row["evidence_kind"])
    attempt_rows = connection.execute(
        "SELECT {} FROM collection_attempts "
        "WHERE collection_attempt_id = ?".format(
            ", ".join(_ATTEMPT_COLUMNS)
        ),
        (evidence_row["collection_attempt_id"],),
    ).fetchall()
    if len(attempt_rows) != 1:
        raise ValueError("evidence collection attempt is not unique")
    attempt = attempt_rows[0]
    if (
        attempt["assessment_id"]
        != validation_result.request.assessment_id
        or attempt["assessment_id"] != evidence_row["assessment_id"]
        or attempt["evidence_kind"] != evidence_kind.value
        or attempt["repository_identity"]
        != validation_result.normalized_repository_identity
    ):
        raise ValueError("evidence relationship does not match request")

    snapshot_rows = tuple(
        connection.execute(
            "SELECT {} FROM github_source_snapshots "
            "WHERE collection_attempt_id = ? ORDER BY source_snapshot_id".format(
                ", ".join(_SOURCE_SNAPSHOT_COLUMNS)
            ),
            (attempt["collection_attempt_id"],),
        ).fetchall()
    )
    observation_rows = tuple(
        connection.execute(
            "SELECT {} FROM github_source_observations "
            "WHERE collection_attempt_id = ? ORDER BY request_sequence".format(
                ", ".join(_SOURCE_OBSERVATION_COLUMNS)
            ),
            (attempt["collection_attempt_id"],),
        ).fetchall()
    )
    evidence_rows = tuple(
        connection.execute(
            "SELECT {} FROM evidence_records "
            "WHERE collection_attempt_id = ?".format(
                ", ".join(_EVIDENCE_COLUMNS)
            ),
            (attempt["collection_attempt_id"],),
        ).fetchall()
    )
    if (
        len(evidence_rows) != 1
        or _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
        != _row_values(evidence_row, _EVIDENCE_COLUMNS)
    ):
        raise ValueError("evidence row does not uniquely match its attempt")

    if evidence_kind is EvidenceKind.REPOSITORY_ARCHIVED:
        if observation_rows:
            raise ValueError("archived evidence has unexpected observations")
        reconstructed = _collection_result_from_rows(
            attempt, snapshot_rows
        )
        expected_attempt = _attempt_values(reconstructed)
        expected_evidence = _expected_evidence(reconstructed)
        evidence_values = _evidence_values
        expected_snapshots = (
            (_source_snapshot_values(reconstructed),)
            if reconstructed.outcome is GitHubCollectionOutcome.AVAILABLE
            else ()
        )
    elif evidence_kind is EvidenceKind.LICENSE_STATUS:
        if observation_rows:
            raise ValueError("license evidence has unexpected observations")
        reconstructed = _license_collection_result_from_rows(
            attempt, snapshot_rows
        )
        expected_attempt = _attempt_values(reconstructed)
        expected_evidence = _license_expected_evidence(reconstructed)
        evidence_values = _license_evidence_values
        expected_snapshots = (
            (_license_source_snapshot_values(reconstructed),)
            if reconstructed.outcome is GitHubCollectionOutcome.AVAILABLE
            else ()
        )
    elif evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
        if observation_rows:
            raise ValueError(
                "latest commit evidence has unexpected observations"
            )
        reconstructed = _latest_commit_collection_result_from_rows(
            attempt, snapshot_rows, evidence_rows
        )
        expected_attempt = _attempt_values(reconstructed)
        expected_evidence = _latest_commit_expected_evidence(reconstructed)
        evidence_values = _latest_commit_evidence_values
        expected_snapshots = (
            (_latest_commit_source_snapshot_values(reconstructed),)
            if reconstructed.outcome is GitHubCollectionOutcome.AVAILABLE
            else ()
        )
    elif evidence_kind is EvidenceKind.SECURITY_POLICY_PRESENT:
        reconstructed = _security_policy_collection_result_from_rows(
            attempt, observation_rows, snapshot_rows
        )
        expected_attempt = _security_policy_attempt_values(reconstructed)
        expected_evidence = _security_policy_expected_evidence(reconstructed)
        evidence_values = _security_policy_evidence_values
        expected_snapshots = tuple(
            _security_policy_snapshot_values(
                reconstructed.request, observation
            )
            for observation in reconstructed.observations
            if observation.raw_response_bytes is not None
        )
        if len(reconstructed.observations) != len(observation_rows):
            raise ValueError("security observations do not reconstruct")
        for observation, row in zip(
            reconstructed.observations, observation_rows
        ):
            if _security_policy_observation_values(
                reconstructed.request, observation
            ) != _row_values(row, _SOURCE_OBSERVATION_COLUMNS):
                raise ValueError("security observation does not reconstruct")
    else:
        raise ValueError("unsupported evidence kind")

    if expected_attempt != _row_values(attempt, _ATTEMPT_COLUMNS):
        raise ValueError("collection attempt does not reconstruct exactly")
    if expected_evidence is None:
        raise ValueError("selected attempt does not produce evidence")
    evidence = _evidence_from_row(evidence_rows[0])
    if (
        evidence != expected_evidence
        or evidence_values(evidence)
        != _row_values(evidence_rows[0], _EVIDENCE_COLUMNS)
    ):
        raise ValueError("evidence does not reconstruct exactly")

    actual_snapshots = tuple(
        _row_values(row, _SOURCE_SNAPSHOT_COLUMNS)
        for row in snapshot_rows
    )
    if actual_snapshots != tuple(sorted(expected_snapshots)):
        raise ValueError("source snapshots do not reconstruct exactly")
    return evidence


def _verified_assessment_evidence_set_from_connection(
    connection: sqlite3.Connection,
    assessment_id: str,
) -> VerifiedAssessmentEvidenceSet:
    _, validation_result = _read_request(connection, assessment_id)
    evidence_rows = tuple(
        connection.execute(
            "SELECT {} FROM evidence_records "
            "WHERE assessment_id = ? "
            "ORDER BY evidence_kind, attempt_number, evidence_id".format(
                ", ".join(_EVIDENCE_COLUMNS)
            ),
            (assessment_id,),
        ).fetchall()
    )
    rows_by_kind = {kind: [] for kind in _VERIFIED_EVIDENCE_KINDS}
    for row in evidence_rows:
        kind = EvidenceKind(row["evidence_kind"])
        if kind not in rows_by_kind:
            raise ValueError("unsupported evidence kind")
        rows_by_kind[kind].append(row)
    if any(len(rows_by_kind[kind]) > 1 for kind in _VERIFIED_EVIDENCE_KINDS):
        raise _error("evidence_set_ambiguous")
    if any(not rows_by_kind[kind] for kind in _VERIFIED_EVIDENCE_KINDS):
        raise _error("evidence_set_incomplete")

    verified_records = tuple(
        _verified_evidence_from_connection(
            connection, rows_by_kind[kind][0], validation_result
        )
        for kind in _VERIFIED_EVIDENCE_KINDS
    )
    return VerifiedAssessmentEvidenceSet(
        validation_result=validation_result,
        evidence_records=verified_records,
    )


def load_verified_assessment_evidence(
    database_path: _DatabasePath,
    assessment_id: str,
) -> VerifiedAssessmentEvidenceSet:
    """Load one complete authoritative evidence set without modifying SQLite."""

    filename = _database_filename(database_path)
    _validate_record_identifier("assessment_id", assessment_id)

    connection = _connect_read_only_v5(filename)
    try:
        verified_set = _verified_assessment_evidence_set_from_connection(
            connection, assessment_id
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key verification failed")
    except SQLitePersistenceError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise _error("verification_failed") from None
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _rollback_safely(connection)
        _close_safely(connection)
    return verified_set


def _validate_record_identifier(field_name: str, value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
    ):
        raise _error("invalid_input")
    return value


def _evaluation_snapshot_from_connection(
    connection: sqlite3.Connection,
    assessment_id: str,
):
    from .assessment import (
        ASSESSMENT_EVALUATION_SCHEMA_VERSION,
        build_assessment_evaluation_snapshot,
        evaluate_assessment,
    )

    rows = connection.execute(
        "SELECT {} FROM assessment_evaluation_snapshots "
        "WHERE assessment_id = ?".format(
            ", ".join(_ASSESSMENT_EVALUATION_COLUMNS)
        ),
        (assessment_id,),
    ).fetchall()
    if not rows:
        raise _error("evaluation_not_found")
    if len(rows) != 1:
        raise _error("verification_failed")
    row = rows[0]
    snapshot_json = row["snapshot_json"]
    if type(snapshot_json) is not str:
        raise ValueError("snapshot_json must be text")
    payload = json.loads(snapshot_json)
    expected_keys = {
        "assessment_id",
        "evaluated_at",
        "evaluation_schema_version",
        "evidence_references",
        "metric_results",
        "policy_findings",
    }
    if type(payload) is not dict or set(payload) != expected_keys:
        raise ValueError("evaluation payload shape is invalid")
    if (
        payload["assessment_id"] != assessment_id
        or payload["assessment_id"] != row["assessment_id"]
        or payload["evaluation_schema_version"]
        != ASSESSMENT_EVALUATION_SCHEMA_VERSION
    ):
        raise ValueError("evaluation payload identity is invalid")
    evaluated_at = _parse_stored_datetime(payload["evaluated_at"])
    verified_evidence = _verified_assessment_evidence_set_from_connection(
        connection, assessment_id
    )
    context = verified_evidence.validation_result.context
    if context is None:
        raise ValueError("verified assessment requires context")
    result = evaluate_assessment(
        context, verified_evidence.evidence_records, evaluated_at
    )
    expected = build_assessment_evaluation_snapshot(result)
    if _row_values(row, _ASSESSMENT_EVALUATION_COLUMNS) != (
        expected.assessment_evaluation_id,
        expected.assessment_id,
        expected.snapshot_json,
        expected.integrity_digest,
    ):
        raise ValueError("evaluation snapshot does not reconstruct exactly")
    return expected


def load_verified_assessment_evaluation_snapshot(
    database_path: _DatabasePath,
    assessment_id: str,
):
    """Load and deterministically verify one durable reviewed evaluation."""

    filename = _database_filename(database_path)
    _validate_record_identifier("assessment_id", assessment_id)
    connection = _connect_read_only_v5(filename)
    try:
        snapshot = _evaluation_snapshot_from_connection(
            connection, assessment_id
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key verification failed")
    except SQLitePersistenceError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise _error("verification_failed") from None
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _rollback_safely(connection)
        _close_safely(connection)
    return snapshot


def persist_assessment_evaluation_snapshot(
    database_path: _DatabasePath,
    assessment_result,
):
    """Persist or exactly replay one complete deterministic evaluation."""

    from .assessment import (
        DeterministicAssessmentResult,
        build_assessment_evaluation_snapshot,
        evaluate_assessment,
    )

    if type(assessment_result) is not DeterministicAssessmentResult:
        raise _error("invalid_input")
    filename = _database_filename(database_path)
    try:
        proposed = build_assessment_evaluation_snapshot(assessment_result)
    except (AttributeError, TypeError, ValueError):
        raise _error("invalid_input") from None

    connection = _connect(filename)
    replay = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        verified_evidence = _verified_assessment_evidence_set_from_connection(
            connection, proposed.assessment_id
        )
        context = verified_evidence.validation_result.context
        if context is None:
            raise _error("verification_failed")
        recalculated = evaluate_assessment(
            context,
            verified_evidence.evidence_records,
            proposed.evaluated_at,
        )
        if (
            recalculated != assessment_result
            or build_assessment_evaluation_snapshot(recalculated) != proposed
        ):
            raise _error("invalid_input")

        existing_rows = connection.execute(
            "SELECT assessment_evaluation_id "
            "FROM assessment_evaluation_snapshots WHERE assessment_id = ?",
            (proposed.assessment_id,),
        ).fetchall()
        if existing_rows:
            replay = True
            existing = _evaluation_snapshot_from_connection(
                connection, proposed.assessment_id
            )
            if existing != proposed:
                raise _error("conflicting_replay")
            _rollback_safely(connection)
        else:
            _insert_values(
                connection,
                "assessment_evaluation_snapshots",
                _ASSESSMENT_EVALUATION_COLUMNS,
                (
                    proposed.assessment_evaluation_id,
                    proposed.assessment_id,
                    proposed.snapshot_json,
                    proposed.integrity_digest,
                ),
            )
            connection.commit()
    except SQLitePersistenceError:
        _rollback_safely(connection)
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        _rollback_safely(connection)
        raise _error("verification_failed") from None
    except sqlite3.Error:
        _rollback_safely(connection)
        raise _error("write_failed") from None
    finally:
        _close_safely(connection)

    stored = load_verified_assessment_evaluation_snapshot(
        filename, proposed.assessment_id
    )
    if stored != proposed:
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored


def _canonical_string_tuple_json(values: tuple[str, ...]) -> str:
    return json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parse_canonical_string_tuple_json(value: object) -> tuple[str, ...]:
    if type(value) is not str:
        raise ValueError("stored tuple must be text")
    parsed = json.loads(value)
    if type(parsed) is not list or not all(type(item) is str for item in parsed):
        raise ValueError("stored tuple is invalid")
    result = tuple(parsed)
    if _canonical_string_tuple_json(result) != value:
        raise ValueError("stored tuple is not canonical")
    return result


def _human_decision_identity_payload_bytes(
    *,
    assessment_id: str,
    assessment_evaluation_id: str,
    decision_maker_actor_id: str,
    disposition: HumanDecisionDisposition,
    rationale: str,
    conditions: tuple[str, ...],
    information_requests: tuple[str, ...],
    acknowledged_policy_finding_ids: tuple[str, ...],
    recorded_at: datetime,
    decision_schema_version: str,
) -> bytes:
    payload = {
        "assessment_id": assessment_id,
        "assessment_evaluation_id": assessment_evaluation_id,
        "decision_maker_actor_id": decision_maker_actor_id,
        "disposition": disposition.value,
        "rationale": rationale,
        "conditions": list(conditions),
        "information_requests": list(information_requests),
        "acknowledged_policy_finding_ids": list(
            acknowledged_policy_finding_ids
        ),
        "recorded_at": recorded_at.isoformat(),
        "decision_schema_version": decision_schema_version,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _human_decision_id(identity_payload_bytes: bytes) -> str:
    material = b"human-decision-id.v1\0" + identity_payload_bytes
    return "human-decision-" + hashlib.sha256(material).hexdigest()


def _current_decision_time() -> datetime:
    return datetime.now(timezone.utc)


def _validated_business_text(field_name: str, value: object) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
    ):
        raise _error("invalid_input")
    return value


def _validated_business_tuple(
    field_name: str, values: object
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise _error("invalid_input")
    for value in values:
        _validated_business_text(field_name, value)
    if len(set(values)) != len(values):
        raise _error("invalid_input")
    return values


def _normalized_decision_business_content(
    *,
    assessment_id: object,
    assessment_evaluation_id: object,
    decision_maker_actor_id: object,
    disposition: object,
    rationale: object,
    conditions: object,
    information_requests: object,
    acknowledged_policy_finding_ids: object,
) -> tuple[object, ...]:
    assessment_id = _validated_business_text("assessment_id", assessment_id)
    assessment_evaluation_id = _validated_business_text(
        "assessment_evaluation_id", assessment_evaluation_id
    )
    decision_maker_actor_id = _validated_business_text(
        "decision_maker_actor_id", decision_maker_actor_id
    )
    rationale = _validated_business_text("rationale", rationale)
    if type(disposition) is not HumanDecisionDisposition:
        raise _error("invalid_input")
    conditions = _validated_business_tuple("conditions", conditions)
    information_requests = _validated_business_tuple(
        "information_requests", information_requests
    )
    acknowledged_policy_finding_ids = _validated_business_tuple(
        "acknowledged_policy_finding_ids",
        acknowledged_policy_finding_ids,
    )
    return (
        assessment_id,
        assessment_evaluation_id,
        decision_maker_actor_id,
        disposition,
        rationale,
        conditions,
        information_requests,
        acknowledged_policy_finding_ids,
    )


def _validate_decision_business_content(
    *,
    validation_result: AssessmentRequestValidationResult,
    snapshot,
    assessment_id: object,
    assessment_evaluation_id: object,
    decision_maker_actor_id: object,
    disposition: object,
    rationale: object,
    conditions: object,
    information_requests: object,
    acknowledged_policy_finding_ids: object,
) -> tuple[object, ...]:
    business_content = _normalized_decision_business_content(
        assessment_id=assessment_id,
        assessment_evaluation_id=assessment_evaluation_id,
        decision_maker_actor_id=decision_maker_actor_id,
        disposition=disposition,
        rationale=rationale,
        conditions=conditions,
        information_requests=information_requests,
        acknowledged_policy_finding_ids=(
            acknowledged_policy_finding_ids
        ),
    )
    (
        assessment_id,
        assessment_evaluation_id,
        decision_maker_actor_id,
        disposition,
        rationale,
        conditions,
        information_requests,
        acknowledged_policy_finding_ids,
    ) = business_content
    request = validation_result.request
    if (
        assessment_id != request.assessment_id
        or assessment_id != snapshot.assessment_id
        or assessment_evaluation_id != snapshot.assessment_evaluation_id
        or decision_maker_actor_id
        != request.responsible_reviewer_actor_id
    ):
        raise _error("invalid_input")
    nonpassing_ids = tuple(
        finding.policy_finding_id
        for finding in snapshot.policy_findings
        if finding.outcome is not PolicyOutcome.PASS
    )
    if disposition in (
        HumanDecisionDisposition.APPROVE,
        HumanDecisionDisposition.APPROVE_WITH_CONDITIONS,
    ):
        if acknowledged_policy_finding_ids != nonpassing_ids:
            raise _error("invalid_input")
    elif acknowledged_policy_finding_ids:
        raise _error("invalid_input")
    if disposition is HumanDecisionDisposition.APPROVE:
        if conditions or information_requests:
            raise _error("invalid_input")
    elif disposition is HumanDecisionDisposition.APPROVE_WITH_CONDITIONS:
        if not conditions or information_requests:
            raise _error("invalid_input")
    elif disposition is HumanDecisionDisposition.NEEDS_MORE_INFORMATION:
        if conditions or not information_requests:
            raise _error("invalid_input")
    elif disposition is HumanDecisionDisposition.REJECT:
        if conditions or information_requests:
            raise _error("invalid_input")
    return business_content


def _decision_business_content(decision: HumanDecision) -> tuple[object, ...]:
    return (
        decision.assessment_id,
        decision.assessment_evaluation_id,
        decision.decision_maker_actor_id,
        decision.disposition,
        decision.rationale,
        decision.conditions,
        decision.information_requests,
        decision.acknowledged_policy_finding_ids,
    )


def _human_decision_from_connection(
    connection: sqlite3.Connection,
    assessment_id: str,
) -> HumanDecision:
    rows = connection.execute(
        "SELECT {} FROM human_decisions WHERE assessment_id = ?".format(
            ", ".join(_HUMAN_DECISION_COLUMNS)
        ),
        (assessment_id,),
    ).fetchall()
    if not rows:
        raise _error("decision_not_found")
    if len(rows) != 1:
        raise _error("verification_failed")
    row = rows[0]
    snapshot = _evaluation_snapshot_from_connection(connection, assessment_id)
    _, validation_result = _read_request(connection, assessment_id)
    conditions = _parse_canonical_string_tuple_json(row["conditions_json"])
    information_requests = _parse_canonical_string_tuple_json(
        row["information_requests_json"]
    )
    acknowledgments = _parse_canonical_string_tuple_json(
        row["acknowledged_policy_finding_ids_json"]
    )
    recorded_at = _parse_stored_datetime(row["recorded_at"])
    decision = HumanDecision(
        human_decision_id=row["human_decision_id"],
        assessment_id=row["assessment_id"],
        assessment_evaluation_id=row["assessment_evaluation_id"],
        decision_maker_actor_id=row["decision_maker_actor_id"],
        disposition=HumanDecisionDisposition(row["disposition"]),
        rationale=row["rationale"],
        conditions=conditions,
        information_requests=information_requests,
        acknowledged_policy_finding_ids=acknowledgments,
        recorded_at=recorded_at,
        decision_schema_version=row["decision_schema_version"],
    )
    try:
        _validate_decision_business_content(
            validation_result=validation_result,
            snapshot=snapshot,
            assessment_id=decision.assessment_id,
            assessment_evaluation_id=decision.assessment_evaluation_id,
            decision_maker_actor_id=decision.decision_maker_actor_id,
            disposition=decision.disposition,
            rationale=decision.rationale,
            conditions=decision.conditions,
            information_requests=decision.information_requests,
            acknowledged_policy_finding_ids=(
                decision.acknowledged_policy_finding_ids
            ),
        )
    except SQLitePersistenceError:
        raise ValueError("stored decision business content is invalid") from None
    if recorded_at < snapshot.evaluated_at.astimezone(timezone.utc):
        raise ValueError("recorded_at precedes evaluated_at")
    identity_bytes = _human_decision_identity_payload_bytes(
        assessment_id=decision.assessment_id,
        assessment_evaluation_id=decision.assessment_evaluation_id,
        decision_maker_actor_id=decision.decision_maker_actor_id,
        disposition=decision.disposition,
        rationale=decision.rationale,
        conditions=decision.conditions,
        information_requests=decision.information_requests,
        acknowledged_policy_finding_ids=(
            decision.acknowledged_policy_finding_ids
        ),
        recorded_at=decision.recorded_at,
        decision_schema_version=decision.decision_schema_version,
    )
    if decision.human_decision_id != _human_decision_id(identity_bytes):
        raise ValueError("human decision identity does not verify")
    return decision


def load_verified_human_decision(
    database_path: _DatabasePath,
    assessment_id: str,
) -> HumanDecision:
    """Load one immutable decision only after complete reopen verification."""

    filename = _database_filename(database_path)
    _validate_record_identifier("assessment_id", assessment_id)
    connection = _connect_read_only_v5(filename)
    try:
        decision = _human_decision_from_connection(connection, assessment_id)
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key verification failed")
    except SQLitePersistenceError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise _error("verification_failed") from None
    except sqlite3.Error:
        raise _error("verification_failed") from None
    finally:
        _rollback_safely(connection)
        _close_safely(connection)
    return decision


def persist_human_decision(
    database_path: _DatabasePath,
    *,
    assessment_id: str,
    assessment_evaluation_id: str,
    decision_maker_actor_id: str,
    disposition: HumanDecisionDisposition,
    rationale: str,
    conditions: tuple[str, ...] = (),
    information_requests: tuple[str, ...] = (),
    acknowledged_policy_finding_ids: tuple[str, ...] = (),
) -> HumanDecision:
    """Record or exactly replay the one immutable decision for an assessment."""

    filename = _database_filename(database_path)
    connection = _connect(filename)
    replay = False
    decision: Optional[HumanDecision] = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        business_content = _normalized_decision_business_content(
            assessment_id=assessment_id,
            assessment_evaluation_id=assessment_evaluation_id,
            decision_maker_actor_id=decision_maker_actor_id,
            disposition=disposition,
            rationale=rationale,
            conditions=conditions,
            information_requests=information_requests,
            acknowledged_policy_finding_ids=(
                acknowledged_policy_finding_ids
            ),
        )
        _, validation_result = _read_request(connection, assessment_id)
        snapshot = _evaluation_snapshot_from_connection(
            connection, assessment_id
        )
        existing_rows = connection.execute(
            "SELECT human_decision_id FROM human_decisions "
            "WHERE assessment_id = ?",
            (assessment_id,),
        ).fetchall()
        if existing_rows:
            replay = True
            existing = _human_decision_from_connection(
                connection, assessment_id
            )
            if _decision_business_content(existing) != business_content:
                raise _error("conflicting_replay")
            decision = existing
            _rollback_safely(connection)
        else:
            _validate_decision_business_content(
                validation_result=validation_result,
                snapshot=snapshot,
                assessment_id=assessment_id,
                assessment_evaluation_id=assessment_evaluation_id,
                decision_maker_actor_id=decision_maker_actor_id,
                disposition=disposition,
                rationale=rationale,
                conditions=conditions,
                information_requests=information_requests,
                acknowledged_policy_finding_ids=(
                    acknowledged_policy_finding_ids
                ),
            )
            recorded_at = _current_decision_time()
            if (
                not isinstance(recorded_at, datetime)
                or recorded_at.tzinfo is None
                or recorded_at.utcoffset() is None
                or recorded_at.utcoffset()
                != timezone.utc.utcoffset(recorded_at)
                or recorded_at
                < snapshot.evaluated_at.astimezone(timezone.utc)
            ):
                raise _error("invalid_input")
            identity_bytes = _human_decision_identity_payload_bytes(
                assessment_id=assessment_id,
                assessment_evaluation_id=assessment_evaluation_id,
                decision_maker_actor_id=decision_maker_actor_id,
                disposition=disposition,
                rationale=rationale,
                conditions=conditions,
                information_requests=information_requests,
                acknowledged_policy_finding_ids=(
                    acknowledged_policy_finding_ids
                ),
                recorded_at=recorded_at,
                decision_schema_version=HUMAN_DECISION_SCHEMA_VERSION,
            )
            decision = HumanDecision(
                human_decision_id=_human_decision_id(identity_bytes),
                assessment_id=assessment_id,
                assessment_evaluation_id=assessment_evaluation_id,
                decision_maker_actor_id=decision_maker_actor_id,
                disposition=disposition,
                rationale=rationale,
                conditions=conditions,
                information_requests=information_requests,
                acknowledged_policy_finding_ids=(
                    acknowledged_policy_finding_ids
                ),
                recorded_at=recorded_at,
                decision_schema_version=HUMAN_DECISION_SCHEMA_VERSION,
            )
            _insert_values(
                connection,
                "human_decisions",
                _HUMAN_DECISION_COLUMNS,
                (
                    decision.human_decision_id,
                    decision.assessment_id,
                    decision.assessment_evaluation_id,
                    decision.decision_maker_actor_id,
                    decision.disposition.value,
                    decision.rationale,
                    _canonical_string_tuple_json(decision.conditions),
                    _canonical_string_tuple_json(
                        decision.information_requests
                    ),
                    _canonical_string_tuple_json(
                        decision.acknowledged_policy_finding_ids
                    ),
                    decision.recorded_at.isoformat(),
                    decision.decision_schema_version,
                ),
            )
            connection.commit()
    except SQLitePersistenceError:
        _rollback_safely(connection)
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        _rollback_safely(connection)
        raise _error("verification_failed") from None
    except sqlite3.Error:
        _rollback_safely(connection)
        raise _error("write_failed") from None
    finally:
        _close_safely(connection)

    if decision is None:
        raise _error("verification_failed")
    stored = load_verified_human_decision(filename, assessment_id)
    if stored != decision:
        raise _error("conflicting_replay" if replay else "verification_failed")
    return stored
