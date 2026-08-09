"""Transient public GitHub repository metadata collection."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .models import EvidenceKind, LicenseStatus


_COLLECTOR_VERSION = "public-github-repository-metadata.v1"
_LICENSE_COLLECTOR_VERSION = "public-github-license-status.v1"
_LATEST_COMMIT_COLLECTOR_VERSION = "public-github-latest-commit.v1"
_HTTP_TIMEOUT_SECONDS = 10.0
_CANONICAL_IDENTITY_PATTERN = re.compile(
    r"github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)\Z"
)
_FULL_NAME_PATTERN = re.compile(
    r"([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)\Z"
)
_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_RESPONSE_HEADERS = (
    "ETag",
    "Retry-After",
    "X-RateLimit-Remaining",
)

_ERROR_DEFINITIONS = {
    "repository_not_publicly_available": (
        "conditionally_retryable",
        "The repository is not available through the public GitHub endpoint.",
    ),
    "repository_has_no_commits": (
        "conditionally_retryable",
        "GitHub returned no commits for the repository.",
    ),
    "github_rate_limited": (
        "retryable",
        "GitHub rate limited the repository metadata request.",
    ),
    "github_authorization_failed": (
        "conditionally_retryable",
        "GitHub did not authorize the public repository metadata request.",
    ),
    "github_request_rejected": (
        "nonretryable",
        "GitHub rejected the repository metadata request.",
    ),
    "github_server_error": (
        "retryable",
        "GitHub could not complete the repository metadata request.",
    ),
    "github_timeout": (
        "retryable",
        "The GitHub repository metadata request timed out.",
    ),
    "github_connectivity_failure": (
        "retryable",
        "The GitHub repository metadata request could not connect.",
    ),
    "github_response_invalid": (
        "conditionally_retryable",
        "GitHub returned an invalid repository metadata response.",
    ),
    "github_unexpected_status": (
        "conditionally_retryable",
        "GitHub returned an unexpected repository metadata status.",
    ),
}


class GitHubCollectionOutcome(str, Enum):
    """Terminal outcome of one transient GitHub collection attempt."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NONRETRYABLE = "failed_nonretryable"


