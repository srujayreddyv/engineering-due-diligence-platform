"""One-shot execution of one complete public GitHub assessment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .assessment import (
    AssessmentEvaluationSnapshot,
    DeterministicAssessmentResult,
    build_assessment_evaluation_snapshot,
    evaluate_persisted_assessment,
)
from .evaluation import REQUIRED_EVIDENCE_KINDS
from .github import (
    GitHubCollectionOutcome,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    collect_public_github_latest_commit,
    collect_public_github_license_status,
    collect_public_github_repository_metadata,
    collect_public_github_security_policy_presence,
)
from .models import EvidenceKind, EvidenceRecord
from .persistence import (
    SQLitePersistenceError,
    load_verified_assessment_evaluation_snapshot,
    persist_assessment_evaluation_snapshot,
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_github_security_policy_presence_collection,
    persist_valid_assessment_request,
)
from .request import (
    AssessmentRequestInput,
    AssessmentRequestValidationResult,
    validate_assessment_request,
)


_EXECUTION_NAMESPACE = "assessment-execution.v1"
_ATTEMPT_NUMBER = 1


class AssessmentExecutionStatus(str, Enum):
    """Terminal status returned by one execution call."""

    INVALID_REQUEST = "invalid_request"
    COLLECTION_FAILED = "collection_failed"
    COMPLETE = "complete"


def _require_aware_datetime(field_name: str, value: object) -> None:
    if not isinstance(value, datetime):
        raise ValueError("{} must be a datetime".format(field_name))
    try:
        is_aware = value.tzinfo is not None and value.utcoffset() is not None
    except Exception:
        is_aware = False
    if not is_aware:
        raise ValueError("{} must be timezone-aware".format(field_name))


def _current_evaluation_time() -> datetime:
    """Return the aware UTC time used for transient evaluation."""

    return datetime.now(timezone.utc)


def _collection_attempt_id(
    assessment_id: str, evidence_kind: EvidenceKind
) -> str:
    canonical = json.dumps(
        {
            "assessment_id": assessment_id,
            "attempt_number": _ATTEMPT_NUMBER,
            "evidence_kind": evidence_kind.value,
            "namespace": _EXECUTION_NAMESPACE,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "collection-attempt-{}".format(
        hashlib.sha256(canonical).hexdigest()
    )


@dataclass(frozen=True)
class AssessmentExecutionInput:
    """Immutable input for one one-shot assessment execution."""

    request: AssessmentRequestInput
    collection_attempted_at: datetime

    def __post_init__(self) -> None:
        if type(self.request) is not AssessmentRequestInput:
            raise ValueError("request must be an AssessmentRequestInput")
        _require_aware_datetime(
            "collection_attempted_at", self.collection_attempted_at
        )


@dataclass(frozen=True)
class AssessmentExecutionFailure:
    """Sanitized durable terminal collector failure for one evidence kind."""

    evidence_kind: EvidenceKind
    collection_attempt_id: str
    outcome: GitHubCollectionOutcome
    error: GitHubRepositoryMetadataCollectionError

    def __post_init__(self) -> None:
        if type(self.evidence_kind) is not EvidenceKind:
            raise ValueError("evidence_kind must be an EvidenceKind")
        if (
            type(self.collection_attempt_id) is not str
            or not self.collection_attempt_id.strip()
            or self.collection_attempt_id != self.collection_attempt_id.strip()
        ):
            raise ValueError(
                "collection_attempt_id must be a nonempty unpadded string"
            )
        if self.outcome not in (
            GitHubCollectionOutcome.FAILED_RETRYABLE,
            GitHubCollectionOutcome.FAILED_NONRETRYABLE,
        ):
            raise ValueError("outcome must be a failed collection outcome")
        if type(self.error) is not GitHubRepositoryMetadataCollectionError:
            raise ValueError(
                "error must be a GitHubRepositoryMetadataCollectionError"
            )
        expected_outcome = (
            GitHubCollectionOutcome.FAILED_RETRYABLE
            if self.error.retryability == "retryable"
            else GitHubCollectionOutcome.FAILED_NONRETRYABLE
        )
        if self.outcome is not expected_outcome:
            raise ValueError("outcome does not match error retryability")


@dataclass(frozen=True)
class AssessmentExecutionResult:
    """Complete terminal output of one assessment execution call."""

    execution_input: AssessmentExecutionInput
    validation_result: AssessmentRequestValidationResult
    status: AssessmentExecutionStatus
    failure: Optional[AssessmentExecutionFailure]
    assessment_result: Optional[DeterministicAssessmentResult]
    assessment_evaluation_snapshot: Optional[
        AssessmentEvaluationSnapshot
    ] = None

    def __post_init__(self) -> None:
        if type(self.execution_input) is not AssessmentExecutionInput:
            raise ValueError(
                "execution_input must be an AssessmentExecutionInput"
            )
        if type(self.validation_result) is not AssessmentRequestValidationResult:
            raise ValueError(
                "validation_result must be an "
                "AssessmentRequestValidationResult"
            )
        if self.validation_result.request is not self.execution_input.request:
            raise ValueError(
                "validation_result must preserve the submitted request"
            )
        if (
            validate_assessment_request(self.execution_input.request)
            != self.validation_result
        ):
            raise ValueError(
                "validation_result must reconstruct from the submitted request"
            )
        if type(self.status) is not AssessmentExecutionStatus:
            raise ValueError("status must be an AssessmentExecutionStatus")

        if self.status is AssessmentExecutionStatus.INVALID_REQUEST:
            if (
                self.validation_result.validation_status != "invalid"
                or self.failure is not None
                or self.assessment_result is not None
                or self.assessment_evaluation_snapshot is not None
            ):
                raise ValueError(
                    "invalid execution requires only invalid validation data"
                )
            return

        if self.validation_result.validation_status != "valid":
            raise ValueError("noninvalid execution requires a valid request")

        if self.status is AssessmentExecutionStatus.COLLECTION_FAILED:
            if (
                type(self.failure) is not AssessmentExecutionFailure
                or self.assessment_result is not None
                or self.assessment_evaluation_snapshot is not None
            ):
                raise ValueError(
                    "failed execution requires one failure and no assessment"
                )
            expected_attempt_id = _collection_attempt_id(
                self.execution_input.request.assessment_id,
                self.failure.evidence_kind,
            )
            if self.failure.collection_attempt_id != expected_attempt_id:
                raise ValueError(
                    "failure collection_attempt_id is not deterministic"
                )
            return

        if self.status is AssessmentExecutionStatus.COMPLETE:
            if (
                self.failure is not None
                or type(self.assessment_result)
                is not DeterministicAssessmentResult
                or type(self.assessment_evaluation_snapshot)
                is not AssessmentEvaluationSnapshot
            ):
                raise ValueError(
                    "complete execution requires one assessment and no failure"
                )
            context = self.validation_result.context
            evaluated_at = self.assessment_result.evaluated_at
            _require_aware_datetime(
                "assessment_result.evaluated_at", evaluated_at
            )
            if (
                context is None
                or self.assessment_result.context != context
                or tuple(
                    record.evidence_kind
                    for record in self.assessment_result.evidence_records
                )
                != REQUIRED_EVIDENCE_KINDS
                or any(
                    record.assessment_id
                    != self.execution_input.request.assessment_id
                    for record in self.assessment_result.evidence_records
                )
                or any(
                    record.attempted_at.astimezone(timezone.utc)
                    > evaluated_at.astimezone(timezone.utc)
                    for record in self.assessment_result.evidence_records
                )
                or any(
                    metric.calculated_at is not evaluated_at
                    for metric in self.assessment_result.metric_results
                )
                or any(
                    finding.evaluated_at is not evaluated_at
                    for finding in self.assessment_result.policy_findings
                )
                or build_assessment_evaluation_snapshot(
                    self.assessment_result
                )
                != self.assessment_evaluation_snapshot
            ):
                raise ValueError(
                    "complete assessment does not match the execution input"
                )
            return

        raise ValueError("unsupported assessment execution status")


_COLLECTION_STEPS = (
    (
        EvidenceKind.REPOSITORY_ARCHIVED,
        collect_public_github_repository_metadata,
        persist_github_repository_metadata_collection,
    ),
    (
        EvidenceKind.LICENSE_STATUS,
        collect_public_github_license_status,
        persist_github_license_status_collection,
    ),
    (
        EvidenceKind.LATEST_COMMIT_TIMESTAMP,
        collect_public_github_latest_commit,
        persist_github_latest_commit_collection,
    ),
    (
        EvidenceKind.SECURITY_POLICY_PRESENT,
        collect_public_github_security_policy_presence,
        persist_github_security_policy_presence_collection,
    ),
)


def execute_assessment(
    database_path,
    execution_input: AssessmentExecutionInput,
) -> AssessmentExecutionResult:
    """Execute one validation-to-evaluation public GitHub assessment."""

    if type(execution_input) is not AssessmentExecutionInput:
        raise ValueError(
            "execution_input must be an AssessmentExecutionInput"
        )

    validation_result = validate_assessment_request(execution_input.request)
    if validation_result.validation_status == "invalid":
        return AssessmentExecutionResult(
            execution_input=execution_input,
            validation_result=validation_result,
            status=AssessmentExecutionStatus.INVALID_REQUEST,
            failure=None,
            assessment_result=None,
        )

    persist_valid_assessment_request(database_path, validation_result)
    repository_identity = validation_result.normalized_repository_identity
    if repository_identity is None:
        raise ValueError("valid request requires a repository identity")

    for evidence_kind, collector, persister in _COLLECTION_STEPS:
        collection_attempt_id = _collection_attempt_id(
            execution_input.request.assessment_id, evidence_kind
        )
        collection_input = GitHubRepositoryMetadataCollectionInput(
            assessment_id=execution_input.request.assessment_id,
            repository_identity=repository_identity,
            collection_attempt_id=collection_attempt_id,
            attempt_number=_ATTEMPT_NUMBER,
            attempted_at=execution_input.collection_attempted_at,
        )
        collection_result = collector(collection_input)
        if collection_result.evidence_kind is not evidence_kind:
            raise ValueError("collector returned the wrong evidence kind")
        evidence = persister(database_path, collection_result)

        if collection_result.outcome in (
            GitHubCollectionOutcome.AVAILABLE,
            GitHubCollectionOutcome.UNAVAILABLE,
        ):
            if (
                type(evidence) is not EvidenceRecord
                or evidence.evidence_kind is not evidence_kind
            ):
                raise ValueError(
                    "authoritative collection outcome requires evidence"
                )
            continue

        if evidence is not None or collection_result.error is None:
            raise ValueError(
                "failed collection outcome cannot contain evidence"
            )
        return AssessmentExecutionResult(
            execution_input=execution_input,
            validation_result=validation_result,
            status=AssessmentExecutionStatus.COLLECTION_FAILED,
            failure=AssessmentExecutionFailure(
                evidence_kind=evidence_kind,
                collection_attempt_id=collection_attempt_id,
                outcome=collection_result.outcome,
                error=collection_result.error,
            ),
            assessment_result=None,
        )

    assessment_id = execution_input.request.assessment_id
    try:
        snapshot = load_verified_assessment_evaluation_snapshot(
            database_path, assessment_id
        )
    except SQLitePersistenceError as exc:
        if exc.category != "evaluation_not_found":
            raise
        evaluated_at = _current_evaluation_time()
        _require_aware_datetime("evaluated_at", evaluated_at)
        assessment_result = evaluate_persisted_assessment(
            database_path,
            assessment_id,
            evaluated_at,
        )
        snapshot = persist_assessment_evaluation_snapshot(
            database_path, assessment_result
        )
    else:
        assessment_result = evaluate_persisted_assessment(
            database_path,
            assessment_id,
            snapshot.evaluated_at,
        )
    return AssessmentExecutionResult(
        execution_input=execution_input,
        validation_result=validation_result,
        status=AssessmentExecutionStatus.COMPLETE,
        failure=None,
        assessment_result=assessment_result,
        assessment_evaluation_snapshot=snapshot,
    )
