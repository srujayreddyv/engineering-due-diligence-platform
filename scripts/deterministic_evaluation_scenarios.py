"""Frozen Day 19 deterministic system-evaluation scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ContextExpectation:
    intended_use: str
    environment: str
    criticality: str
    expected_lifetime_days: int
    risk_tolerance: str


@dataclass(frozen=True)
class EvidenceExpectation:
    kind: str
    outcome: str
    value: object
    freshness: str
    unavailability_reason: Optional[str] = None
    error_category: Optional[str] = None


@dataclass(frozen=True)
class MetricExpectation:
    name: str
    status: str
    value: object
    unit: Optional[str]
    sufficiency: str
    reason_code: Optional[str] = None


@dataclass(frozen=True)
class PolicyExpectation:
    requirement_id: str
    outcome: str
    reason_code: str
    condition_template: Optional[str] = None


@dataclass(frozen=True)
class DecisionExercise:
    disposition: str
    rationale: str
    conditions: Tuple[str, ...] = ()
    information_requests: Tuple[str, ...] = ()
    acknowledged_requirement_ids: Tuple[str, ...] = ()
    exercise_exact_replay: bool = False


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    terminal_expectation: str
    context: ContextExpectation
    archived: bool = False
    license_present: bool = True
    latest_commit_age_days: Optional[int] = 30
    security_policy_present: bool = True
    expected_evidence: Tuple[EvidenceExpectation, ...] = ()
    expected_metrics: Tuple[MetricExpectation, ...] = ()
    expected_policy: Tuple[PolicyExpectation, ...] = ()
    decision: Optional[DecisionExercise] = None
    assessment_replay: bool = False
    rate_limit_latest_commit: bool = False
    corrupt_evaluation_before_review: bool = False


TOLERANT_CONTEXT = ContextExpectation(
    intended_use="Time-bounded internal engineering experiment",
    environment="internal",
    criticality="low",
    expected_lifetime_days=30,
    risk_tolerance="tolerant",
)

STRICT_PRODUCTION_CONTEXT = ContextExpectation(
    intended_use="Production service dependency",
    environment="production",
    criticality="critical",
    expected_lifetime_days=1_825,
    risk_tolerance="low",
)

HEALTHY_EVIDENCE = (
    EvidenceExpectation("repository_archived", "available", False, "current"),
    EvidenceExpectation("license_status", "available", "present", "current"),
    EvidenceExpectation(
        "latest_commit_timestamp", "available", "commit_timestamp", "current"
    ),
    EvidenceExpectation(
        "security_policy_present", "available", True, "current"
    ),
)


def _available_metrics(
    archived: bool,
    license_present: bool,
    commit_age_days: int,
    security_policy_present: bool,
) -> Tuple[MetricExpectation, ...]:
    return (
        MetricExpectation(
            "repository_archived", "available", archived, "boolean", "sufficient"
        ),
        MetricExpectation(
            "license_present",
            "available",
            license_present,
            "boolean",
            "sufficient",
        ),
        MetricExpectation(
            "days_since_latest_commit",
            "available",
            commit_age_days,
            "days",
            "sufficient",
        ),
        MetricExpectation(
            "security_policy_present",
            "available",
            security_policy_present,
            "boolean",
            "sufficient",
        ),
    )


SCENARIOS = (
    Scenario(
        scenario_id="E01",
        description="healthy active repository",
        terminal_expectation="completed",
        context=STRICT_PRODUCTION_CONTEXT,
        expected_evidence=HEALTHY_EVIDENCE,
        expected_metrics=_available_metrics(False, True, 30, True),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_180_days"
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
        decision=DecisionExercise(
            "approve",
            "The reviewed evidence supports this defined production use.",
        ),
        assessment_replay=True,
    ),
    Scenario(
        scenario_id="E02",
        description="archived repository",
        terminal_expectation="completed",
        context=TOLERANT_CONTEXT,
        archived=True,
        expected_evidence=(
            EvidenceExpectation(
                "repository_archived", "available", True, "current"
            ),
            *HEALTHY_EVIDENCE[1:],
        ),
        expected_metrics=_available_metrics(True, True, 30, True),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "fail", "repository_is_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_730_days"
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
    ),
    Scenario(
        scenario_id="E03",
        description="license metadata absent",
        terminal_expectation="completed",
        context=TOLERANT_CONTEXT,
        license_present=False,
        expected_evidence=(
            HEALTHY_EVIDENCE[0],
            EvidenceExpectation("license_status", "available", "absent", "current"),
            *HEALTHY_EVIDENCE[2:],
        ),
        expected_metrics=_available_metrics(False, False, 30, True),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation(
                "license_declared",
                "condition_required",
                "prototype_requires_license_resolution_before_broader_use",
                "Resolve and document the license before use expands beyond the prototype.",
            ),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_730_days"
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
        decision=DecisionExercise(
            "approve_with_conditions",
            "The experiment is accepted subject to the recorded human condition.",
            conditions=(
                "Obtain and document legal review before expanding beyond the prototype.",
            ),
            acknowledged_requirement_ids=("license_declared",),
            exercise_exact_replay=True,
        ),
    ),
    Scenario(
        scenario_id="E04",
        description="effective security policy absent",
        terminal_expectation="completed",
        context=TOLERANT_CONTEXT,
        security_policy_present=False,
        expected_evidence=(
            *HEALTHY_EVIDENCE[:3],
            EvidenceExpectation(
                "security_policy_present", "available", False, "current"
            ),
        ),
        expected_metrics=_available_metrics(False, True, 30, False),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_730_days"
            ),
            PolicyExpectation(
                "security_policy",
                "condition_required",
                "prototype_requires_security_contact_plan",
                "Record a security contact and escalation plan for prototype use.",
            ),
        ),
    ),
    Scenario(
        scenario_id="E05",
        description="old commit for critical long lived use",
        terminal_expectation="completed",
        context=ContextExpectation(
            "Long-lived critical internal dependency",
            "internal",
            "critical",
            1_825,
            "tolerant",
        ),
        latest_commit_age_days=365,
        expected_evidence=HEALTHY_EVIDENCE,
        expected_metrics=_available_metrics(False, True, 365, True),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency", "fail", "latest_commit_older_than_180_days"
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
    ),
    Scenario(
        scenario_id="E06",
        description="tolerant context over paired repository facts",
        terminal_expectation="completed",
        context=TOLERANT_CONTEXT,
        license_present=False,
        latest_commit_age_days=365,
        security_policy_present=False,
        expected_evidence=(
            HEALTHY_EVIDENCE[0],
            EvidenceExpectation("license_status", "available", "absent", "current"),
            HEALTHY_EVIDENCE[2],
            EvidenceExpectation(
                "security_policy_present", "available", False, "current"
            ),
        ),
        expected_metrics=_available_metrics(False, False, 365, False),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation(
                "license_declared",
                "condition_required",
                "prototype_requires_license_resolution_before_broader_use",
                "Resolve and document the license before use expands beyond the prototype.",
            ),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_730_days"
            ),
            PolicyExpectation(
                "security_policy",
                "condition_required",
                "prototype_requires_security_contact_plan",
                "Record a security contact and escalation plan for prototype use.",
            ),
        ),
    ),
    Scenario(
        scenario_id="E07",
        description="low risk tolerance over paired repository facts",
        terminal_expectation="completed",
        context=ContextExpectation(
            TOLERANT_CONTEXT.intended_use,
            TOLERANT_CONTEXT.environment,
            TOLERANT_CONTEXT.criticality,
            TOLERANT_CONTEXT.expected_lifetime_days,
            "low",
        ),
        license_present=False,
        latest_commit_age_days=365,
        security_policy_present=False,
        expected_evidence=(
            HEALTHY_EVIDENCE[0],
            EvidenceExpectation("license_status", "available", "absent", "current"),
            HEALTHY_EVIDENCE[2],
            EvidenceExpectation(
                "security_policy_present", "available", False, "current"
            ),
        ),
        expected_metrics=_available_metrics(False, False, 365, False),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation(
                "license_declared", "fail", "license_is_not_declared"
            ),
            PolicyExpectation(
                "commit_recency", "fail", "latest_commit_older_than_180_days"
            ),
            PolicyExpectation(
                "security_policy", "fail", "security_policy_is_absent"
            ),
        ),
    ),
    Scenario(
        scenario_id="E08",
        description="unavailable latest commit from empty repository response",
        terminal_expectation="completed",
        context=TOLERANT_CONTEXT,
        latest_commit_age_days=None,
        expected_evidence=(
            HEALTHY_EVIDENCE[0],
            HEALTHY_EVIDENCE[1],
            EvidenceExpectation(
                "latest_commit_timestamp",
                "unavailable",
                None,
                "unknown",
                "repository_has_no_commits",
                "repository_has_no_commits",
            ),
            HEALTHY_EVIDENCE[3],
        ),
        expected_metrics=(
            *_available_metrics(False, True, 30, True)[:2],
            MetricExpectation(
                "days_since_latest_commit",
                "unavailable",
                None,
                None,
                "insufficient",
                "evidence_unavailable:repository_has_no_commits",
            ),
            _available_metrics(False, True, 30, True)[3],
        ),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency",
                "not_evaluable",
                "required_metric_unavailable:days_since_latest_commit:"
                "evidence_unavailable:repository_has_no_commits",
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
        decision=DecisionExercise(
            "needs_more_information",
            "The latest repository activity could not be established.",
            information_requests=(
                "Provide authoritative repository activity evidence for maintenance review.",
            ),
        ),
    ),
    Scenario(
        scenario_id="E09",
        description="partial collection failure caused by rate limiting",
        terminal_expectation="collection_failed",
        context=TOLERANT_CONTEXT,
        expected_evidence=(),
        expected_metrics=(),
        expected_policy=(),
        rate_limit_latest_commit=True,
    ),
    Scenario(
        scenario_id="E10",
        description="corrupted durable evaluation detected during review",
        terminal_expectation="review_verification_failed",
        context=STRICT_PRODUCTION_CONTEXT,
        expected_evidence=HEALTHY_EVIDENCE,
        expected_metrics=_available_metrics(False, True, 30, True),
        expected_policy=(
            PolicyExpectation(
                "repository_not_archived", "pass", "repository_is_not_archived"
            ),
            PolicyExpectation("license_declared", "pass", "license_is_declared"),
            PolicyExpectation(
                "commit_recency", "pass", "latest_commit_within_180_days"
            ),
            PolicyExpectation(
                "security_policy", "pass", "security_policy_is_present"
            ),
        ),
        corrupt_evaluation_before_review=True,
    ),
)