def _require_unpadded_text(field_name: str, value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError("{} must be a nonempty string".format(field_name))
    if value != value.strip():
        raise ValueError(
            "{} must not have surrounding whitespace".format(field_name)
        )


def _identity_parts(repository_identity: object) -> Optional[Tuple[str, str]]:
    if type(repository_identity) is not str:
        return None
    if (
        not repository_identity.isascii()
        or not repository_identity.isprintable()
        or any(character.isspace() for character in repository_identity)
    ):
        return None
    match = _CANONICAL_IDENTITY_PATTERN.fullmatch(repository_identity)
    if match is None:
        return None
    owner, repository = match.groups()
    if owner in (".", "..") or repository in (".", ".."):
        return None
    if repository.casefold().endswith(".git"):
        return None
    return owner, repository


def _full_name_parts(full_name: object) -> Optional[Tuple[str, str]]:
    if type(full_name) is not str:
        return None
    if (
        not full_name.isascii()
        or not full_name.isprintable()
        or any(character.isspace() for character in full_name)
    ):
        return None
    match = _FULL_NAME_PATTERN.fullmatch(full_name)
    if match is None:
        return None
    owner, repository = match.groups()
    if owner in (".", "..") or repository in (".", ".."):
        return None
    if repository.casefold().endswith(".git"):
        return None
    return owner, repository


def _source_identity(request: "GitHubRepositoryMetadataCollectionInput") -> str:
    parts = _identity_parts(request.repository_identity)
    if parts is None:
        raise ValueError("repository_identity must be canonical")
    owner, repository = parts
    return "https://api.github.com/repos/{}/{}".format(owner, repository)


def _latest_commit_source_identity(
    request: "GitHubRepositoryMetadataCollectionInput",
) -> str:
    return _source_identity(request) + "/commits?per_page=1"


def _safe_header_value(value: object) -> Optional[str]:
    if type(value) is not str:
        return None
    if (
        not value.isascii()
        or not value.isprintable()
        or "\r" in value
        or "\n" in value
    ):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _header_value(
    headers: Tuple[Tuple[str, str], ...], name: str
) -> Optional[str]:
    for header_name, header_value in headers:
        if (
            type(header_name) is str
            and header_name.casefold() == name.casefold()
        ):
            return header_value if type(header_value) is str else None
    return None


def _reject_json_constant(value: str) -> None:
    raise ValueError("nonstandard JSON constant")


def _validated_payload_values(
    raw_snapshot: object, requested_full_name: str
) -> Optional[Tuple[str, bool]]:
    if type(raw_snapshot) is not str:
        return None
    try:
        payload = json.loads(
            raw_snapshot,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        return None
    if type(payload) is not dict:
        return None

    repository_id = payload.get("id")
    full_name = payload.get("full_name")
    archived = payload.get("archived")
    if type(repository_id) is not int or repository_id <= 0:
        return None
    if _full_name_parts(full_name) is None:
        return None
    if full_name.casefold() != requested_full_name.casefold():
        return None
    if type(archived) is not bool:
        return None
    return str(repository_id), archived


def _valid_license_text(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


def _validated_license_payload_values(
    raw_snapshot: object, requested_full_name: str
) -> Optional[Tuple[str, LicenseStatus]]:
    if type(raw_snapshot) is not str:
        return None
    try:
        payload = json.loads(
            raw_snapshot,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        return None
    if type(payload) is not dict or "license" not in payload:
        return None

    repository_id = payload.get("id")
    full_name = payload.get("full_name")
    license_metadata = payload["license"]
    if type(repository_id) is not int or repository_id <= 0:
        return None
    if _full_name_parts(full_name) is None:
        return None
    if full_name.casefold() != requested_full_name.casefold():
        return None
    if license_metadata is None:
        return str(repository_id), LicenseStatus.ABSENT
    if type(license_metadata) is not dict:
        return None
    for field_name in ("key", "name", "spdx_id"):
        if not _valid_license_text(license_metadata.get(field_name)):
            return None
    return str(repository_id), LicenseStatus.PRESENT


def _validated_latest_commit_payload_values(
    raw_snapshot: object,
    requested_full_name: str,
) -> Optional[Tuple[Optional[str], Optional[datetime], Optional[str]]]:
    if type(raw_snapshot) is not str:
        return None
    try:
        payload = json.loads(
            raw_snapshot,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        return None
    if type(payload) is not list or len(payload) > 1:
        return None
    if not payload:
        return (None, None, None)

    item = payload[0]
    if type(item) is not dict:
        return None
    commit_sha = item.get("sha")
    commit_url = item.get("url")
    commit = item.get("commit")
    if (
        type(commit_sha) is not str
        or _COMMIT_SHA_PATTERN.fullmatch(commit_sha) is None
        or type(commit_url) is not str
        or type(commit) is not dict
    ):
        return None

    try:
        parsed_url = urlsplit(commit_url)
    except ValueError:
        return None
    path_parts = parsed_url.path.split("/")
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "api.github.com"
        or parsed_url.query
        or parsed_url.fragment
        or len(path_parts) != 6
        or path_parts[:2] != ["", "repos"]
        or path_parts[4] != "commits"
        or path_parts[5] != commit_sha
    ):
        return None
    returned_full_name = "{}/{}".format(path_parts[2], path_parts[3])
    if (
        _full_name_parts(returned_full_name) is None
        or returned_full_name.casefold() != requested_full_name.casefold()
    ):
        return None

    committer = commit.get("committer")
    if type(committer) is not dict:
        return None
    source_timestamp = committer.get("date")
    if (
        type(source_timestamp) is not str
        or not source_timestamp
        or source_timestamp != source_timestamp.strip()
        or not source_timestamp.isprintable()
    ):
        return None
    try:
        parsed_timestamp = (
            source_timestamp[:-1] + "+00:00"
            if source_timestamp.endswith("Z")
            else source_timestamp
        )
        latest_commit_at = datetime.fromisoformat(parsed_timestamp)
        is_aware = (
            latest_commit_at.tzinfo is not None
            and latest_commit_at.utcoffset() is not None
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if not is_aware:
        return None
    return commit_sha, latest_commit_at, source_timestamp


@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionInput:
    """Immutable input for one post-validation GitHub collection attempt."""

    assessment_id: str
    repository_identity: str
    collection_attempt_id: str
    attempt_number: int
    attempted_at: datetime

    def __post_init__(self) -> None:
        _require_unpadded_text("assessment_id", self.assessment_id)
        _require_unpadded_text(
            "collection_attempt_id", self.collection_attempt_id
        )
        if _identity_parts(self.repository_identity) is None:
            raise ValueError(
                "repository_identity must use canonical "
                "github.com/owner/repository format"
            )
        if type(self.attempt_number) is not int or self.attempt_number <= 0:
            raise ValueError("attempt_number must be a positive integer")
        if not isinstance(self.attempted_at, datetime):
            raise ValueError("attempted_at must be a datetime")
        try:
            is_aware = (
                self.attempted_at.tzinfo is not None
                and self.attempted_at.utcoffset() is not None
            )
        except Exception:
            is_aware = False
        if not is_aware:
            raise ValueError("attempted_at must be timezone-aware")


@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionError:
    """One sanitized deterministic GitHub collection error."""

    category: str
    retryability: str
    message: str
    retry_after: Optional[str] = None

    def __post_init__(self) -> None:
        definition = _ERROR_DEFINITIONS.get(self.category)
        if definition is None:
            raise ValueError("category must be a supported collection error")
        expected_retryability, expected_message = definition
        if self.retryability != expected_retryability:
            raise ValueError("retryability does not match error category")
        if self.message != expected_message:
            raise ValueError("message does not match error category")
        if self.retry_after is not None:
            if self.category not in (
                "github_rate_limited",
                "github_server_error",
            ):
                raise ValueError(
                    "retry_after is not valid for this error category"
                )
            if _safe_header_value(self.retry_after) != self.retry_after:
                raise ValueError("retry_after must be a safe header value")


@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionResult:
    """Complete transient output of one GitHub metadata collection attempt."""

    request: GitHubRepositoryMetadataCollectionInput
    outcome: GitHubCollectionOutcome
    evidence_kind: EvidenceKind
    collector_version: str
    source_identity: str
    repository_source_id: Optional[str]
    archived: Optional[bool]
    raw_snapshot: Optional[str]
    integrity_digest: Optional[str]
    response_status: Optional[int]
    response_etag: Optional[str]
    error: Optional[GitHubRepositoryMetadataCollectionError]

    def __post_init__(self) -> None:
        if type(self.request) is not GitHubRepositoryMetadataCollectionInput:
            raise ValueError(
                "request must be a GitHubRepositoryMetadataCollectionInput"
            )
        if type(self.outcome) is not GitHubCollectionOutcome:
            raise ValueError("outcome must be a GitHubCollectionOutcome")
        if self.evidence_kind is not EvidenceKind.REPOSITORY_ARCHIVED:
            raise ValueError(
                "evidence_kind must be repository_archived"
            )
        if self.collector_version != _COLLECTOR_VERSION:
            raise ValueError("collector_version is not supported")
        if self.source_identity != _source_identity(self.request):
            raise ValueError("source_identity does not match request")
        if self.response_status is not None and (
            type(self.response_status) is not int
            or not 100 <= self.response_status <= 599
        ):
            raise ValueError("response_status must be a valid HTTP status")
        if self.response_etag is not None:
            if self.outcome is not GitHubCollectionOutcome.AVAILABLE:
                raise ValueError("response_etag is valid only when available")
            if _safe_header_value(self.response_etag) != self.response_etag:
                raise ValueError("response_etag must be a safe header value")

        if self.outcome is GitHubCollectionOutcome.AVAILABLE:
            self._validate_available()
            return
        self._validate_nonavailable()

    def _validate_available(self) -> None:
        if self.response_status != 200 or self.error is not None:
            raise ValueError(
                "available result requires HTTP 200 and no error"
            )
        if (
            type(self.repository_source_id) is not str
            or not self.repository_source_id.isascii()
            or not self.repository_source_id.isdecimal()
        ):
            raise ValueError(
                "available result requires a decimal repository source ID"
            )
        repository_id = int(self.repository_source_id)
        if repository_id <= 0 or str(repository_id) != self.repository_source_id:
            raise ValueError(
                "repository_source_id must be canonical and positive"
            )
        if type(self.archived) is not bool:
            raise ValueError("available result requires a Boolean archived value")
        if type(self.raw_snapshot) is not str:
            raise ValueError("available result requires a raw snapshot")
        expected_digest = hashlib.sha256(
            self.raw_snapshot.encode("utf-8")
        ).hexdigest()
        if self.integrity_digest != expected_digest:
            raise ValueError("integrity_digest does not match raw_snapshot")

        parts = _identity_parts(self.request.repository_identity)
        if parts is None:
            raise ValueError("request repository identity is invalid")
        normalized = _validated_payload_values(
            self.raw_snapshot,
            "{}/{}".format(*parts),
        )
        if normalized != (self.repository_source_id, self.archived):
            raise ValueError(
                "raw_snapshot does not match normalized repository metadata"
            )

    def _validate_nonavailable(self) -> None:
        if (
            self.repository_source_id is not None
            or self.archived is not None
            or self.raw_snapshot is not None
            or self.integrity_digest is not None
            or self.response_etag is not None
        ):
            raise ValueError(
                "nonavailable result cannot contain partial evidence"
            )
        if type(self.error) is not GitHubRepositoryMetadataCollectionError:
            raise ValueError("nonavailable result requires an error")

        category = self.error.category
        if self.outcome is GitHubCollectionOutcome.UNAVAILABLE:
            if (
                self.response_status != 404
                or category != "repository_not_publicly_available"
                or self.error.retry_after is not None
            ):
                raise ValueError("unavailable result has contradictory fields")
            return

        if self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE:
            if self.error.retryability != "retryable":
                raise ValueError("retryable failure requires retryable error")
        elif self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE:
            if self.error.retryability not in (
                "nonretryable",
                "conditionally_retryable",
            ):
                raise ValueError(
                    "nonretryable failure has invalid retryability"
                )
        else:
            raise ValueError("unsupported nonavailable outcome")

        if category == "github_rate_limited":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status in (403, 429)
            )
        elif category == "github_authorization_failed":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status in (401, 403)
                and self.error.retry_after is None
            )
        elif category == "github_request_rejected":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and 400 <= self.response_status <= 499
                and self.response_status not in (401, 403, 404, 429)
                and self.error.retry_after is None
            )
        elif category == "github_server_error":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is not None
                and 500 <= self.response_status <= 599
            )
        elif category == "github_timeout":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is None
                and self.error.retry_after is None
            )
        elif category == "github_connectivity_failure":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is None
                and self.error.retry_after is None
            )
        elif category == "github_response_invalid":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status == 200
                and self.error.retry_after is None
            )
        elif category == "github_unexpected_status":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and not 400 <= self.response_status <= 599
                and self.response_status != 200
                and self.error.retry_after is None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("failure result does not match classification")


