"""Focused contract test for the transient deterministic assessment result."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Iterator, Sequence, Tuple
from unittest.mock import patch

from engineering_due_diligence.assessment import (
    DeterministicAssessmentResult,
    evaluate_assessment,
)
from engineering_due_diligence.evaluation import (
    REQUIRED_EVIDENCE_KINDS,
    MissingEvidenceRecordError,
    SliceEvaluationError,
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
    LicenseStatus,
    RiskTolerance,
)


EVALUATED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
REPOSITORY = "github.com/example/reliable-library"


def _strict_context(assessment_id: str) -> AssessmentContext:
    return AssessmentContext(
        assessment_id=assessment_id,
        repository_identity=REPOSITORY,
        intended_use="Critical production authentication dependency",
        environment=Environment.PRODUCTION,
        criticality=Criticality.CRITICAL,
        expected_lifetime_days=1_825,
        risk_tolerance=RiskTolerance.LOW,
    )


def _snapshot(value: object) -> str:
    if isinstance(value, datetime):
        serializable = value.isoformat()
    elif isinstance(value, LicenseStatus):
        serializable = value.value
    else:
        serializable = value
    return json.dumps(
        {"value": serializable}, sort_keys=True, separators=(",", ":")
    )


def _available_evidence(
    assessment_id: str,
    evidence_kind: EvidenceKind,
    value: object,
) -> EvidenceRecord:
    raw_snapshot = _snapshot(value)
    return EvidenceRecord(
        evidence_id="{}-{}".format(assessment_id, evidence_kind.value),
        assessment_id=assessment_id,
        evidence_kind=evidence_kind,
        source_identity="local-fixture://{}/{}".format(
            REPOSITORY, evidence_kind.value
        ),
        collector_name="local-deterministic-fixture",
        collector_version="local-fixture.v1",
        collection_attempt_id="attempt-{}-{}".format(
            assessment_id, evidence_kind.value
        ),
        attempt_number=1,
        attempted_at=EVALUATED_AT - timedelta(minutes=5),
        collection_outcome=EvidenceOutcome.AVAILABLE,
        freshness_basis="fixture_observation_time",
        freshness_status_at_collection=FreshnessStatus.CURRENT,
        evidence_schema_version="evidence-record.v1",
        provenance=(("fixture", "tests/test_assessment_result.py"),),
        value=value,
        raw_snapshot=raw_snapshot,
        integrity_digest=hashlib.sha256(
            raw_snapshot.encode("utf-8")
        ).hexdigest(),
    )


def _evidence(assessment_id: str) -> Tuple[EvidenceRecord, ...]:
    values = {
        EvidenceKind.REPOSITORY_ARCHIVED: False,
        EvidenceKind.LICENSE_STATUS: LicenseStatus.PRESENT,
        EvidenceKind.LATEST_COMMIT_TIMESTAMP: EVALUATED_AT
        - timedelta(days=30),
        EvidenceKind.SECURITY_POLICY_PRESENT: True,
    }
    return tuple(
        _available_evidence(assessment_id, evidence_kind, value)
        for evidence_kind, value in values.items()
    )


class _SingleIterationEvidenceSequence(Sequence[EvidenceRecord]):
    def __init__(self, records: Tuple[EvidenceRecord, ...]) -> None:
        self._records = records
        self.iteration_count = 0

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index: int) -> EvidenceRecord:
        return self._records[index]

    def __iter__(self) -> Iterator[EvidenceRecord]:
        self.iteration_count += 1
        if self.iteration_count > 1:
            raise AssertionError("caller-owned evidence sequence iterated twice")
        return iter(self._records)


class AssessmentResultTests(unittest.TestCase):
    def test_evaluate_assessment_returns_frozen_complete_result(self) -> None:
        context = _strict_context("assessment-complete-result")
        evidence = tuple(reversed(_evidence(context.assessment_id)))
        expected_metrics, expected_findings = evaluate_slice(
            context, evidence, EVALUATED_AT
        )

        result = evaluate_assessment(context, evidence, EVALUATED_AT)

        self.assertIsInstance(result, DeterministicAssessmentResult)
        self.assertIs(result.context, context)
        self.assertEqual(
            tuple(
                record.evidence_kind for record in result.evidence_records
            ),
            REQUIRED_EVIDENCE_KINDS,
        )
        self.assertEqual(
            set(result.evidence_records),
            set(evidence),
        )
        self.assertEqual(result.metric_results, expected_metrics)
        self.assertEqual(result.policy_findings, expected_findings)
        self.assertIs(result.evaluated_at, EVALUATED_AT)

        with self.assertRaises(FrozenInstanceError):
            result.evaluated_at = EVALUATED_AT + timedelta(seconds=1)

        evidence_ids = {
            record.evidence_id for record in result.evidence_records
        }
        metric_ids = {
            metric.metric_result_id for metric in result.metric_results
        }

        for metric in result.metric_results:
            self.assertTrue(
                set(metric.input_evidence_ids).issubset(evidence_ids)
            )

        for finding in result.policy_findings:
            self.assertTrue(
                set(finding.input_evidence_ids).issubset(evidence_ids)
            )
            self.assertTrue(
                set(finding.input_metric_result_ids).issubset(metric_ids)
            )

    def test_evaluate_assessment_snapshots_sequence_once_before_delegation(
        self,
    ) -> None:
        context = _strict_context("assessment-single-snapshot")
        canonical_evidence = _evidence(context.assessment_id)
        caller_evidence = _SingleIterationEvidenceSequence(
            canonical_evidence
        )

        with patch(
            "engineering_due_diligence.assessment.evaluate_slice",
            wraps=evaluate_slice,
        ) as evaluate_slice_mock:
            result = evaluate_assessment(
                context, caller_evidence, EVALUATED_AT
            )

        evaluate_slice_mock.assert_called_once()
        delegated_context, delegated_evidence, delegated_at = (
            evaluate_slice_mock.call_args.args
        )
        self.assertIs(delegated_context, context)
        self.assertIsInstance(delegated_evidence, tuple)
        self.assertEqual(delegated_evidence, canonical_evidence)
        self.assertIs(delegated_at, EVALUATED_AT)
        self.assertEqual(caller_evidence.iteration_count, 1)
        self.assertEqual(result.evidence_records, canonical_evidence)

    def test_evaluate_assessment_canonicalizes_reversed_evidence_order(
        self,
    ) -> None:
        context = _strict_context("assessment-reversed-evidence")
        canonical_evidence = _evidence(context.assessment_id)
        reversed_evidence = tuple(reversed(canonical_evidence))
        expected_metrics, expected_findings = evaluate_slice(
            context, reversed_evidence, EVALUATED_AT
        )

        result = evaluate_assessment(
            context, reversed_evidence, EVALUATED_AT
        )

        returned_kinds = tuple(
            record.evidence_kind for record in result.evidence_records
        )
        self.assertEqual(returned_kinds, REQUIRED_EVIDENCE_KINDS)
        self.assertEqual(result.metric_results, expected_metrics)
        self.assertEqual(result.policy_findings, expected_findings)
        self.assertEqual(
            len(result.evidence_records), len(REQUIRED_EVIDENCE_KINDS)
        )
        for evidence_kind in REQUIRED_EVIDENCE_KINDS:
            self.assertEqual(returned_kinds.count(evidence_kind), 1)

    def test_evaluate_assessment_preserves_supplied_aware_offset_timestamp(
        self,
    ) -> None:
        context = _strict_context("assessment-aware-offset")
        evidence = _evidence(context.assessment_id)
        supplied_timezone = timezone(timedelta(hours=5, minutes=30))
        supplied_timestamp = EVALUATED_AT.astimezone(supplied_timezone)

        result = evaluate_assessment(
            context, evidence, supplied_timestamp
        )

        self.assertEqual(supplied_timestamp, EVALUATED_AT)
        self.assertIs(result.evaluated_at, supplied_timestamp)
        self.assertIs(result.evaluated_at.tzinfo, supplied_timezone)
        self.assertEqual(
            result.evaluated_at.isoformat(), supplied_timestamp.isoformat()
        )
        self.assertEqual(len(result.metric_results), 4)
        self.assertEqual(len(result.policy_findings), 4)
        for metric in result.metric_results:
            self.assertIs(metric.calculated_at, supplied_timestamp)
            self.assertIs(metric.calculated_at.tzinfo, supplied_timezone)
            self.assertEqual(
                metric.calculated_at.isoformat(),
                supplied_timestamp.isoformat(),
            )
        for finding in result.policy_findings:
            self.assertIs(finding.evaluated_at, supplied_timestamp)
            self.assertIs(finding.evaluated_at.tzinfo, supplied_timezone)
            self.assertEqual(
                finding.evaluated_at.isoformat(),
                supplied_timestamp.isoformat(),
            )

    def test_evaluate_assessment_equivalent_timezone_instants_preserve_supplied_representations(
        self,
    ) -> None:
        context = _strict_context("assessment-equivalent-timezones")
        evidence = _evidence(context.assessment_id)
        eastern_timezone = timezone(timedelta(hours=5, minutes=30))
        western_timezone = timezone(-timedelta(hours=7))
        eastern_timestamp = EVALUATED_AT.astimezone(eastern_timezone)
        western_timestamp = EVALUATED_AT.astimezone(western_timezone)

        eastern_result = evaluate_assessment(
            context, evidence, eastern_timestamp
        )
        western_result = evaluate_assessment(
            context, evidence, western_timestamp
        )

        self.assertEqual(eastern_timestamp, western_timestamp)
        self.assertNotEqual(
            eastern_timestamp.isoformat(), western_timestamp.isoformat()
        )
        for result, supplied_timestamp in (
            (eastern_result, eastern_timestamp),
            (western_result, western_timestamp),
        ):
            self.assertIs(result.evaluated_at, supplied_timestamp)
            self.assertIs(
                result.evaluated_at.tzinfo, supplied_timestamp.tzinfo
            )
            self.assertEqual(
                result.evaluated_at.isoformat(),
                supplied_timestamp.isoformat(),
            )

        self.assertEqual(
            len(eastern_result.metric_results),
            len(western_result.metric_results),
        )
        for eastern_metric, western_metric in zip(
            eastern_result.metric_results, western_result.metric_results
        ):
            self.assertEqual(eastern_metric.metric_name, western_metric.metric_name)
            self.assertEqual(
                (
                    eastern_metric.value,
                    eastern_metric.result_status,
                    eastern_metric.input_evidence_ids,
                    eastern_metric.metric_result_id,
                    eastern_metric.calculation_attempt_id,
                ),
                (
                    western_metric.value,
                    western_metric.result_status,
                    western_metric.input_evidence_ids,
                    western_metric.metric_result_id,
                    western_metric.calculation_attempt_id,
                ),
            )

        self.assertEqual(
            len(eastern_result.policy_findings),
            len(western_result.policy_findings),
        )
        for eastern_finding, western_finding in zip(
            eastern_result.policy_findings, western_result.policy_findings
        ):
            self.assertEqual(
                eastern_finding.requirement_id,
                western_finding.requirement_id,
            )
            self.assertEqual(
                (
                    eastern_finding.outcome,
                    eastern_finding.deterministic_reason,
                    eastern_finding.input_evidence_ids,
                    eastern_finding.input_metric_result_ids,
                    eastern_finding.policy_finding_id,
                    eastern_finding.policy_evaluation_id,
                ),
                (
                    western_finding.outcome,
                    western_finding.deterministic_reason,
                    western_finding.input_evidence_ids,
                    western_finding.input_metric_result_ids,
                    western_finding.policy_finding_id,
                    western_finding.policy_evaluation_id,
                ),
            )

    def test_evaluate_assessment_rejects_naive_timestamp_without_result(
        self,
    ) -> None:
        context = _strict_context("assessment-naive-timestamp")
        evidence = _evidence(context.assessment_id)
        result = None

        with self.assertRaises(SliceEvaluationError):
            result = evaluate_assessment(
                context, evidence, EVALUATED_AT.replace(tzinfo=None)
            )

        self.assertIsNone(result)

    def test_evaluate_assessment_returns_complete_reference_closure(
        self,
    ) -> None:
        context = _strict_context("assessment-reference-closure")
        result = evaluate_assessment(
            context, _evidence(context.assessment_id), EVALUATED_AT
        )
        evidence_ids = {
            record.evidence_id for record in result.evidence_records
        }
        metric_ids = {
            metric.metric_result_id for metric in result.metric_results
        }
        metric_evidence_references = {
            evidence_id
            for metric in result.metric_results
            for evidence_id in metric.input_evidence_ids
        }
        finding_evidence_references = {
            evidence_id
            for finding in result.policy_findings
            for evidence_id in finding.input_evidence_ids
        }
        finding_metric_references = {
            metric_id
            for finding in result.policy_findings
            for metric_id in finding.input_metric_result_ids
        }

        self.assertTrue(metric_evidence_references.issubset(evidence_ids))
        self.assertTrue(finding_evidence_references.issubset(evidence_ids))
        self.assertTrue(finding_metric_references.issubset(metric_ids))
        self.assertTrue(
            all(
                record.assessment_id == result.context.assessment_id
                for record in result.evidence_records
            )
        )
        self.assertTrue(
            all(
                metric.assessment_id == result.context.assessment_id
                for metric in result.metric_results
            )
        )
        self.assertTrue(
            all(
                finding.assessment_id == result.context.assessment_id
                for finding in result.policy_findings
            )
        )

    def test_evaluate_assessment_missing_evidence_fails_atomically(
        self,
    ) -> None:
        context = _strict_context("assessment-missing-evidence")
        incomplete_evidence = _evidence(context.assessment_id)[:-1]
        result = None

        with self.assertRaises(MissingEvidenceRecordError):
            result = evaluate_assessment(
                context, incomplete_evidence, EVALUATED_AT
            )

        self.assertIsNone(result)

    def test_evaluate_assessment_is_input_order_independent(self) -> None:
        context = _strict_context("assessment-order-independent")
        evidence = _evidence(context.assessment_id)
        evidence_orders = (
            evidence,
            tuple(reversed(evidence)),
            evidence[1:] + evidence[:1],
            (evidence[2], evidence[0], evidence[3], evidence[1]),
        )

        results = tuple(
            evaluate_assessment(context, evidence_order, EVALUATED_AT)
            for evidence_order in evidence_orders
        )

        expected_result = results[0]
        for result in results:
            self.assertEqual(result, expected_result)
            self.assertEqual(
                tuple(
                    record.evidence_kind
                    for record in result.evidence_records
                ),
                REQUIRED_EVIDENCE_KINDS,
            )
            self.assertIs(result.evaluated_at, EVALUATED_AT)


if __name__ == "__main__":
    unittest.main()
