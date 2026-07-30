"""Pure metric calculation and policy evaluation for the first slice."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .models import (
    AssessmentContext,
    Criticality,
    Environment,
    EvidenceKind,
    EvidenceOutcome,
    EvidenceRecord,
    FreshnessStatus,
    InputSufficiency,
    LicenseStatus,
    MetricResult,
    MetricStatus,
    PolicyFinding,
    PolicyOutcome,
    RiskTolerance,
)


METRIC_SCHEMA_VERSION = "metric-result.v1"
FINDING_SCHEMA_VERSION = "policy-finding.v1"
POLICY_ID = "repository-adoption"
POLICY_VERSION = "repository-adoption.prototype-v2"
POLICY_ENGINE_VERSION = "deterministic-policy-engine.v1"
PROVISIONAL_STRICT_CONTEXT_LIFETIME_DAYS = 180
PROVISIONAL_STRICT_COMMIT_RECENCY_DAYS = 180
PROVISIONAL_BROADER_COMMIT_RECENCY_DAYS = 730

METRIC_VERSIONS = {
    "repository_archived": "repository-archived.v1",
    "license_present": "license-present.v1",
    "days_since_latest_commit": "days-since-latest-commit.v1",
    "security_policy_present": "security-policy-present.v1",
}

REQUIREMENT_VERSIONS = {
    "repository_not_archived": "repository-not-archived.v1",
    "license_declared": "license-declared.v1",
    "commit_recency": "commit-recency.prototype-v2",
    "security_policy": "security-policy.v1",
}

REQUIRED_EVIDENCE_KINDS = (
    EvidenceKind.REPOSITORY_ARCHIVED,
    EvidenceKind.LICENSE_STATUS,
    EvidenceKind.LATEST_COMMIT_TIMESTAMP,
    EvidenceKind.SECURITY_POLICY_PRESENT,
)

METRIC_TO_EVIDENCE_KIND = {
    "repository_archived": EvidenceKind.REPOSITORY_ARCHIVED,
    "license_present": EvidenceKind.LICENSE_STATUS,
    "days_since_latest_commit": EvidenceKind.LATEST_COMMIT_TIMESTAMP,
    "security_policy_present": EvidenceKind.SECURITY_POLICY_PRESENT,
}

REQUIREMENT_TO_METRIC = {
    "repository_not_archived": "repository_archived",
    "license_declared": "license_present",
    "commit_recency": "days_since_latest_commit",
    "security_policy": "security_policy_present",
}


class SliceEvaluationError(ValueError):
    """Base class for deterministic slice validation failures."""


class MissingEvidenceRecordError(SliceEvaluationError):
    """Raised before calculation when a required evidence record is absent."""


class InvalidEvidenceSetError(SliceEvaluationError):
    """Raised before calculation when evidence cannot belong to this assessment."""


class InvalidMetricSetError(SliceEvaluationError):
    """Raised before policy evaluation when metric traceability is invalid."""


class DeterministicCalculationError(SliceEvaluationError):
    """Raised when available evidence cannot yield a valid deterministic value."""


def _normalize(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return value


def _digest(value: object) -> str:
    canonical = json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _stable_id(prefix: str, value: object) -> str:
    return "{}-{}".format(prefix, _digest(value)[:24])


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SliceEvaluationError("{} must be timezone-aware".format(field_name))


def _utc_instant(field_name: str, value: datetime) -> datetime:
    _require_aware_datetime(field_name, value)
    return value.astimezone(timezone.utc)


def _index_evidence(
    context: AssessmentContext, evidence_records: Sequence[EvidenceRecord]
) -> Dict[EvidenceKind, EvidenceRecord]:
    by_kind: Dict[EvidenceKind, EvidenceRecord] = {}
    evidence_ids = set()
    for record in evidence_records:
        if record.assessment_id != context.assessment_id:
            raise InvalidEvidenceSetError(
                "evidence {} belongs to another assessment".format(
                    record.evidence_id
                )
            )
        if record.raw_snapshot is not None:
            expected_digest = hashlib.sha256(
                record.raw_snapshot.encode("utf-8")
            ).hexdigest()
            if record.integrity_digest != expected_digest:
                raise InvalidEvidenceSetError(
                    "evidence {} integrity_digest does not match raw_snapshot".format(
                        record.evidence_id
                    )
                )
        if record.evidence_id in evidence_ids:
            raise InvalidEvidenceSetError(
                "duplicate evidence_id {}".format(record.evidence_id)
            )
        if record.evidence_kind in by_kind:
            raise InvalidEvidenceSetError(
                "multiple current records for {}".format(record.evidence_kind.value)
            )
        evidence_ids.add(record.evidence_id)
        by_kind[record.evidence_kind] = record

    missing = [kind.value for kind in REQUIRED_EVIDENCE_KINDS if kind not in by_kind]
    if missing:
        raise MissingEvidenceRecordError(
            "required EvidenceRecord entries are absent: {}".format(
                ", ".join(missing)
            )
        )
    return by_kind


def _evidence_input_digest(record: EvidenceRecord) -> str:
    return _digest(
        {
            "evidence_id": record.evidence_id,
            "evidence_kind": record.evidence_kind,
            "collection_outcome": record.collection_outcome,
            "collector_version": record.collector_version,
            "evidence_schema_version": record.evidence_schema_version,
            "freshness_status_at_collection": record.freshness_status_at_collection,
            "integrity_digest": record.integrity_digest,
            "value": record.value,
            "unavailability_reason": record.unavailability_reason,
            "error_category": record.error_category,
        }
    )


def _is_usable_evidence(record: EvidenceRecord) -> bool:
    return (
        record.collection_outcome is EvidenceOutcome.AVAILABLE
        and record.freshness_status_at_collection
        not in (FreshnessStatus.STALE, FreshnessStatus.UNKNOWN)
    )


def _metric_result(
    context: AssessmentContext,
    record: EvidenceRecord,
    metric_name: str,
    calculated_at: datetime,
    value: Optional[object],
    unit: Optional[str],
) -> MetricResult:
    input_digest = _evidence_input_digest(record)
    identity_input = {
        "assessment_id": context.assessment_id,
        "metric_name": metric_name,
        "metric_definition_version": METRIC_VERSIONS[metric_name],
        "input_digest": input_digest,
        "calculated_at": calculated_at,
    }
    attempt_id = _stable_id("calc", identity_input)
    result_id = _stable_id("metric", identity_input)

    if not _is_usable_evidence(record):
        if record.collection_outcome is EvidenceOutcome.AVAILABLE:
            reason_code = "evidence_freshness:{}".format(
                record.freshness_status_at_collection.value
            )
        else:
            reason_code = "evidence_unavailable:{}".format(
                record.unavailability_reason
            )
        return MetricResult(
            metric_result_id=result_id,
            assessment_id=context.assessment_id,
            calculation_attempt_id=attempt_id,
            metric_name=metric_name,
            metric_definition_version=METRIC_VERSIONS[metric_name],
            input_evidence_ids=(record.evidence_id,),
            input_digest=input_digest,
            calculated_at=calculated_at,
            result_status=MetricStatus.UNAVAILABLE,
            input_sufficiency=InputSufficiency.INSUFFICIENT,
            metric_schema_version=METRIC_SCHEMA_VERSION,
            reason_code=reason_code,
        )

    return MetricResult(
        metric_result_id=result_id,
        assessment_id=context.assessment_id,
        calculation_attempt_id=attempt_id,
        metric_name=metric_name,
        metric_definition_version=METRIC_VERSIONS[metric_name],
        input_evidence_ids=(record.evidence_id,),
        input_digest=input_digest,
        calculated_at=calculated_at,
        result_status=MetricStatus.AVAILABLE,
        input_sufficiency=InputSufficiency.SUFFICIENT,
        metric_schema_version=METRIC_SCHEMA_VERSION,
        value=value,
        unit=unit,
    )


def calculate_metrics(
    context: AssessmentContext,
    evidence_records: Sequence[EvidenceRecord],
    calculated_at: datetime,
) -> Tuple[MetricResult, ...]:
    """Calculate all four metrics or raise before returning any result set."""

    _require_aware_datetime("calculated_at", calculated_at)
    evidence = _index_evidence(context, evidence_records)
    calculation_instant = _utc_instant("calculated_at", calculated_at)
    for record in evidence.values():
        if _utc_instant(
            "EvidenceRecord.attempted_at", record.attempted_at
        ) > calculation_instant:
            raise InvalidEvidenceSetError(
                "evidence {} attempted_at is after calculated_at".format(
                    record.evidence_id
                )
            )

    archived_record = evidence[EvidenceKind.REPOSITORY_ARCHIVED]
    license_record = evidence[EvidenceKind.LICENSE_STATUS]
    commit_record = evidence[EvidenceKind.LATEST_COMMIT_TIMESTAMP]
    security_record = evidence[EvidenceKind.SECURITY_POLICY_PRESENT]

    archived_value = (
        archived_record.value
        if _is_usable_evidence(archived_record)
        else None
    )
    license_value = (
        license_record.value is LicenseStatus.PRESENT
        if _is_usable_evidence(license_record)
        else None
    )
    security_value = (
        security_record.value
        if _is_usable_evidence(security_record)
        else None
    )

    commit_age_days: Optional[int] = None
    if commit_record.collection_outcome is EvidenceOutcome.AVAILABLE:
        commit_timestamp = commit_record.value
        if not isinstance(commit_timestamp, datetime):
            raise DeterministicCalculationError(
                "latest commit evidence has an invalid value type"
            )
        delta = calculation_instant - _utc_instant(
            "latest commit timestamp", commit_timestamp
        )
        if delta.total_seconds() < 0:
            raise DeterministicCalculationError(
                "latest commit timestamp cannot be after calculated_at"
            )
        if _is_usable_evidence(commit_record):
            commit_age_days = delta.days

    return (
        _metric_result(
            context,
            archived_record,
            "repository_archived",
            calculated_at,
            archived_value,
            "boolean" if archived_value is not None else None,
        ),
        _metric_result(
            context,
            license_record,
            "license_present",
            calculated_at,
            license_value,
            "boolean" if license_value is not None else None,
        ),
        _metric_result(
            context,
            commit_record,
            "days_since_latest_commit",
            calculated_at,
            commit_age_days,
            "days" if commit_age_days is not None else None,
        ),
        _metric_result(
            context,
            security_record,
            "security_policy_present",
            calculated_at,
            security_value,
            "boolean" if security_value is not None else None,
        ),
    )


def _index_metrics(
    context: AssessmentContext,
    evidence: Mapping[EvidenceKind, EvidenceRecord],
    metric_results: Sequence[MetricResult],
    evaluated_at: datetime,
) -> Dict[str, MetricResult]:
    by_name: Dict[str, MetricResult] = {}
    canonical_by_timestamp: Dict[datetime, Dict[str, MetricResult]] = {}
    evidence_ids = {record.evidence_id for record in evidence.values()}
    policy_evaluation_instant = _utc_instant("evaluated_at", evaluated_at)
    canonical_evidence = tuple(
        evidence[kind] for kind in REQUIRED_EVIDENCE_KINDS
    )
    for result in metric_results:
        if _utc_instant(
            "MetricResult.calculated_at", result.calculated_at
        ) > policy_evaluation_instant:
            raise InvalidMetricSetError(
                "metric {} calculated_at is after policy evaluated_at".format(
                    result.metric_result_id
                )
            )
        if result.assessment_id != context.assessment_id:
            raise InvalidMetricSetError(
                "metric {} belongs to another assessment".format(
                    result.metric_result_id
                )
            )
        if result.metric_name in by_name:
            raise InvalidMetricSetError(
                "multiple current results for {}".format(result.metric_name)
            )
        if not set(result.input_evidence_ids).issubset(evidence_ids):
            raise InvalidMetricSetError(
                "metric {} references unknown evidence".format(
                    result.metric_result_id
                )
            )
        expected_version = METRIC_VERSIONS.get(result.metric_name)
        if result.metric_definition_version != expected_version:
            raise InvalidMetricSetError(
                "metric {} has an inapplicable definition version".format(
                    result.metric_result_id
                )
            )
        expected_record = evidence[METRIC_TO_EVIDENCE_KIND[result.metric_name]]
        if result.input_evidence_ids != (expected_record.evidence_id,):
            raise InvalidMetricSetError(
                "metric {} does not reference its required evidence".format(
                    result.metric_result_id
                )
            )
        if result.calculated_at not in canonical_by_timestamp:
            canonical_by_timestamp[result.calculated_at] = {
                canonical.metric_name: canonical
                for canonical in calculate_metrics(
                    context, canonical_evidence, result.calculated_at
                )
            }
        canonical_result = canonical_by_timestamp[result.calculated_at][
            result.metric_name
        ]
        if result != canonical_result:
            raise InvalidMetricSetError(
                "metric {} does not match deterministic recalculation".format(
                    result.metric_result_id
                )
            )
        by_name[result.metric_name] = result

    missing = [
        metric_name
        for metric_name in METRIC_TO_EVIDENCE_KIND
        if metric_name not in by_name
    ]
    if missing:
        raise InvalidMetricSetError(
            "required MetricResult entries are absent: {}".format(
                ", ".join(missing)
            )
        )
    return by_name


def _requires_strict_controls(context: AssessmentContext) -> bool:
    return (
        context.environment is Environment.PRODUCTION
        or context.criticality is Criticality.CRITICAL
        or context.expected_lifetime_days
        > PROVISIONAL_STRICT_CONTEXT_LIFETIME_DAYS
        or context.risk_tolerance is RiskTolerance.LOW
    )


def _policy_outcome(
    context: AssessmentContext,
    requirement_id: str,
    metric: MetricResult,
    evidence_record: EvidenceRecord,
    evaluated_at: datetime,
) -> Tuple[PolicyOutcome, str, Optional[str]]:
    if metric.result_status is MetricStatus.UNAVAILABLE:
        return (
            PolicyOutcome.NOT_EVALUABLE,
            "required_metric_unavailable:{}:{}".format(
                metric.metric_name, metric.reason_code
            ),
            None,
        )

    if requirement_id == "repository_not_archived":
        if type(metric.value) is not bool:
            raise InvalidMetricSetError(
                "repository_not_archived requires a boolean metric"
            )
        if metric.value is True:
            return PolicyOutcome.FAIL, "repository_is_archived", None
        return PolicyOutcome.PASS, "repository_is_not_archived", None

    if requirement_id == "license_declared":
        if type(metric.value) is not bool:
            raise InvalidMetricSetError(
                "license_declared requires a boolean metric"
            )
        if metric.value is True:
            return PolicyOutcome.PASS, "license_is_declared", None
        if _requires_strict_controls(context):
            return PolicyOutcome.FAIL, "license_is_not_declared", None
        return (
            PolicyOutcome.CONDITION_REQUIRED,
            "prototype_requires_license_resolution_before_broader_use",
            "Resolve and document the license before use expands beyond the prototype.",
        )

    if requirement_id == "commit_recency":
        if not isinstance(metric.value, int) or isinstance(metric.value, bool):
            raise InvalidMetricSetError("commit_recency requires an integer metric")
        commit_timestamp = evidence_record.value
        if not isinstance(commit_timestamp, datetime):
            raise InvalidMetricSetError(
                "commit_recency requires timestamp evidence"
            )
        elapsed_duration = _utc_instant(
            "evaluated_at", evaluated_at
        ) - _utc_instant("latest commit timestamp", commit_timestamp)
        if elapsed_duration < timedelta(0):
            raise InvalidMetricSetError(
                "latest commit timestamp cannot be after policy evaluated_at"
            )
        threshold_days = (
            PROVISIONAL_STRICT_COMMIT_RECENCY_DAYS
            if _requires_strict_controls(context)
            else PROVISIONAL_BROADER_COMMIT_RECENCY_DAYS
        )
        if elapsed_duration <= timedelta(days=threshold_days):
            return (
                PolicyOutcome.PASS,
                "latest_commit_within_{}_days".format(threshold_days),
                None,
            )
        return (
            PolicyOutcome.FAIL,
            "latest_commit_older_than_{}_days".format(threshold_days),
            None,
        )

    if requirement_id == "security_policy":
        if type(metric.value) is not bool:
            raise InvalidMetricSetError(
                "security_policy requires a boolean metric"
            )
        if metric.value is True:
            return PolicyOutcome.PASS, "security_policy_is_present", None
        if _requires_strict_controls(context):
            return PolicyOutcome.FAIL, "security_policy_is_absent", None
        return (
            PolicyOutcome.CONDITION_REQUIRED,
            "prototype_requires_security_contact_plan",
            "Record a security contact and escalation plan for prototype use.",
        )

    raise InvalidMetricSetError(
        "unknown policy requirement {}".format(requirement_id)
    )


def evaluate_policy(
    context: AssessmentContext,
    evidence_records: Sequence[EvidenceRecord],
    metric_results: Sequence[MetricResult],
    evaluated_at: datetime,
) -> Tuple[PolicyFinding, ...]:
    """Evaluate every requirement against one context and exact input set."""

    _require_aware_datetime("evaluated_at", evaluated_at)
    evidence = _index_evidence(context, evidence_records)
    metrics = _index_metrics(
        context, evidence, metric_results, evaluated_at
    )
    evaluation_input = {
        "assessment_id": context.assessment_id,
        "repository_identity": context.repository_identity,
        "environment": context.environment,
        "criticality": context.criticality,
        "expected_lifetime_days": context.expected_lifetime_days,
        "risk_tolerance": context.risk_tolerance,
        "policy_version": POLICY_VERSION,
        "policy_engine_version": POLICY_ENGINE_VERSION,
        "metric_result_ids": tuple(
            sorted(result.metric_result_id for result in metrics.values())
        ),
        "evaluated_at": evaluated_at,
    }
    policy_evaluation_id = _stable_id("policy-eval", evaluation_input)

    findings = []
    for requirement_id, metric_name in REQUIREMENT_TO_METRIC.items():
        metric = metrics[metric_name]
        evidence_record = evidence[METRIC_TO_EVIDENCE_KIND[metric_name]]
        outcome, reason, condition = _policy_outcome(
            context,
            requirement_id,
            metric,
            evidence_record,
            evaluated_at,
        )
        finding_identity = {
            "policy_evaluation_id": policy_evaluation_id,
            "requirement_id": requirement_id,
            "requirement_version": REQUIREMENT_VERSIONS[requirement_id],
            "metric_result_id": metric.metric_result_id,
            "outcome": outcome,
            "reason": reason,
        }
        findings.append(
            PolicyFinding(
                policy_finding_id=_stable_id("finding", finding_identity),
                assessment_id=context.assessment_id,
                policy_id=POLICY_ID,
                policy_version=POLICY_VERSION,
                policy_engine_version=POLICY_ENGINE_VERSION,
                policy_evaluation_id=policy_evaluation_id,
                requirement_id=requirement_id,
                requirement_version=REQUIREMENT_VERSIONS[requirement_id],
                outcome=outcome,
                input_evidence_ids=metric.input_evidence_ids,
                input_metric_result_ids=(metric.metric_result_id,),
                deterministic_reason=reason,
                evaluated_at=evaluated_at,
                finding_schema_version=FINDING_SCHEMA_VERSION,
                condition_template=condition,
            )
        )
    return tuple(findings)


def evaluate_slice(
    context: AssessmentContext,
    evidence_records: Sequence[EvidenceRecord],
    evaluated_at: datetime,
) -> Tuple[Tuple[MetricResult, ...], Tuple[PolicyFinding, ...]]:
    """Run the pure slice and return only complete metric and finding sets."""

    metrics = calculate_metrics(context, evidence_records, evaluated_at)
    findings = evaluate_policy(context, evidence_records, metrics, evaluated_at)
    return metrics, findings