@dataclass(frozen=True)
class GitHubLicenseStatusCollectionResult:
    """Complete transient output of one GitHub license collection attempt."""

    request: GitHubRepositoryMetadataCollectionInput
    outcome: GitHubCollectionOutcome
    evidence_kind: EvidenceKind
    collector_version: str
    source_identity: str
    repository_source_id: Optional[str]
    license_status: Optional[LicenseStatus]
    raw_snapshot: Optional[str]
    integrity_digest: Optional[str]
    response_status: Optional[int]
    response_etag: Optional[str]
    error: Optional[GitHubRepositoryMetadataCollectionError]

    def __post_init__(self) -> None:
        if type(self.request) is not GitHubRepositoryMetadataCollectionInput:
            raise ValueError(
                "request must be a GitHubRepositoryMetadataCollectionInput"
            )
        if type(self.outcome) is not GitHubCollectionOutcome:
            raise ValueError("outcome must be a GitHubCollectionOutcome")
        if self.evidence_kind is not EvidenceKind.LICENSE_STATUS:
            raise ValueError("evidence_kind must be license_status")
        if self.collector_version != _LICENSE_COLLECTOR_VERSION:
            raise ValueError("collector_version is not supported")
        if self.source_identity != _source_identity(self.request):
            raise ValueError("source_identity does not match request")
        if self.response_status is not None and (
            type(self.response_status) is not int
            or not 100 <= self.response_status <= 599
        ):
            raise ValueError("response_status must be a valid HTTP status")
        if self.response_etag is not None:
            if self.outcome is not GitHubCollectionOutcome.AVAILABLE:
                raise ValueError("response_etag is valid only when available")
            if _safe_header_value(self.response_etag) != self.response_etag:
                raise ValueError("response_etag must be a safe header value")

        if self.outcome is GitHubCollectionOutcome.AVAILABLE:
            self._validate_available()
            return
        self._validate_nonavailable()

    def _validate_available(self) -> None:
        if self.response_status != 200 or self.error is not None:
            raise ValueError(
                "available result requires HTTP 200 and no error"
            )
        if (
            type(self.repository_source_id) is not str
            or not self.repository_source_id.isascii()
            or not self.repository_source_id.isdecimal()
        ):
            raise ValueError(
                "available result requires a decimal repository source ID"
            )
        repository_id = int(self.repository_source_id)
        if repository_id <= 0 or str(repository_id) != self.repository_source_id:
            raise ValueError(
                "repository_source_id must be canonical and positive"
            )
        if type(self.license_status) is not LicenseStatus:
            raise ValueError(
                "available result requires a LicenseStatus value"
            )
        if type(self.raw_snapshot) is not str:
            raise ValueError("available result requires a raw snapshot")
        expected_digest = hashlib.sha256(
            self.raw_snapshot.encode("utf-8")
        ).hexdigest()
        if self.integrity_digest != expected_digest:
            raise ValueError("integrity_digest does not match raw_snapshot")

        parts = _identity_parts(self.request.repository_identity)
        if parts is None:
            raise ValueError("request repository identity is invalid")
        normalized = _validated_license_payload_values(
            self.raw_snapshot,
            "{}/{}".format(*parts),
        )
        if normalized != (self.repository_source_id, self.license_status):
            raise ValueError(
                "raw_snapshot does not match normalized license metadata"
            )

    def _validate_nonavailable(self) -> None:
        if (
            self.repository_source_id is not None
            or self.license_status is not None
            or self.raw_snapshot is not None
            or self.integrity_digest is not None
            or self.response_etag is not None
        ):
            raise ValueError(
                "nonavailable result cannot contain partial evidence"
            )
        if type(self.error) is not GitHubRepositoryMetadataCollectionError:
            raise ValueError("nonavailable result requires an error")

        category = self.error.category
        if self.outcome is GitHubCollectionOutcome.UNAVAILABLE:
            if (
                self.response_status != 404
                or category != "repository_not_publicly_available"
                or self.error.retry_after is not None
            ):
                raise ValueError("unavailable result has contradictory fields")
            return

        if self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE:
            if self.error.retryability != "retryable":
                raise ValueError("retryable failure requires retryable error")
        elif self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE:
            if self.error.retryability not in (
                "nonretryable",
                "conditionally_retryable",
            ):
                raise ValueError(
                    "nonretryable failure has invalid retryability"
                )
        else:
            raise ValueError("unsupported nonavailable outcome")

        if category == "github_rate_limited":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status in (403, 429)
            )
        elif category == "github_authorization_failed":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status in (401, 403)
                and self.error.retry_after is None
            )
        elif category == "github_request_rejected":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and 400 <= self.response_status <= 499
                and self.response_status not in (401, 403, 404, 429)
                and self.error.retry_after is None
            )
        elif category == "github_server_error":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is not None
                and 500 <= self.response_status <= 599
            )
        elif category in ("github_timeout", "github_connectivity_failure"):
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is None
                and self.error.retry_after is None
            )
        elif category == "github_response_invalid":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status == 200
                and self.error.retry_after is None
            )
        elif category == "github_unexpected_status":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and not 400 <= self.response_status <= 599
                and self.response_status != 200
                and self.error.retry_after is None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("failure result does not match classification")


