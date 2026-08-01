"""Transient orchestration for one complete deterministic assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .evaluation import REQUIRED_EVIDENCE_KINDS, evaluate_slice
from .models import (
    AssessmentContext,
    EvidenceRecord,
    MetricResult,
    PolicyFinding,
)


@dataclass(frozen=True)
class DeterministicAssessmentResult:
    """Complete transient inputs and outputs for one deterministic evaluation."""

    context: AssessmentContext
    evidence_records: tuple[EvidenceRecord, ...]
    metric_results: tuple[MetricResult, ...]
    policy_findings: tuple[PolicyFinding, ...]
    evaluated_at: datetime


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
