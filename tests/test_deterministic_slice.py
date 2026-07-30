"""Focused tests for the first deterministic assessment slice."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Sequence, Tuple

from engineering_due_diligence.evaluation import (
    METRIC_VERSIONS,
    POLICY_ENGINE_VERSION,
    POLICY_VERSION,
    REQUIREMENT_VERSIONS,
    DeterministicCalculationError,
    InvalidEvidenceSetError,
    InvalidMetricSetError,
    MissingEvidenceRecordError,
    SliceEvaluationError,
    calculate_metrics,
    evaluate_policy,
    evaluate_slice,
)
from engineering_due_diligence.models import (
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


EVALUATED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
REPOSITORY = "github.com/example/reliable-library"
USE_NORMALIZED_VALUE = object()


def _context(assessment_id: str, strict: bool) -> AssessmentContext:
    if strict:
        return AssessmentContext(
            assessment_id=assessment_id,
            repository_identity=REPOSITORY,
            intended_use="Critical production authentication dependency",
            environment=Environment.PRODUCTION,
            criticality=Criticality.CRITICAL,
            expected_lifetime_days=1_825,
            risk_tolerance=RiskTolerance.LOW,
        )
    return AssessmentContext(
        assessment_id=assessment_id,
        repository_identity=REPOSITORY,
        intended_use="Short-lived internal prototype",
        environment=Environment.INTERNAL,
        criticality=Criticality.LOW,
        expected_lifetime_days=30,
        risk_tolerance=RiskTolerance.TOLERANT,
    )


def _snapshot(value: object) -> str:
    if isinstance(value, datetime):
        serializable = value.isoformat()
    elif isinstance(value, LicenseStatus):
        serializable = value.value
    else:
        serializable = value
    return json.dumps({"value": serializable}, sort_keys=True, separators=(",", ":"))


def _available_evidence(
    assessment_id: str,
    kind: EvidenceKind,
    value: object,
    snapshot_value: object = USE_NORMALIZED_VALUE,
) -> EvidenceRecord:
    raw_snapshot = _snapshot(
        value if snapshot_value is USE_NORMALIZED_VALUE else snapshot_value
    )
    return EvidenceRecord(
        evidence_id="{}-{}".format(assessment_id, kind.value),
        assessment_id=assessment_id,
        evidence_kind=kind,
        source_identity="local-fixture://{}/{}".format(REPOSITORY, kind.value),
        collector_name="local-deterministic-fixture",
        collector_version="local-fixture.v1",
        collection_attempt_id="attempt-{}-{}".format(
            assessment_id, kind.value
        ),
        attempt_number=1,
        attempted_at=EVALUATED_AT - timedelta(minutes=5),
        collection_outcome=EvidenceOutcome.AVAILABLE,
        freshness_basis="fixture_observation_time",
        freshness_status_at_collection=FreshnessStatus.CURRENT,
        evidence_schema_version="evidence-record.v1",
        provenance=(("fixture", "tests/test_deterministic_slice.py"),),
        value=value,
        raw_snapshot=raw_snapshot,
        integrity_digest=hashlib.sha256(raw_snapshot.encode("utf-8")).hexdigest(),
    )


def _unavailable_evidence(
    assessment_id: str, kind: EvidenceKind
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="{}-{}-unavailable".format(assessment_id, kind.value),
        assessment_id=assessment_id,
        evidence_kind=kind,
        source_identity="local-fixture://{}/{}".format(REPOSITORY, kind.value),
        collector_name="local-deterministic-fixture",
        collector_version="local-fixture.v1",
        collection_attempt_id="attempt-{}-{}".format(
            assessment_id, kind.value
        ),
        attempt_number=1,
        attempted_at=EVALUATED_AT - timedelta(minutes=5),
        collection_outcome=EvidenceOutcome.UNAVAILABLE,
        freshness_basis="unknown",
        freshness_status_at_collection=FreshnessStatus.UNKNOWN,
        evidence_schema_version="evidence-record.v1",
        provenance=(("fixture", "tests/test_deterministic_slice.py"),),
        unavailability_reason="missing_at_source",
        error_category="missing_evidence",
    )


def _evidence(
    assessment_id: str,
    archived: bool = False,
    license_status: LicenseStatus = LicenseStatus.PRESENT,
    latest_commit_age_days: int = 365,
    security_policy_present: bool = False,
    unavailable_kind: Optional[EvidenceKind] = None,
) -> Tuple[EvidenceRecord, ...]:
    values = {
        EvidenceKind.REPOSITORY_ARCHIVED: archived,
        EvidenceKind.LICENSE_STATUS: license_status,
        EvidenceKind.LATEST_COMMIT_TIMESTAMP: EVALUATED_AT
        - timedelta(days=latest_commit_age_days),
        EvidenceKind.SECURITY_POLICY_PRESENT: security_policy_present,
    }
    return tuple(
        _unavailable_evidence(assessment_id, kind)
        if kind is unavailable_kind
        else _available_evidence(assessment_id, kind, value)
        for kind, value in values.items()
    )


def _metric_by_name(metrics: Sequence[MetricResult]) -> Dict[str, MetricResult]:
    return {metric.metric_name: metric for metric in metrics}


def _finding_by_requirement(
    findings: Sequence[PolicyFinding],
) -> Dict[str, PolicyFinding]:
    return {finding.requirement_id: finding for finding in findings}


def _with_freshness(
    evidence: Sequence[EvidenceRecord],
    kind: EvidenceKind,
    status: FreshnessStatus,
) -> Tuple[EvidenceRecord, ...]:
    return tuple(
        replace(record, freshness_status_at_collection=status)
        if record.evidence_kind is kind
        else record
        for record in evidence
    )


def _with_attempted_at(
    evidence: Sequence[EvidenceRecord],
    kind: EvidenceKind,
    attempted_at: datetime,
) -> Tuple[EvidenceRecord, ...]:
    return tuple(
        replace(record, attempted_at=attempted_at)
        if record.evidence_kind is kind
        else record
        for record in evidence
    )


def _with_latest_commit_timestamp(
    evidence: Sequence[EvidenceRecord],
    commit_timestamp: datetime,
) -> Tuple[EvidenceRecord, ...]:
    return tuple(
        _available_evidence(
            record.assessment_id,
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            commit_timestamp,
        )
        if record.evidence_kind is EvidenceKind.LATEST_COMMIT_TIMESTAMP
        else record
        for record in evidence
    )


def _replace_metric(
    metrics: Sequence[MetricResult], metric_name: str, **changes: object
) -> Tuple[MetricResult, ...]:
    return tuple(
        replace(metric, **changes)
        if metric.metric_name == metric_name
        else metric
        for metric in metrics
    )


class DeterministicSliceTests(unittest.TestCase):
    def test_archived_snapshot_must_match_normalized_value(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "normalized repository_archived value does not match",
        ):
            _available_evidence(
                "assessment-mismatched-archived",
                EvidenceKind.REPOSITORY_ARCHIVED,
                False,
                snapshot_value=True,
            )

    def test_license_snapshot_must_match_normalized_value(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "normalized license_status value does not match",
        ):
            _available_evidence(
                "assessment-mismatched-license",
                EvidenceKind.LICENSE_STATUS,
                LicenseStatus.PRESENT,
                snapshot_value=LicenseStatus.ABSENT,
            )

    def test_security_snapshot_must_match_normalized_value(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "normalized security_policy_present value does not match",
        ):
            _available_evidence(
                "assessment-mismatched-security",
                EvidenceKind.SECURITY_POLICY_PRESENT,
                True,
                snapshot_value=False,
            )

    def test_commit_snapshot_must_match_normalized_timestamp(self) -> None:
        normalized_timestamp = EVALUATED_AT - timedelta(days=30)
        with self.assertRaisesRegex(
            ValueError,
            "normalized latest_commit_timestamp value does not match",
        ):
            _available_evidence(
                "assessment-mismatched-commit",
                EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                normalized_timestamp,
                snapshot_value=normalized_timestamp - timedelta(seconds=1),
            )

    def test_raw_snapshot_digest_mismatch_is_rejected_before_metrics(self) -> None:
        context = _context("assessment-mismatched-digest", strict=True)
        evidence = list(_evidence(context.assessment_id))
        tampered_record = replace(evidence[0])
        object.__setattr__(tampered_record, "integrity_digest", "0" * 64)
        evidence[0] = tampered_record
        metrics = None

        with self.assertRaisesRegex(
            InvalidEvidenceSetError,
            "integrity_digest does not match raw_snapshot",
        ):
            metrics = calculate_metrics(context, tuple(evidence), EVALUATED_AT)

        self.assertIsNone(metrics)

    def test_consistent_snapshots_continue_through_evaluation(self) -> None:
        context = _context("assessment-consistent-snapshots", strict=True)
        evidence = _evidence(
            context.assessment_id,
            archived=False,
            license_status=LicenseStatus.PRESENT,
            latest_commit_age_days=30,
            security_policy_present=True,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(len(metrics), 4)
        self.assertEqual(len(findings), 4)
        self.assertTrue(
            all(metric.result_status is MetricStatus.AVAILABLE for metric in metrics)
        )
        self.assertTrue(
            all(finding.outcome is PolicyOutcome.PASS for finding in findings)
        )

    def test_snapshot_validation_failure_returns_no_partial_results(self) -> None:
        result = None

        with self.assertRaisesRegex(
            ValueError,
            "normalized repository_archived value does not match",
        ):
            context = _context("assessment-no-partial-results", strict=True)
            evidence = (
                _available_evidence(
                    context.assessment_id,
                    EvidenceKind.REPOSITORY_ARCHIVED,
                    False,
                    snapshot_value=True,
                ),
            )
            result = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertIsNone(result)

    def test_evidence_attempted_after_metric_calculation_is_rejected(self) -> None:
        context = _context("assessment-future-evidence", strict=True)
        evidence = _with_attempted_at(
            _evidence(context.assessment_id),
            EvidenceKind.REPOSITORY_ARCHIVED,
            EVALUATED_AT + timedelta(seconds=1),
        )
        metrics = None

        with self.assertRaisesRegex(
            InvalidEvidenceSetError,
            "attempted_at is after calculated_at",
        ):
            metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        self.assertIsNone(metrics)

    def test_evidence_at_metric_calculation_time_is_accepted(self) -> None:
        context = _context("assessment-equal-evidence-time", strict=True)
        evidence = _with_attempted_at(
            _evidence(context.assessment_id),
            EvidenceKind.REPOSITORY_ARCHIVED,
            EVALUATED_AT,
        )

        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        self.assertEqual(len(metrics), 4)

    def test_equivalent_timezone_instants_are_accepted(self) -> None:
        context = _context("assessment-equivalent-timezones", strict=True)
        eastern_offset = timezone(timedelta(hours=5, minutes=30))
        western_offset = timezone(-timedelta(hours=7))
        evidence = _with_attempted_at(
            _evidence(context.assessment_id),
            EvidenceKind.REPOSITORY_ARCHIVED,
            EVALUATED_AT.astimezone(eastern_offset),
        )
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        findings = evaluate_policy(
            context,
            evidence,
            metrics,
            EVALUATED_AT.astimezone(western_offset),
        )

        self.assertEqual(len(findings), 4)

    def test_metric_calculated_after_policy_evaluation_is_rejected(self) -> None:
        context = _context("assessment-future-metric", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(
            context, evidence, EVALUATED_AT + timedelta(seconds=1)
        )

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "calculated_at is after policy evaluated_at",
        ):
            evaluate_policy(context, evidence, metrics, EVALUATED_AT)

    def test_metric_at_policy_evaluation_time_is_accepted(self) -> None:
        context = _context("assessment-equal-policy-time", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        findings = evaluate_policy(
            context, evidence, metrics, EVALUATED_AT
        )

        self.assertEqual(len(findings), 4)

    def test_metrics_with_different_valid_timestamps_are_accepted(self) -> None:
        context = _context("assessment-mixed-metric-times", strict=True)
        evidence = _evidence(context.assessment_id)
        metric_names = tuple(METRIC_VERSIONS)
        calculation_times = tuple(
            EVALUATED_AT - timedelta(seconds=offset)
            for offset in (4, 3, 2, 1)
        )
        metric_sets = tuple(
            _metric_by_name(
                calculate_metrics(context, evidence, calculated_at)
            )
            for calculated_at in calculation_times
        )
        mixed_metrics = tuple(
            metric_sets[index][metric_name]
            for index, metric_name in enumerate(metric_names)
        )

        findings = evaluate_policy(
            context, evidence, mixed_metrics, EVALUATED_AT
        )

        self.assertEqual(len(findings), 4)
        self.assertEqual(
            {metric.calculated_at for metric in mixed_metrics},
            set(calculation_times),
        )

    def test_one_future_metric_returns_no_partial_policy_findings(self) -> None:
        context = _context("assessment-future-metric-no-partial", strict=True)
        evidence = _evidence(context.assessment_id)
        current_metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        future_metrics = _metric_by_name(
            calculate_metrics(
                context, evidence, EVALUATED_AT + timedelta(seconds=1)
            )
        )
        mixed_metrics = tuple(
            future_metrics[metric.metric_name]
            if metric.metric_name == "security_policy_present"
            else metric
            for metric in current_metrics
        )
        findings = None

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "calculated_at is after policy evaluated_at",
        ):
            findings = evaluate_policy(
                context, evidence, mixed_metrics, EVALUATED_AT
            )

        self.assertIsNone(findings)

    def test_exact_strict_recency_threshold_passes(self) -> None:
        context = _context("assessment-exact-180-days", strict=True)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id),
            EVALUATED_AT - timedelta(days=180),
        )

        _, findings = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.PASS,
        )

    def test_one_second_over_strict_recency_threshold_fails(self) -> None:
        context = _context("assessment-over-180-days", strict=True)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id),
            EVALUATED_AT - timedelta(days=180, seconds=1),
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(
            _metric_by_name(metrics)["days_since_latest_commit"].value,
            180,
        )
        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.FAIL,
        )

    def test_exact_broader_recency_threshold_passes(self) -> None:
        context = _context("assessment-exact-730-days", strict=False)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id),
            EVALUATED_AT - timedelta(days=730),
        )

        _, findings = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.PASS,
        )

    def test_one_second_over_broader_recency_threshold_fails(self) -> None:
        context = _context("assessment-over-730-days", strict=False)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id),
            EVALUATED_AT - timedelta(days=730, seconds=1),
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(
            _metric_by_name(metrics)["days_since_latest_commit"].value,
            730,
        )
        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.FAIL,
        )

    def test_recency_is_equivalent_across_timezone_offsets(self) -> None:
        context = _context("assessment-recency-timezones", strict=True)
        offset = timezone(timedelta(hours=5, minutes=30))
        commit_timestamp = (
            EVALUATED_AT - timedelta(days=180)
        ).astimezone(offset)
        policy_evaluated_at = EVALUATED_AT.astimezone(
            timezone(-timedelta(hours=7))
        )
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id), commit_timestamp
        )
        metrics = calculate_metrics(
            context, evidence, policy_evaluated_at
        )

        findings = evaluate_policy(
            context,
            evidence,
            metrics,
            policy_evaluated_at,
        )

        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.PASS,
        )

    def test_commit_at_evaluation_instant_has_zero_elapsed_duration(self) -> None:
        context = _context("assessment-zero-recency", strict=True)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id), EVALUATED_AT
        )

        metrics, findings = evaluate_slice(
            context, evidence, EVALUATED_AT
        )

        self.assertEqual(
            _metric_by_name(metrics)["days_since_latest_commit"].value,
            0,
        )
        self.assertEqual(
            _finding_by_requirement(findings)["commit_recency"].outcome,
            PolicyOutcome.PASS,
        )

    def test_future_commit_timestamp_remains_invalid(self) -> None:
        context = _context("assessment-future-commit", strict=True)
        evidence = _with_latest_commit_timestamp(
            _evidence(context.assessment_id),
            EVALUATED_AT + timedelta(seconds=1),
        )
        result = None

        with self.assertRaisesRegex(
            DeterministicCalculationError,
            "latest commit timestamp cannot be after calculated_at",
        ):
            result = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertIsNone(result)

    def test_future_stale_commit_timestamp_is_rejected_before_metrics(self) -> None:
        context = _context("assessment-future-stale-commit", strict=True)
        evidence = _with_freshness(
            _with_latest_commit_timestamp(
                _evidence(context.assessment_id),
                EVALUATED_AT + timedelta(seconds=1),
            ),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            FreshnessStatus.STALE,
        )
        metrics = None

        with self.assertRaisesRegex(
            DeterministicCalculationError,
            "latest commit timestamp cannot be after calculated_at",
        ):
            metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        self.assertIsNone(metrics)

    def test_future_unknown_commit_timestamp_is_rejected_before_metrics(self) -> None:
        context = _context("assessment-future-unknown-commit", strict=True)
        evidence = _with_freshness(
            _with_latest_commit_timestamp(
                _evidence(context.assessment_id),
                EVALUATED_AT + timedelta(seconds=1),
            ),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            FreshnessStatus.UNKNOWN,
        )
        metrics = None

        with self.assertRaisesRegex(
            DeterministicCalculationError,
            "latest commit timestamp cannot be after calculated_at",
        ):
            metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        self.assertIsNone(metrics)

    def test_future_commit_recalculation_returns_no_policy_findings(self) -> None:
        for freshness in (
            FreshnessStatus.CURRENT,
            FreshnessStatus.STALE,
            FreshnessStatus.UNKNOWN,
        ):
            with self.subTest(freshness=freshness):
                context = _context(
                    "assessment-future-policy-{}".format(freshness.value),
                    strict=True,
                )
                valid_evidence = _evidence(context.assessment_id)
                metrics = calculate_metrics(
                    context, valid_evidence, EVALUATED_AT
                )
                future_evidence = _with_freshness(
                    _with_latest_commit_timestamp(
                        valid_evidence,
                        EVALUATED_AT + timedelta(seconds=1),
                    ),
                    EvidenceKind.LATEST_COMMIT_TIMESTAMP,
                    freshness,
                )
                findings = None

                with self.assertRaisesRegex(
                    DeterministicCalculationError,
                    "latest commit timestamp cannot be after calculated_at",
                ):
                    findings = evaluate_policy(
                        context,
                        future_evidence,
                        metrics,
                        EVALUATED_AT,
                    )

                self.assertIsNone(findings)

    def test_altered_license_metric_value_is_rejected(self) -> None:
        context = _context("assessment-altered-license", strict=True)
        evidence = _evidence(
            context.assessment_id, license_status=LicenseStatus.ABSENT
        )
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        altered_metrics = _replace_metric(metrics, "license_present", value=True)

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "does not match deterministic recalculation",
        ):
            evaluate_policy(
                context, evidence, altered_metrics, EVALUATED_AT
            )

    def test_unavailable_metric_changed_to_available_is_rejected(self) -> None:
        context = _context("assessment-altered-unavailable", strict=True)
        evidence = _evidence(
            context.assessment_id,
            unavailable_kind=EvidenceKind.SECURITY_POLICY_PRESENT,
        )
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        altered_metrics = _replace_metric(
            metrics,
            "security_policy_present",
            result_status=MetricStatus.AVAILABLE,
            input_sufficiency=InputSufficiency.SUFFICIENT,
            value=True,
            unit="boolean",
            reason_code=None,
        )

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "does not match deterministic recalculation",
        ):
            evaluate_policy(
                context, evidence, altered_metrics, EVALUATED_AT
            )

    def test_metric_with_changed_evidence_identifier_is_rejected(self) -> None:
        context = _context("assessment-altered-evidence-id", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        license_evidence_id = next(
            record.evidence_id
            for record in evidence
            if record.evidence_kind is EvidenceKind.LICENSE_STATUS
        )
        altered_metrics = _replace_metric(
            metrics,
            "repository_archived",
            input_evidence_ids=(license_evidence_id,),
        )

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "does not reference its required evidence",
        ):
            evaluate_policy(
                context, evidence, altered_metrics, EVALUATED_AT
            )

    def test_metric_with_changed_calculation_version_is_rejected(self) -> None:
        context = _context("assessment-altered-version", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        altered_metrics = _replace_metric(
            metrics,
            "repository_archived",
            metric_definition_version="repository-archived.tampered",
        )

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "inapplicable definition version",
        ):
            evaluate_policy(
                context, evidence, altered_metrics, EVALUATED_AT
            )

    def test_metric_with_changed_timestamp_or_identifier_is_rejected(self) -> None:
        context = _context("assessment-altered-identity", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        alterations = (
            {"calculated_at": EVALUATED_AT - timedelta(seconds=1)},
            {"metric_result_id": "metric-tampered"},
        )

        for changes in alterations:
            with self.subTest(changes=changes):
                altered_metrics = _replace_metric(
                    metrics, "repository_archived", **changes
                )
                with self.assertRaisesRegex(
                    InvalidMetricSetError,
                    "does not match deterministic recalculation",
                ):
                    evaluate_policy(
                        context, evidence, altered_metrics, EVALUATED_AT
                    )

    def test_canonical_metrics_continue_through_policy_evaluation(self) -> None:
        context = _context("assessment-canonical-policy", strict=True)
        evidence = _evidence(
            context.assessment_id,
            archived=False,
            license_status=LicenseStatus.PRESENT,
            latest_commit_age_days=30,
            security_policy_present=True,
        )
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        findings = evaluate_policy(
            context, evidence, metrics, EVALUATED_AT
        )

        self.assertEqual(len(findings), 4)
        self.assertTrue(
            all(finding.outcome is PolicyOutcome.PASS for finding in findings)
        )

    def test_rejected_metric_returns_no_partial_policy_findings(self) -> None:
        context = _context("assessment-no-partial-findings", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)
        altered_metrics = _replace_metric(
            metrics, "security_policy_present", value=True
        )
        findings = None

        with self.assertRaisesRegex(
            InvalidMetricSetError,
            "does not match deterministic recalculation",
        ):
            findings = evaluate_policy(
                context, evidence, altered_metrics, EVALUATED_AT
            )

        self.assertIsNone(findings)

    def test_repeated_canonical_policy_evaluation_is_deterministic(self) -> None:
        context = _context("assessment-repeat-policy", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        first = evaluate_policy(context, evidence, metrics, EVALUATED_AT)
        second = evaluate_policy(context, evidence, metrics, EVALUATED_AT)

        self.assertEqual(first, second)

    def test_metric_results_are_deterministic_and_versioned(self) -> None:
        context = _context("assessment-prototype", strict=False)
        evidence = _evidence(context.assessment_id)

        first_metrics, _ = evaluate_slice(context, evidence, EVALUATED_AT)
        second_metrics, _ = evaluate_slice(context, evidence, EVALUATED_AT)
        metrics = _metric_by_name(first_metrics)

        self.assertEqual(first_metrics, second_metrics)
        self.assertEqual(metrics["repository_archived"].value, False)
        self.assertEqual(metrics["license_present"].value, True)
        self.assertEqual(metrics["days_since_latest_commit"].value, 365)
        self.assertEqual(metrics["security_policy_present"].value, False)
        self.assertEqual(
            {metric.metric_name: metric.metric_definition_version for metric in first_metrics},
            METRIC_VERSIONS,
        )

    def test_absent_required_evidence_aborts_before_result_set(self) -> None:
        context = _context("assessment-missing-record", strict=False)
        evidence = _evidence(context.assessment_id)[:-1]

        with self.assertRaises(MissingEvidenceRecordError):
            evaluate_slice(context, evidence, EVALUATED_AT)

    def test_duplicate_evidence_identifier_is_rejected_before_metrics(self) -> None:
        context = _context("assessment-duplicate-evidence-id", strict=True)
        evidence = _evidence(context.assessment_id)
        duplicate_id_evidence = (
            evidence[0],
            replace(evidence[1], evidence_id=evidence[0].evidence_id),
            *evidence[2:],
        )
        metrics = None

        with self.assertRaisesRegex(
            InvalidEvidenceSetError, "duplicate evidence_id"
        ):
            metrics = calculate_metrics(
                context, duplicate_id_evidence, EVALUATED_AT
            )

        self.assertIsNone(metrics)

    def test_duplicate_current_evidence_kind_is_rejected_before_metrics(self) -> None:
        context = _context("assessment-duplicate-evidence-kind", strict=True)
        evidence = _evidence(context.assessment_id)
        duplicate_kind_evidence = evidence + (
            replace(
                evidence[0],
                evidence_id="{}-duplicate-archived".format(
                    context.assessment_id
                ),
                collection_attempt_id="attempt-{}-duplicate-archived".format(
                    context.assessment_id
                ),
            ),
        )
        metrics = None

        with self.assertRaisesRegex(
            InvalidEvidenceSetError,
            "multiple current records for repository_archived",
        ):
            metrics = calculate_metrics(
                context, duplicate_kind_evidence, EVALUATED_AT
            )

        self.assertIsNone(metrics)

    def test_naive_evidence_timestamp_is_rejected(self) -> None:
        context = _context("assessment-naive-evidence-time", strict=True)
        evidence = _evidence(context.assessment_id)

        with self.assertRaisesRegex(
            ValueError, "attempted_at must be timezone-aware"
        ):
            replace(
                evidence[0],
                attempted_at=EVALUATED_AT.replace(tzinfo=None),
            )

    def test_naive_metric_timestamp_is_rejected(self) -> None:
        context = _context("assessment-naive-metric-time", strict=True)
        metric = calculate_metrics(
            context, _evidence(context.assessment_id), EVALUATED_AT
        )[0]

        with self.assertRaisesRegex(
            ValueError, "calculated_at must be timezone-aware"
        ):
            replace(
                metric,
                calculated_at=EVALUATED_AT.replace(tzinfo=None),
            )

    def test_naive_policy_evaluation_timestamp_is_rejected(self) -> None:
        context = _context("assessment-naive-policy-time", strict=True)
        evidence = _evidence(context.assessment_id)
        metrics = calculate_metrics(context, evidence, EVALUATED_AT)

        with self.assertRaisesRegex(
            SliceEvaluationError, "evaluated_at must be timezone-aware"
        ):
            evaluate_policy(
                context,
                evidence,
                metrics,
                EVALUATED_AT.replace(tzinfo=None),
            )

    def test_unavailable_evidence_never_becomes_a_pass(self) -> None:
        context = _context("assessment-unavailable", strict=False)
        evidence = _evidence(
            context.assessment_id,
            unavailable_kind=EvidenceKind.SECURITY_POLICY_PRESENT,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        security_metric = _metric_by_name(metrics)["security_policy_present"]
        security_finding = _finding_by_requirement(findings)["security_policy"]

        self.assertEqual(security_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertIsNone(security_metric.value)
        self.assertEqual(security_finding.outcome, PolicyOutcome.NOT_EVALUABLE)
        self.assertEqual(
            security_finding.input_evidence_ids,
            security_metric.input_evidence_ids,
        )

    def test_stale_archived_status_cannot_produce_pass(self) -> None:
        context = _context("assessment-stale-archived", strict=False)
        evidence = _with_freshness(
            _evidence(context.assessment_id),
            EvidenceKind.REPOSITORY_ARCHIVED,
            FreshnessStatus.STALE,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        archived_metric = _metric_by_name(metrics)["repository_archived"]
        archived_finding = _finding_by_requirement(findings)[
            "repository_not_archived"
        ]

        self.assertEqual(archived_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertEqual(archived_finding.outcome, PolicyOutcome.NOT_EVALUABLE)
        self.assertEqual(
            archived_finding.input_evidence_ids,
            archived_metric.input_evidence_ids,
        )
        self.assertEqual(
            archived_finding.input_metric_result_ids,
            (archived_metric.metric_result_id,),
        )

    def test_unknown_archived_status_cannot_produce_pass(self) -> None:
        context = _context("assessment-unknown-archived", strict=False)
        evidence = _with_freshness(
            _evidence(context.assessment_id),
            EvidenceKind.REPOSITORY_ARCHIVED,
            FreshnessStatus.UNKNOWN,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        archived_metric = _metric_by_name(metrics)["repository_archived"]
        archived_finding = _finding_by_requirement(findings)[
            "repository_not_archived"
        ]

        self.assertEqual(archived_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertEqual(archived_finding.outcome, PolicyOutcome.NOT_EVALUABLE)
        self.assertEqual(
            archived_finding.input_evidence_ids,
            archived_metric.input_evidence_ids,
        )
        self.assertEqual(
            archived_finding.input_metric_result_ids,
            (archived_metric.metric_result_id,),
        )

    def test_valid_stale_commit_is_unavailable_and_not_evaluable(self) -> None:
        context = _context("assessment-valid-stale-commit", strict=True)
        evidence = _with_freshness(
            _evidence(context.assessment_id, latest_commit_age_days=30),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            FreshnessStatus.STALE,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        commit_metric = _metric_by_name(metrics)["days_since_latest_commit"]
        commit_finding = _finding_by_requirement(findings)["commit_recency"]

        self.assertEqual(commit_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertEqual(commit_finding.outcome, PolicyOutcome.NOT_EVALUABLE)

    def test_valid_unknown_commit_is_unavailable_and_not_evaluable(self) -> None:
        context = _context("assessment-valid-unknown-commit", strict=True)
        evidence = _with_freshness(
            _evidence(context.assessment_id, latest_commit_age_days=30),
            EvidenceKind.LATEST_COMMIT_TIMESTAMP,
            FreshnessStatus.UNKNOWN,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        commit_metric = _metric_by_name(metrics)["days_since_latest_commit"]
        commit_finding = _finding_by_requirement(findings)["commit_recency"]

        self.assertEqual(commit_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertEqual(commit_finding.outcome, PolicyOutcome.NOT_EVALUABLE)

    def test_stale_security_policy_cannot_satisfy_critical_requirement(self) -> None:
        context = _context("assessment-stale-security", strict=True)
        evidence = _with_freshness(
            _evidence(context.assessment_id, security_policy_present=True),
            EvidenceKind.SECURITY_POLICY_PRESENT,
            FreshnessStatus.STALE,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        security_metric = _metric_by_name(metrics)["security_policy_present"]
        security_finding = _finding_by_requirement(findings)["security_policy"]

        self.assertEqual(security_metric.result_status, MetricStatus.UNAVAILABLE)
        self.assertEqual(security_finding.outcome, PolicyOutcome.NOT_EVALUABLE)
        self.assertEqual(
            security_finding.input_evidence_ids,
            security_metric.input_evidence_ids,
        )
        self.assertEqual(
            security_finding.input_metric_result_ids,
            (security_metric.metric_result_id,),
        )

    def test_current_evidence_continues_through_normal_evaluation(self) -> None:
        context = _context("assessment-current-evidence", strict=True)
        evidence = _evidence(
            context.assessment_id,
            archived=False,
            security_policy_present=True,
        )

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        metrics_by_name = _metric_by_name(metrics)
        findings_by_requirement = _finding_by_requirement(findings)

        self.assertEqual(
            metrics_by_name["repository_archived"].result_status,
            MetricStatus.AVAILABLE,
        )
        self.assertEqual(
            metrics_by_name["security_policy_present"].result_status,
            MetricStatus.AVAILABLE,
        )
        self.assertEqual(
            findings_by_requirement["repository_not_archived"].outcome,
            PolicyOutcome.PASS,
        )
        self.assertEqual(
            findings_by_requirement["security_policy"].outcome,
            PolicyOutcome.PASS,
        )

    def test_archived_repository_fails_in_both_contexts(self) -> None:
        for strict in (False, True):
            with self.subTest(strict=strict):
                context = _context(
                    "assessment-archived-{}".format(strict), strict=strict
                )
                evidence = _evidence(context.assessment_id, archived=True)

                _, findings = evaluate_slice(context, evidence, EVALUATED_AT)

                self.assertEqual(
                    _finding_by_requirement(findings)[
                        "repository_not_archived"
                    ].outcome,
                    PolicyOutcome.FAIL,
                )

    def test_absent_license_policy_is_context_sensitive(self) -> None:
        expected_outcomes = {
            False: PolicyOutcome.CONDITION_REQUIRED,
            True: PolicyOutcome.FAIL,
        }
        for strict, expected_outcome in expected_outcomes.items():
            with self.subTest(strict=strict):
                context = _context(
                    "assessment-license-{}".format(strict), strict=strict
                )
                evidence = _evidence(
                    context.assessment_id,
                    license_status=LicenseStatus.ABSENT,
                    latest_commit_age_days=30,
                    security_policy_present=True,
                )

                metrics, findings = evaluate_slice(
                    context, evidence, EVALUATED_AT
                )
                metrics_by_name = _metric_by_name(metrics)
                findings_by_requirement = _finding_by_requirement(findings)
                license_metric = metrics_by_name["license_present"]
                license_finding = findings_by_requirement["license_declared"]
                license_evidence = next(
                    record
                    for record in evidence
                    if record.evidence_kind is EvidenceKind.LICENSE_STATUS
                )

                self.assertEqual(license_finding.outcome, expected_outcome)
                self.assertEqual(
                    license_metric.input_evidence_ids,
                    (license_evidence.evidence_id,),
                )
                self.assertEqual(
                    license_finding.input_evidence_ids,
                    (license_evidence.evidence_id,),
                )
                self.assertEqual(
                    license_finding.input_metric_result_ids,
                    (license_metric.metric_result_id,),
                )
                self.assertTrue(
                    all(
                        finding.outcome is PolicyOutcome.PASS
                        for requirement, finding in findings_by_requirement.items()
                        if requirement != "license_declared"
                    )
                )

    def test_security_policy_is_context_sensitive(self) -> None:
        prototype = _context("assessment-security-prototype", strict=False)
        production = _context("assessment-security-production", strict=True)

        _, prototype_findings = evaluate_slice(
            prototype, _evidence(prototype.assessment_id), EVALUATED_AT
        )
        _, production_findings = evaluate_slice(
            production, _evidence(production.assessment_id), EVALUATED_AT
        )

        self.assertEqual(
            _finding_by_requirement(prototype_findings)["security_policy"].outcome,
            PolicyOutcome.CONDITION_REQUIRED,
        )
        self.assertEqual(
            _finding_by_requirement(production_findings)["security_policy"].outcome,
            PolicyOutcome.FAIL,
        )

    def test_same_repository_facts_produce_context_specific_findings(self) -> None:
        prototype = _context("assessment-facts-prototype", strict=False)
        production = _context("assessment-facts-production", strict=True)

        _, prototype_findings = evaluate_slice(
            prototype, _evidence(prototype.assessment_id), EVALUATED_AT
        )
        _, production_findings = evaluate_slice(
            production, _evidence(production.assessment_id), EVALUATED_AT
        )
        prototype_by_requirement = _finding_by_requirement(prototype_findings)
        production_by_requirement = _finding_by_requirement(production_findings)

        self.assertEqual(
            prototype_by_requirement["commit_recency"].outcome,
            PolicyOutcome.PASS,
        )
        self.assertEqual(
            production_by_requirement["commit_recency"].outcome,
            PolicyOutcome.FAIL,
        )
        self.assertEqual(
            prototype_by_requirement["security_policy"].outcome,
            PolicyOutcome.CONDITION_REQUIRED,
        )
        self.assertEqual(
            production_by_requirement["security_policy"].outcome,
            PolicyOutcome.FAIL,
        )

    def test_findings_preserve_metric_and_evidence_traceability(self) -> None:
        context = _context("assessment-traceability", strict=True)
        evidence = _evidence(context.assessment_id)

        metrics, findings = evaluate_slice(context, evidence, EVALUATED_AT)
        metrics_by_id = {metric.metric_result_id: metric for metric in metrics}
        evidence_ids = {record.evidence_id for record in evidence}

        for finding in findings:
            self.assertEqual(finding.policy_version, POLICY_VERSION)
            self.assertEqual(
                finding.policy_engine_version, POLICY_ENGINE_VERSION
            )
            self.assertEqual(
                finding.requirement_version,
                REQUIREMENT_VERSIONS[finding.requirement_id],
            )
            self.assertEqual(len(finding.input_metric_result_ids), 1)
            metric = metrics_by_id[finding.input_metric_result_ids[0]]
            self.assertEqual(finding.input_evidence_ids, metric.input_evidence_ids)
            self.assertTrue(set(finding.input_evidence_ids).issubset(evidence_ids))

    def test_repeated_evaluation_produces_identical_complete_results(self) -> None:
        context = _context("assessment-repeat", strict=True)
        evidence = _evidence(context.assessment_id)

        first = evaluate_slice(context, evidence, EVALUATED_AT)
        second = evaluate_slice(context, evidence, EVALUATED_AT)

        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), 4)
        self.assertEqual(len(first[1]), 4)


if __name__ == "__main__":
    unittest.main()