@dataclass(frozen=True)
class GitHubLatestCommitCollectionResult:
    """Complete transient output of one GitHub latest-commit collection."""

    request: GitHubRepositoryMetadataCollectionInput
    outcome: GitHubCollectionOutcome
    evidence_kind: EvidenceKind
    collector_version: str
    source_identity: str
    commit_sha: Optional[str]
    latest_commit_at: Optional[datetime]
    source_timestamp: Optional[str]
    raw_snapshot: Optional[str]
    integrity_digest: Optional[str]
    response_status: Optional[int]
    response_etag: Optional[str]
    error: Optional[GitHubRepositoryMetadataCollectionError]

    def __post_init__(self) -> None:
        if type(self.request) is not GitHubRepositoryMetadataCollectionInput:
            raise ValueError(
                "request must be a GitHubRepositoryMetadataCollectionInput"
            )
        if type(self.outcome) is not GitHubCollectionOutcome:
            raise ValueError("outcome must be a GitHubCollectionOutcome")
        if self.evidence_kind is not EvidenceKind.LATEST_COMMIT_TIMESTAMP:
            raise ValueError("evidence_kind must be latest_commit_timestamp")
        if self.collector_version != _LATEST_COMMIT_COLLECTOR_VERSION:
            raise ValueError("collector_version is not supported")
        if self.source_identity != _latest_commit_source_identity(self.request):
            raise ValueError("source_identity does not match request")
        if self.response_status is not None and (
            type(self.response_status) is not int
            or not 100 <= self.response_status <= 599
        ):
            raise ValueError("response_status must be a valid HTTP status")
        if self.response_etag is not None:
            if self.outcome is not GitHubCollectionOutcome.AVAILABLE:
                raise ValueError("response_etag is valid only when available")
            if _safe_header_value(self.response_etag) != self.response_etag:
                raise ValueError("response_etag must be a safe header value")

        if self.outcome is GitHubCollectionOutcome.AVAILABLE:
            self._validate_available()
            return
        self._validate_nonavailable()

    def _validate_available(self) -> None:
        if self.response_status != 200 or self.error is not None:
            raise ValueError(
                "available result requires HTTP 200 and no error"
            )
        if (
            type(self.commit_sha) is not str
            or _COMMIT_SHA_PATTERN.fullmatch(self.commit_sha) is None
        ):
            raise ValueError("available result requires a valid commit SHA")
        if not isinstance(self.latest_commit_at, datetime):
            raise ValueError("available result requires a commit datetime")
        try:
            is_aware = (
                self.latest_commit_at.tzinfo is not None
                and self.latest_commit_at.utcoffset() is not None
            )
        except Exception:
            is_aware = False
        if not is_aware:
            raise ValueError("latest_commit_at must be timezone-aware")
        if type(self.source_timestamp) is not str:
            raise ValueError("available result requires a source timestamp")
        if type(self.raw_snapshot) is not str:
            raise ValueError("available result requires a raw snapshot")
        expected_digest = hashlib.sha256(
            self.raw_snapshot.encode("utf-8")
        ).hexdigest()
        if self.integrity_digest != expected_digest:
            raise ValueError("integrity_digest does not match raw_snapshot")

        parts = _identity_parts(self.request.repository_identity)
        if parts is None:
            raise ValueError("request repository identity is invalid")
        normalized = _validated_latest_commit_payload_values(
            self.raw_snapshot,
            "{}/{}".format(*parts),
        )
        if normalized is None:
            raise ValueError("raw_snapshot is not valid commit metadata")
        commit_sha, latest_commit_at, source_timestamp = normalized
        if (
            commit_sha != self.commit_sha
            or source_timestamp != self.source_timestamp
            or latest_commit_at is None
            or latest_commit_at.astimezone(timezone.utc)
            != self.latest_commit_at.astimezone(timezone.utc)
        ):
            raise ValueError(
                "raw_snapshot does not match normalized commit metadata"
            )

    def _validate_nonavailable(self) -> None:
        if (
            self.commit_sha is not None
            or self.latest_commit_at is not None
            or self.source_timestamp is not None
            or self.raw_snapshot is not None
            or self.integrity_digest is not None
            or self.response_etag is not None
        ):
            raise ValueError(
                "nonavailable result cannot contain partial evidence"
            )
        if type(self.error) is not GitHubRepositoryMetadataCollectionError:
            raise ValueError("nonavailable result requires an error")

        category = self.error.category
        if self.outcome is GitHubCollectionOutcome.UNAVAILABLE:
            valid_unavailable = (
                self.response_status == 404
                and category == "repository_not_publicly_available"
            ) or (
                self.response_status == 200
                and category == "repository_has_no_commits"
            )
            if not valid_unavailable or self.error.retry_after is not None:
                raise ValueError("unavailable result has contradictory fields")
            return

        if self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE:
            if self.error.retryability != "retryable":
                raise ValueError("retryable failure requires retryable error")
        elif self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE:
            if self.error.retryability not in (
                "nonretryable",
                "conditionally_retryable",
            ):
                raise ValueError(
                    "nonretryable failure has invalid retryability"
                )
        else:
            raise ValueError("unsupported nonavailable outcome")

        if category == "github_rate_limited":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status in (403, 429)
            )
        elif category == "github_authorization_failed":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status in (401, 403)
                and self.error.retry_after is None
            )
        elif category == "github_request_rejected":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and 400 <= self.response_status <= 499
                and self.response_status not in (401, 403, 404, 429)
                and self.error.retry_after is None
            )
        elif category == "github_server_error":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is not None
                and 500 <= self.response_status <= 599
            )
        elif category in ("github_timeout", "github_connectivity_failure"):
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_RETRYABLE
                and self.response_status is None
                and self.error.retry_after is None
            )
        elif category == "github_response_invalid":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status == 200
                and self.error.retry_after is None
            )
        elif category == "github_unexpected_status":
            valid = (
                self.outcome is GitHubCollectionOutcome.FAILED_NONRETRYABLE
                and self.response_status is not None
                and not 400 <= self.response_status <= 599
                and self.response_status != 200
                and self.error.retry_after is None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("failure result does not match classification")


def _error(
    category: str, retry_after: Optional[str] = None
) -> GitHubRepositoryMetadataCollectionError:
    retryability, message = _ERROR_DEFINITIONS[category]
    return GitHubRepositoryMetadataCollectionError(
        category=category,
        retryability=retryability,
        message=message,
        retry_after=retry_after,
    )


def _failure_result(
    request: GitHubRepositoryMetadataCollectionInput,
    response_status: Optional[int],
    category: str,
    retry_after: Optional[str] = None,
) -> GitHubRepositoryMetadataCollectionResult:
    retryability, _ = _ERROR_DEFINITIONS[category]
    outcome = (
        GitHubCollectionOutcome.FAILED_RETRYABLE
        if retryability == "retryable"
        else GitHubCollectionOutcome.FAILED_NONRETRYABLE
    )
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=_COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        repository_source_id=None,
        archived=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=response_status,
        response_etag=None,
        error=_error(category, retry_after),
    )


