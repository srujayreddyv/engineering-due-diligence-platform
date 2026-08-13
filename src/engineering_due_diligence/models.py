"""Immutable types for the first deterministic assessment slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple, Union


class Criticality(str, Enum):
    LOW = "low"
    CRITICAL = "critical"


class Environment(str, Enum):
    INTERNAL = "internal"
    PRODUCTION = "production"


class RiskTolerance(str, Enum):
    TOLERANT = "tolerant"
    LOW = "low"


class EvidenceKind(str, Enum):
    REPOSITORY_ARCHIVED = "repository_archived"
    LICENSE_STATUS = "license_status"
    LATEST_COMMIT_TIMESTAMP = "latest_commit_timestamp"
    SECURITY_POLICY_PRESENT = "security_policy_present"


class EvidenceOutcome(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FreshnessStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class LicenseStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"


class MetricStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class InputSufficiency(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class PolicyOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CONDITION_REQUIRED = "condition_required"
    INVESTIGATION_REQUIRED = "investigation_required"
    NOT_EVALUABLE = "not_evaluable"


class HumanDecisionDisposition(str, Enum):
    """The four human-owned repository adoption dispositions."""

    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    NEEDS_MORE_INFORMATION = "needs_more_information"
    REJECT = "reject"


EvidenceValue = Union[bool, datetime, LicenseStatus]
MetricValue = Union[bool, int, str]
Provenance = Tuple[Tuple[str, str], ...]


def _require_text(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError("{} must not be empty".format(field_name))


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field_name))


def _parse_canonical_fixture_value(
    evidence_kind: EvidenceKind, raw_snapshot: str
) -> EvidenceValue:
    try:
        snapshot = json.loads(raw_snapshot)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "raw_snapshot must be valid canonical fixture JSON"
        ) from exc

    if type(snapshot) is not dict or set(snapshot) != {"value"}:
        raise ValueError(
            "raw_snapshot must contain exactly one value field"
        )
    raw_value = snapshot["value"]

    if evidence_kind in (
        EvidenceKind.REPOSITORY_ARCHIVED,
        EvidenceKind.SECURITY_POLICY_PRESENT,
    ):
        if type(raw_value) is not bool:
            raise ValueError(
                "{} raw value must be a JSON boolean".format(
                    evidence_kind.value
                )
            )
        return raw_value

    if evidence_kind is EvidenceKind.LICENSE_STATUS:
        if type(raw_value) is not str:
            raise ValueError("license_status raw value must be a string")
        try:
            return LicenseStatus(raw_value)
        except ValueError as exc:
            raise ValueError(
                "license_status raw value must be present or absent"
            ) from exc

    if evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
        if type(raw_value) is not str:
            raise ValueError(
                "latest_commit_timestamp raw value must be an ISO 8601 string"
            )
        try:
            parsed_timestamp = datetime.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError(
                "latest_commit_timestamp raw value must be valid ISO 8601"
            ) from exc
        _require_aware_datetime(
            "latest commit timestamp raw value", parsed_timestamp
        )
        return parsed_timestamp

    raise ValueError("unsupported local fixture evidence kind")


@dataclass(frozen=True)
class AssessmentContext:
    """Validated context used by deterministic policy evaluation."""

    assessment_id: str
    repository_identity: str
    intended_use: str
    environment: Environment
    criticality: Criticality
    expected_lifetime_days: int
    risk_tolerance: RiskTolerance

    def __post_init__(self) -> None:
        _require_text("assessment_id", self.assessment_id)
        _require_text("repository_identity", self.repository_identity)
        _require_text("intended_use", self.intended_use)
        if not isinstance(self.environment, Environment):
            raise ValueError("environment must be an Environment")
        if not isinstance(self.criticality, Criticality):
            raise ValueError("criticality must be a Criticality")
        if not isinstance(self.risk_tolerance, RiskTolerance):
            raise ValueError("risk_tolerance must be a RiskTolerance")
        if (
            type(self.expected_lifetime_days) is not int
            or self.expected_lifetime_days <= 0
        ):
            raise ValueError("expected_lifetime_days must be positive")


@dataclass(frozen=True)
class EvidenceRecord:
    """A complete available or unavailable local evidence outcome."""

    evidence_id: str
    assessment_id: str
    evidence_kind: EvidenceKind
    source_identity: str
    collector_name: str
    collector_version: str
    collection_attempt_id: str
    attempt_number: int
    attempted_at: datetime
    collection_outcome: EvidenceOutcome
    freshness_basis: str
    freshness_status_at_collection: FreshnessStatus
    evidence_schema_version: str
    provenance: Provenance
    value: Optional[EvidenceValue] = None
    raw_snapshot: Optional[str] = None
    integrity_digest: Optional[str] = None
    unavailability_reason: Optional[str] = None
    error_category: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "assessment_id",
            "source_identity",
            "collector_name",
            "collector_version",
            "collection_attempt_id",
            "freshness_basis",
            "evidence_schema_version",
        ):
            _require_text(field_name, getattr(self, field_name))
        if not isinstance(self.evidence_kind, EvidenceKind):
            raise ValueError("evidence_kind must be an EvidenceKind")
        if not isinstance(self.collection_outcome, EvidenceOutcome):
            raise ValueError("collection_outcome must be an EvidenceOutcome")
        if not isinstance(
            self.freshness_status_at_collection, FreshnessStatus
        ):
            raise ValueError(
                "freshness_status_at_collection must be a FreshnessStatus"
            )
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise ValueError("attempt_number must be at least one")
        _require_aware_datetime("attempted_at", self.attempted_at)
        if not self.provenance:
            raise ValueError("provenance must identify the fixture source")
        for key, value in self.provenance:
            _require_text("provenance key", key)
            _require_text("provenance value", value)

        if self.collection_outcome is EvidenceOutcome.AVAILABLE:
            if self.value is None:
                raise ValueError("available evidence requires a typed value")
            if self.raw_snapshot is None or self.integrity_digest is None:
                raise ValueError(
                    "available evidence requires a raw snapshot and integrity digest"
                )
            expected_digest = hashlib.sha256(
                self.raw_snapshot.encode("utf-8")
            ).hexdigest()
            if self.integrity_digest != expected_digest:
                raise ValueError("integrity_digest does not match raw_snapshot")
            if self.unavailability_reason is not None or self.error_category is not None:
                raise ValueError(
                    "available evidence cannot contain unavailability fields"
                )
            self._validate_available_value()
            self._validate_snapshot_consistency()
            return

        if self.value is not None:
            raise ValueError("unavailable evidence cannot contain a value")
        if self.raw_snapshot is not None or self.integrity_digest is not None:
            raise ValueError("unavailable evidence cannot contain a source snapshot")
        if not self.unavailability_reason or not self.error_category:
            raise ValueError(
                "unavailable evidence requires a reason and error category"
            )

    def _validate_available_value(self) -> None:
        if self.evidence_kind in (
            EvidenceKind.REPOSITORY_ARCHIVED,
            EvidenceKind.SECURITY_POLICY_PRESENT,
        ):
            if type(self.value) is not bool:
                raise ValueError(
                    "{} evidence requires a boolean value".format(
                        self.evidence_kind.value
                    )
                )
        elif self.evidence_kind is EvidenceKind.LICENSE_STATUS:
            if not isinstance(self.value, LicenseStatus):
                raise ValueError("license_status evidence requires LicenseStatus")
        elif self.evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
            if not isinstance(self.value, datetime):
                raise ValueError(
                    "latest_commit_timestamp evidence requires datetime"
                )
            _require_aware_datetime("latest commit timestamp", self.value)

    def _validate_snapshot_consistency(self) -> None:
        if not isinstance(self.raw_snapshot, str):
            raise ValueError("raw_snapshot must be a string")
        snapshot_value = _parse_canonical_fixture_value(
            self.evidence_kind, self.raw_snapshot
        )
        if self.evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP:
            normalized_timestamp = self.value
            if not isinstance(normalized_timestamp, datetime):
                raise ValueError(
                    "latest_commit_timestamp evidence requires datetime"
                )
            matches = snapshot_value.astimezone(
                timezone.utc
            ) == normalized_timestamp.astimezone(timezone.utc)
        else:
            matches = snapshot_value == self.value
        if not matches:
            raise ValueError(
                "normalized {} value does not match canonical raw snapshot".format(
                    self.evidence_kind.value
                )
            )


@dataclass(frozen=True)
class MetricResult:
    """A complete deterministic result derived from identified evidence."""

    metric_result_id: str
    assessment_id: str
    calculation_attempt_id: str
    metric_name: str
    metric_definition_version: str
    input_evidence_ids: Tuple[str, ...]
    input_digest: str
    calculated_at: datetime
    result_status: MetricStatus
    input_sufficiency: InputSufficiency
    metric_schema_version: str
    value: Optional[MetricValue] = None
    unit: Optional[str] = None
    reason_code: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in (
            "metric_result_id",
            "assessment_id",
            "calculation_attempt_id",
            "metric_name",
            "metric_definition_version",
            "input_digest",
            "metric_schema_version",
        ):
            _require_text(field_name, getattr(self, field_name))
        if not self.input_evidence_ids:
            raise ValueError("MetricResult requires identified evidence inputs")
        if len(set(self.input_evidence_ids)) != len(self.input_evidence_ids):
            raise ValueError("input_evidence_ids must not contain duplicates")
        _require_aware_datetime("calculated_at", self.calculated_at)
        if not isinstance(self.result_status, MetricStatus):
            raise ValueError("result_status must be a MetricStatus")
        if not isinstance(self.input_sufficiency, InputSufficiency):
            raise ValueError("input_sufficiency must be an InputSufficiency")

        if self.result_status is MetricStatus.AVAILABLE:
            if self.value is None or self.unit is None:
                raise ValueError("available metric requires a value and unit")
            if self.input_sufficiency is not InputSufficiency.SUFFICIENT:
                raise ValueError("available metric requires sufficient inputs")
            if self.reason_code is not None:
                raise ValueError("available metric cannot contain a failure reason")
            return

        if self.value is not None or self.unit is not None:
            raise ValueError("unavailable metric cannot contain a placeholder value")
        if self.input_sufficiency is not InputSufficiency.INSUFFICIENT:
            raise ValueError("unavailable metric requires insufficient inputs")
        if not self.reason_code:
            raise ValueError("unavailable metric requires a reason code")


@dataclass(frozen=True)
class PolicyFinding:
    """A complete context-specific result for one versioned requirement."""

    policy_finding_id: str
    assessment_id: str
    policy_id: str
    policy_version: str
    policy_engine_version: str
    policy_evaluation_id: str
    requirement_id: str
    requirement_version: str
    outcome: PolicyOutcome
    input_evidence_ids: Tuple[str, ...]
    input_metric_result_ids: Tuple[str, ...]
    deterministic_reason: str
    evaluated_at: datetime
    finding_schema_version: str
    condition_template: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in (
            "policy_finding_id",
            "assessment_id",
            "policy_id",
            "policy_version",
            "policy_engine_version",
            "policy_evaluation_id",
            "requirement_id",
            "requirement_version",
            "deterministic_reason",
            "finding_schema_version",
        ):
            _require_text(field_name, getattr(self, field_name))
        if not self.input_evidence_ids:
            raise ValueError("PolicyFinding requires identified evidence inputs")
        if not self.input_metric_result_ids:
            raise ValueError("PolicyFinding requires identified metric inputs")
        if len(set(self.input_evidence_ids)) != len(self.input_evidence_ids):
            raise ValueError("input_evidence_ids must not contain duplicates")
        if len(set(self.input_metric_result_ids)) != len(
            self.input_metric_result_ids
        ):
            raise ValueError("input_metric_result_ids must not contain duplicates")
        _require_aware_datetime("evaluated_at", self.evaluated_at)
        if not isinstance(self.outcome, PolicyOutcome):
            raise ValueError("outcome must be a PolicyOutcome")
        if (
            self.outcome is PolicyOutcome.CONDITION_REQUIRED
            and not self.condition_template
        ):
            raise ValueError(
                "condition_required finding requires a deterministic condition"
            )
        if (
            self.outcome is not PolicyOutcome.CONDITION_REQUIRED
            and self.condition_template is not None
        ):
            raise ValueError(
                "condition_template is only valid for condition_required"
            )


HUMAN_DECISION_SCHEMA_VERSION = "human-decision.v1"


@dataclass(frozen=True)
class HumanDecision:
    """One immutable human disposition over one reviewed evaluation."""

    human_decision_id: str
    assessment_id: str
    assessment_evaluation_id: str
    decision_maker_actor_id: str
    disposition: HumanDecisionDisposition
    rationale: str
    conditions: Tuple[str, ...]
    information_requests: Tuple[str, ...]
    acknowledged_policy_finding_ids: Tuple[str, ...]
    recorded_at: datetime
    decision_schema_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "human_decision_id",
            "assessment_id",
            "assessment_evaluation_id",
            "decision_maker_actor_id",
            "rationale",
            "decision_schema_version",
        ):
            value = getattr(self, field_name)
            _require_text(field_name, value)
            if value != value.strip():
                raise ValueError("{} must be unpadded".format(field_name))
        if type(self.disposition) is not HumanDecisionDisposition:
            raise ValueError(
                "disposition must be a HumanDecisionDisposition"
            )
        for field_name in (
            "conditions",
            "information_requests",
            "acknowledged_policy_finding_ids",
        ):
            values = getattr(self, field_name)
            if type(values) is not tuple:
                raise ValueError("{} must be a tuple".format(field_name))
            for value in values:
                if (
                    type(value) is not str
                    or not value.strip()
                    or value != value.strip()
                ):
                    raise ValueError(
                        "{} entries must be nonempty unpadded strings".format(
                            field_name
                        )
                    )
            if len(set(values)) != len(values):
                raise ValueError(
                    "{} must not contain duplicates".format(field_name)
                )
        _require_aware_datetime("recorded_at", self.recorded_at)
        if self.recorded_at.utcoffset() != timedelta(0):
            raise ValueError("recorded_at must be UTC")
        if self.decision_schema_version != HUMAN_DECISION_SCHEMA_VERSION:
            raise ValueError("decision_schema_version is not supported")

        if self.disposition is HumanDecisionDisposition.APPROVE:
            if self.conditions or self.information_requests:
                raise ValueError(
                    "approve requires no conditions or information requests"
                )
        elif (
            self.disposition
            is HumanDecisionDisposition.APPROVE_WITH_CONDITIONS
        ):
            if not self.conditions or self.information_requests:
                raise ValueError(
                    "approve_with_conditions requires conditions only"
                )
        elif (
            self.disposition
            is HumanDecisionDisposition.NEEDS_MORE_INFORMATION
        ):
            if self.conditions or not self.information_requests:
                raise ValueError(
                    "needs_more_information requires information requests only"
                )
            if self.acknowledged_policy_finding_ids:
                raise ValueError(
                    "needs_more_information requires empty acknowledgments"
                )
        elif self.disposition is HumanDecisionDisposition.REJECT:
            if self.conditions or self.information_requests:
                raise ValueError(
                    "reject requires no conditions or information requests"
                )
            if self.acknowledged_policy_finding_ids:
                raise ValueError("reject requires empty acknowledgments")
