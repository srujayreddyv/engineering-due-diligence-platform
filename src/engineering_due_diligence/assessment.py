"""Transient orchestration for one complete deterministic assessment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .evaluation import REQUIRED_EVIDENCE_KINDS, evaluate_slice
from .models import (
    AssessmentContext,
    EvidenceKind,
    EvidenceRecord,
    MetricResult,
    PolicyFinding,
)
from .persistence import load_verified_assessment_evidence


ASSESSMENT_EVALUATION_SCHEMA_VERSION = "assessment-evaluation-snapshot.v1"
_ASSESSMENT_EVALUATION_ID_NAMESPACE = "assessment-evaluation-id.v1"
_ASSESSMENT_EVALUATION_ID_PREFIX = "assessment-evaluation-"


@dataclass(frozen=True)
class DeterministicAssessmentResult:
    """Complete transient inputs and outputs for one deterministic evaluation."""

    context: AssessmentContext
    evidence_records: tuple[EvidenceRecord, ...]
    metric_results: tuple[MetricResult, ...]
    policy_findings: tuple[PolicyFinding, ...]
    evaluated_at: datetime


@dataclass(frozen=True)
class AssessmentEvaluationSnapshot:
    """One immutable complete deterministic result prepared for review."""

    assessment_evaluation_id: str
    assessment_id: str
    evaluated_at: datetime
    evidence_references: tuple[tuple[EvidenceKind, str], ...]
    metric_results: tuple[MetricResult, ...]
    policy_findings: tuple[PolicyFinding, ...]
    evaluation_schema_version: str
    snapshot_json: str
    integrity_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "assessment_evaluation_id",
            "assessment_id",
            "evaluation_schema_version",
            "snapshot_json",
            "integrity_digest",
        ):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or not value
                or value != value.strip()
            ):
                raise ValueError(
                    "{} must be a nonempty unpadded string".format(field_name)
                )
        if (
            not isinstance(self.evaluated_at, datetime)
            or self.evaluated_at.tzinfo is None
            or self.evaluated_at.utcoffset() is None
        ):
            raise ValueError("evaluated_at must be timezone-aware")
        if self.evaluation_schema_version != ASSESSMENT_EVALUATION_SCHEMA_VERSION:
            raise ValueError("evaluation_schema_version is not supported")
        if (
            type(self.evidence_references) is not tuple
            or tuple(kind for kind, _ in self.evidence_references)
            != REQUIRED_EVIDENCE_KINDS
            or any(
                type(kind) is not EvidenceKind
                or type(evidence_id) is not str
                or not evidence_id
                or evidence_id != evidence_id.strip()
                for kind, evidence_id in self.evidence_references
            )
            or len({item[1] for item in self.evidence_references})
            != len(self.evidence_references)
        ):
            raise ValueError(
                "evidence_references must contain the four canonical kinds"
            )
        if (
            type(self.metric_results) is not tuple
            or len(self.metric_results) != 4
            or not all(type(item) is MetricResult for item in self.metric_results)
            or type(self.policy_findings) is not tuple
            or len(self.policy_findings) != 4
            or not all(
                type(item) is PolicyFinding for item in self.policy_findings
            )
        ):
            raise ValueError(
                "snapshot requires four metrics and four policy findings"
            )
        if any(
            item.assessment_id != self.assessment_id
            or item.calculated_at.isoformat() != self.evaluated_at.isoformat()
            for item in self.metric_results
        ) or any(
            item.assessment_id != self.assessment_id
            or item.evaluated_at.isoformat() != self.evaluated_at.isoformat()
            for item in self.policy_findings
        ):
            raise ValueError("snapshot results must belong to one evaluation")
        canonical_bytes = canonical_assessment_evaluation_payload_bytes(
            self.assessment_id,
            self.evaluated_at,
            self.evidence_references,
            self.metric_results,
            self.policy_findings,
            self.evaluation_schema_version,
        )
        if self.snapshot_json.encode("utf-8") != canonical_bytes:
            raise ValueError("snapshot_json is not the canonical payload")
        if self.integrity_digest != hashlib.sha256(canonical_bytes).hexdigest():
            raise ValueError("integrity_digest does not match snapshot_json")
        if self.assessment_evaluation_id != assessment_evaluation_id(
            canonical_bytes
        ):
            raise ValueError(
                "assessment_evaluation_id does not match the canonical payload"
            )


def _metric_payload(metric: MetricResult) -> dict[str, object]:
    return {
        "metric_result_id": metric.metric_result_id,
        "assessment_id": metric.assessment_id,
        "calculation_attempt_id": metric.calculation_attempt_id,
        "metric_name": metric.metric_name,
        "metric_definition_version": metric.metric_definition_version,
        "input_evidence_ids": list(metric.input_evidence_ids),
        "input_digest": metric.input_digest,
        "calculated_at": metric.calculated_at.isoformat(),
        "result_status": metric.result_status.value,
        "input_sufficiency": metric.input_sufficiency.value,
        "metric_schema_version": metric.metric_schema_version,
        "value": metric.value,
        "unit": metric.unit,
        "reason_code": metric.reason_code,
    }


def _policy_finding_payload(finding: PolicyFinding) -> dict[str, object]:
    return {
        "policy_finding_id": finding.policy_finding_id,
        "assessment_id": finding.assessment_id,
        "policy_id": finding.policy_id,
        "policy_version": finding.policy_version,
        "policy_engine_version": finding.policy_engine_version,
        "policy_evaluation_id": finding.policy_evaluation_id,
        "requirement_id": finding.requirement_id,
        "requirement_version": finding.requirement_version,
        "outcome": finding.outcome.value,
        "input_evidence_ids": list(finding.input_evidence_ids),
        "input_metric_result_ids": list(finding.input_metric_result_ids),
        "deterministic_reason": finding.deterministic_reason,
        "evaluated_at": finding.evaluated_at.isoformat(),
        "finding_schema_version": finding.finding_schema_version,
        "condition_template": finding.condition_template,
    }


def canonical_assessment_evaluation_payload_bytes(
    assessment_id: str,
    evaluated_at: datetime,
    evidence_references: tuple[tuple[EvidenceKind, str], ...],
    metric_results: tuple[MetricResult, ...],
    policy_findings: tuple[PolicyFinding, ...],
    evaluation_schema_version: str = ASSESSMENT_EVALUATION_SCHEMA_VERSION,
) -> bytes:
    """Return the locked canonical evaluation identity payload bytes."""

    payload = {
        "assessment_id": assessment_id,
        "evaluated_at": evaluated_at.isoformat(),
        "evaluation_schema_version": evaluation_schema_version,
        "evidence_references": [
            {"evidence_kind": kind.value, "evidence_id": evidence_id}
            for kind, evidence_id in evidence_references
        ],
        "metric_results": [_metric_payload(item) for item in metric_results],
        "policy_findings": [
            _policy_finding_payload(item) for item in policy_findings
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def assessment_evaluation_id(canonical_payload_bytes: bytes) -> str:
    """Derive the locked namespaced assessment-evaluation identity."""

    if type(canonical_payload_bytes) is not bytes:
        raise ValueError("canonical_payload_bytes must be bytes")
    material = (
        _ASSESSMENT_EVALUATION_ID_NAMESPACE.encode("utf-8")
        + b"\0"
        + canonical_payload_bytes
    )
    return _ASSESSMENT_EVALUATION_ID_PREFIX + hashlib.sha256(material).hexdigest()


def build_assessment_evaluation_snapshot(
    result: DeterministicAssessmentResult,
) -> AssessmentEvaluationSnapshot:
    """Build the exact immutable review snapshot for one complete result."""

    if type(result) is not DeterministicAssessmentResult:
        raise ValueError("result must be a DeterministicAssessmentResult")
    evidence_references = tuple(
        (record.evidence_kind, record.evidence_id)
        for record in result.evidence_records
    )
    canonical_bytes = canonical_assessment_evaluation_payload_bytes(
        result.context.assessment_id,
        result.evaluated_at,
        evidence_references,
        result.metric_results,
        result.policy_findings,
    )
    return AssessmentEvaluationSnapshot(
        assessment_evaluation_id=assessment_evaluation_id(canonical_bytes),
        assessment_id=result.context.assessment_id,
        evaluated_at=result.evaluated_at,
        evidence_references=evidence_references,
        metric_results=result.metric_results,
        policy_findings=result.policy_findings,
        evaluation_schema_version=ASSESSMENT_EVALUATION_SCHEMA_VERSION,
        snapshot_json=canonical_bytes.decode("utf-8"),
        integrity_digest=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def evaluate_assessment(
    context: AssessmentContext,
    evidence_records: Sequence[EvidenceRecord],
    evaluated_at: datetime,
) -> DeterministicAssessmentResult:
    """Evaluate one fixed evidence set and return only a complete result."""

    evidence_snapshot = tuple(evidence_records)
    metric_results, policy_findings = evaluate_slice(
        context, evidence_snapshot, evaluated_at
    )
    evidence_by_kind = {
        record.evidence_kind: record for record in evidence_snapshot
    }
    canonical_evidence = tuple(
        evidence_by_kind[kind] for kind in REQUIRED_EVIDENCE_KINDS
    )
    return DeterministicAssessmentResult(
        context=context,
        evidence_records=canonical_evidence,
        metric_results=metric_results,
        policy_findings=policy_findings,
        evaluated_at=evaluated_at,
    )


def evaluate_persisted_assessment(
    database_path,
    assessment_id,
    evaluated_at,
) -> DeterministicAssessmentResult:
    """Evaluate one complete evidence set verified from durable SQLite."""

    verified = load_verified_assessment_evidence(
        database_path, assessment_id
    )
    context = verified.validation_result.context
    if context is None:
        raise ValueError("verified assessment evidence requires a context")
    return evaluate_assessment(
        context,
        verified.evidence_records,
        evaluated_at,
    )