def _unavailable_result(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubRepositoryMetadataCollectionResult:
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=_COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        repository_source_id=None,
        archived=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=404,
        response_etag=None,
        error=_error("repository_not_publicly_available"),
    )


def collect_public_github_repository_metadata(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubRepositoryMetadataCollectionResult:
    """Collect one transient public GitHub repository archived-status fact."""

    if type(request) is not GitHubRepositoryMetadataCollectionInput:
        raise ValueError(
            "request must be a GitHubRepositoryMetadataCollectionInput"
        )
    source_identity = _source_identity(request)
    try:
        response_status, response_body, response_headers = (
            _get_public_github_repository(source_identity)
        )
    except (socket.timeout, TimeoutError):
        return _failure_result(request, None, "github_timeout")
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return _failure_result(request, None, "github_timeout")
        return _failure_result(request, None, "github_connectivity_failure")
    except ConnectionError:
        return _failure_result(request, None, "github_connectivity_failure")

    retry_after = _safe_header_value(
        _header_value(response_headers, "Retry-After")
    )
    if response_status == 404:
        return _unavailable_result(request)

    rate_limit_remaining = _header_value(
        response_headers, "X-RateLimit-Remaining"
    )
    is_rate_limited = response_status == 429 or (
        response_status == 403
        and _safe_header_value(rate_limit_remaining) == "0"
    )
    if is_rate_limited:
        return _failure_result(
            request,
            response_status,
            "github_rate_limited",
            retry_after,
        )
    if response_status in (401, 403):
        return _failure_result(
            request,
            response_status,
            "github_authorization_failed",
        )
    if type(response_status) is int and 400 <= response_status <= 499:
        return _failure_result(
            request,
            response_status,
            "github_request_rejected",
        )
    if type(response_status) is int and 500 <= response_status <= 599:
        return _failure_result(
            request,
            response_status,
            "github_server_error",
            retry_after,
        )
    if response_status != 200:
        return _failure_result(
            request,
            response_status,
            "github_unexpected_status",
        )

    if type(response_body) is not bytes:
        return _failure_result(
            request,
            200,
            "github_response_invalid",
        )
    try:
        raw_snapshot = response_body.decode("utf-8")
    except UnicodeDecodeError:
        return _failure_result(
            request,
            200,
            "github_response_invalid",
        )

    parts = _identity_parts(request.repository_identity)
    if parts is None:
        raise ValueError("request repository identity is invalid")
    normalized = _validated_payload_values(
        raw_snapshot,
        "{}/{}".format(*parts),
    )
    if normalized is None:
        return _failure_result(
            request,
            200,
            "github_response_invalid",
        )
    repository_source_id, archived = normalized
    response_etag = _safe_header_value(
        _header_value(response_headers, "ETag")
    )
    return GitHubRepositoryMetadataCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.REPOSITORY_ARCHIVED,
        collector_version=_COLLECTOR_VERSION,
        source_identity=source_identity,
        repository_source_id=repository_source_id,
        archived=archived,
        raw_snapshot=raw_snapshot,
        integrity_digest=hashlib.sha256(response_body).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _license_failure_result(
    request: GitHubRepositoryMetadataCollectionInput,
    response_status: Optional[int],
    category: str,
    retry_after: Optional[str] = None,
) -> GitHubLicenseStatusCollectionResult:
    retryability, _ = _ERROR_DEFINITIONS[category]
    outcome = (
        GitHubCollectionOutcome.FAILED_RETRYABLE
        if retryability == "retryable"
        else GitHubCollectionOutcome.FAILED_NONRETRYABLE
    )
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=_LICENSE_COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        repository_source_id=None,
        license_status=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=response_status,
        response_etag=None,
        error=_error(category, retry_after),
    )


def _license_unavailable_result(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLicenseStatusCollectionResult:
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=_LICENSE_COLLECTOR_VERSION,
        source_identity=_source_identity(request),
        repository_source_id=None,
        license_status=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=404,
        response_etag=None,
        error=_error("repository_not_publicly_available"),
    )


def collect_public_github_license_status(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLicenseStatusCollectionResult:
    """Collect one transient public GitHub detected-license fact."""

    if type(request) is not GitHubRepositoryMetadataCollectionInput:
        raise ValueError(
            "request must be a GitHubRepositoryMetadataCollectionInput"
        )
    source_identity = _source_identity(request)
    try:
        response_status, response_body, response_headers = (
            _get_public_github_repository(source_identity)
        )
    except (socket.timeout, TimeoutError):
        return _license_failure_result(request, None, "github_timeout")
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return _license_failure_result(request, None, "github_timeout")
        return _license_failure_result(
            request, None, "github_connectivity_failure"
        )
    except ConnectionError:
        return _license_failure_result(
            request, None, "github_connectivity_failure"
        )

    retry_after = _safe_header_value(
        _header_value(response_headers, "Retry-After")
    )
    if response_status == 404:
        return _license_unavailable_result(request)

    rate_limit_remaining = _header_value(
        response_headers, "X-RateLimit-Remaining"
    )
    is_rate_limited = response_status == 429 or (
        response_status == 403
        and _safe_header_value(rate_limit_remaining) == "0"
    )
    if is_rate_limited:
        return _license_failure_result(
            request,
            response_status,
            "github_rate_limited",
            retry_after,
        )
    if response_status in (401, 403):
        return _license_failure_result(
            request, response_status, "github_authorization_failed"
        )
    if type(response_status) is int and 400 <= response_status <= 499:
        return _license_failure_result(
            request, response_status, "github_request_rejected"
        )
    if type(response_status) is int and 500 <= response_status <= 599:
        return _license_failure_result(
            request,
            response_status,
            "github_server_error",
            retry_after,
        )
    if response_status != 200:
        return _license_failure_result(
            request, response_status, "github_unexpected_status"
        )

    if type(response_body) is not bytes:
        return _license_failure_result(
            request, 200, "github_response_invalid"
        )
    try:
        raw_snapshot = response_body.decode("utf-8")
    except UnicodeDecodeError:
        return _license_failure_result(
            request, 200, "github_response_invalid"
        )

    parts = _identity_parts(request.repository_identity)
    if parts is None:
        raise ValueError("request repository identity is invalid")
    normalized = _validated_license_payload_values(
        raw_snapshot,
        "{}/{}".format(*parts),
    )
    if normalized is None:
        return _license_failure_result(
            request, 200, "github_response_invalid"
        )
    repository_source_id, license_status = normalized
    response_etag = _safe_header_value(
        _header_value(response_headers, "ETag")
    )
    return GitHubLicenseStatusCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.LICENSE_STATUS,
        collector_version=_LICENSE_COLLECTOR_VERSION,
        source_identity=source_identity,
        repository_source_id=repository_source_id,
        license_status=license_status,
        raw_snapshot=raw_snapshot,
        integrity_digest=hashlib.sha256(response_body).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _latest_commit_failure_result(
    request: GitHubRepositoryMetadataCollectionInput,
    response_status: Optional[int],
    category: str,
    retry_after: Optional[str] = None,
) -> GitHubLatestCommitCollectionResult:
    retryability, _ = _ERROR_DEFINITIONS[category]
    outcome = (
        GitHubCollectionOutcome.FAILED_RETRYABLE
        if retryability == "retryable"
        else GitHubCollectionOutcome.FAILED_NONRETRYABLE
    )
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=outcome,
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=_LATEST_COMMIT_COLLECTOR_VERSION,
        source_identity=_latest_commit_source_identity(request),
        commit_sha=None,
        latest_commit_at=None,
        source_timestamp=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=response_status,
        response_etag=None,
        error=_error(category, retry_after),
    )


def _latest_commit_unavailable_result(
    request: GitHubRepositoryMetadataCollectionInput,
    *,
    empty_repository: bool,
) -> GitHubLatestCommitCollectionResult:
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.UNAVAILABLE,
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=_LATEST_COMMIT_COLLECTOR_VERSION,
        source_identity=_latest_commit_source_identity(request),
        commit_sha=None,
        latest_commit_at=None,
        source_timestamp=None,
        raw_snapshot=None,
        integrity_digest=None,
        response_status=200 if empty_repository else 404,
        response_etag=None,
        error=_error(
            "repository_has_no_commits"
            if empty_repository
            else "repository_not_publicly_available"
        ),
    )


def collect_public_github_latest_commit(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLatestCommitCollectionResult:
    """Collect one transient public GitHub latest-commit timestamp fact."""

    if type(request) is not GitHubRepositoryMetadataCollectionInput:
        raise ValueError(
            "request must be a GitHubRepositoryMetadataCollectionInput"
        )
    source_identity = _latest_commit_source_identity(request)
    try:
        response_status, response_body, response_headers = (
            _get_public_github_repository(source_identity)
        )
    except (socket.timeout, TimeoutError):
        return _latest_commit_failure_result(request, None, "github_timeout")
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return _latest_commit_failure_result(
                request, None, "github_timeout"
            )
        return _latest_commit_failure_result(
            request, None, "github_connectivity_failure"
        )
    except ConnectionError:
        return _latest_commit_failure_result(
            request, None, "github_connectivity_failure"
        )

    retry_after = _safe_header_value(
        _header_value(response_headers, "Retry-After")
    )
    if response_status == 404:
        return _latest_commit_unavailable_result(
            request, empty_repository=False
        )
    rate_limit_remaining = _header_value(
        response_headers, "X-RateLimit-Remaining"
    )
    is_rate_limited = response_status == 429 or (
        response_status == 403
        and _safe_header_value(rate_limit_remaining) == "0"
    )
    if is_rate_limited:
        return _latest_commit_failure_result(
            request, response_status, "github_rate_limited", retry_after
        )
    if response_status in (401, 403):
        return _latest_commit_failure_result(
            request, response_status, "github_authorization_failed"
        )
    if type(response_status) is int and 400 <= response_status <= 499:
        return _latest_commit_failure_result(
            request, response_status, "github_request_rejected"
        )
    if type(response_status) is int and 500 <= response_status <= 599:
        return _latest_commit_failure_result(
            request, response_status, "github_server_error", retry_after
        )
    if response_status != 200:
        return _latest_commit_failure_result(
            request, response_status, "github_unexpected_status"
        )
    if type(response_body) is not bytes:
        return _latest_commit_failure_result(
            request, 200, "github_response_invalid"
        )
    try:
        raw_snapshot = response_body.decode("utf-8")
    except UnicodeDecodeError:
        return _latest_commit_failure_result(
            request, 200, "github_response_invalid"
        )

    parts = _identity_parts(request.repository_identity)
    if parts is None:
        raise ValueError("request repository identity is invalid")
    normalized = _validated_latest_commit_payload_values(
        raw_snapshot,
        "{}/{}".format(*parts),
    )
    if normalized is None:
        return _latest_commit_failure_result(
            request, 200, "github_response_invalid"
        )
    commit_sha, latest_commit_at, source_timestamp = normalized
    if commit_sha is None:
        return _latest_commit_unavailable_result(
            request, empty_repository=True
        )
    response_etag = _safe_header_value(
        _header_value(response_headers, "ETag")
    )
    return GitHubLatestCommitCollectionResult(
        request=request,
        outcome=GitHubCollectionOutcome.AVAILABLE,
        evidence_kind=EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collector_version=_LATEST_COMMIT_COLLECTOR_VERSION,
        source_identity=source_identity,
        commit_sha=commit_sha,
        latest_commit_at=latest_commit_at,
        source_timestamp=source_timestamp,
        raw_snapshot=raw_snapshot,
        integrity_digest=hashlib.sha256(response_body).hexdigest(),
        response_status=200,
        response_etag=response_etag,
        error=None,
    )


def _selected_headers(headers: object) -> Tuple[Tuple[str, str], ...]:
    selected = []
    for name in _SAFE_RESPONSE_HEADERS:
        value = headers.get(name) if headers is not None else None
        if type(value) is str:
            selected.append((name, value))
    return tuple(selected)


def _get_public_github_repository(
    source_identity: str,
) -> Tuple[int, Optional[bytes], Tuple[Tuple[str, str], ...]]:
    request = Request(
        source_identity,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "engineering-due-diligence-platform",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            return (
                response.getcode(),
                response.read(),
                _selected_headers(response.headers),
            )
    except HTTPError as exc:
        try:
            return exc.code, None, _selected_headers(exc.headers)
        finally:
            exc.close()
