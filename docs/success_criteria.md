# Success Criteria

## Status

These are initial acceptance criteria for the four week prototype and simulated
customer validation. They are targets and measurement definitions, not results.

No baseline, customer outcome, production performance, time savings, cost
savings, risk reduction, or business impact has been measured on Day 1.

## Evaluation Principles

* System behavior and customer workflow validation are measured separately.
* A system result is not evidence of customer value by itself.
* A customer preference does not override correctness, security, evidence, or
  audit requirements.
* Missing data is reported as missing and lowers confidence.
* Evaluation results must include the scenario, versions, method, sample size,
  and observed result.
* Targets may be refined through essential customer feedback, but scope remains
  locked.

## System Metrics

System metrics evaluate whether the prototype behaves correctly and preserves
the required boundaries.

| ID | Metric | Initial acceptance threshold | Measurement method |
| --- | --- | --- | --- |
| S01 | Workflow artifact completeness | 100% of completed evaluation assessments retain the request, evidence, metrics, policy findings, versions, report, human decision, and audit timestamps | Inspect persisted records for every completed assessment in the evaluation set |
| S02 | Evidence provenance completeness | 100% of evidence records contain source, collection time, status, and an evidence identifier; provenance and freshness are present whenever the source exposes them | Schema validation and record inspection |
| S03 | Evidence-before-derivation ordering | 100% of metric and policy results reference evidence that was stored before the result timestamp | Automated integration assertions over the evaluation set |
| S04 | Deterministic metric reproducibility | 100% identical metric outputs for identical evidence and calculation versions | Repeat each calculation at least twice and compare structured results |
| S05 | Policy traceability | 100% of policy findings identify the evaluated requirement, policy version, outcome, and causing evidence or metric identifiers | Schema validation plus sampled manual review |
| S06 | Generated-claim grounding | 100% of material report claims use a type-correct reference from the fixed report input set: direct factual claims cite `EvidenceRecord`, calculated claims cite the exact `MetricResult`, and policy conclusions cite the exact `PolicyFinding` | Automated typed-reference and fixed-input-membership validation, deterministic grounding validation, and manual semantic review of all evaluation reports |
| S07 | Missing-evidence safety | 0 test cases invent, silently pass, or replace missing evidence; every missing input is visible in status or confidence | Unit and integration tests for unavailable, stale, partial, and failed evidence |
| S08 | Human decision ownership | 0 assessments receive an automatic final adoption decision; 100% of final dispositions have a human reviewer identity and timestamp | Workflow authorization tests and audit-record inspection |
| S09 | Retry and interruption integrity | 100% of defined retryable failures preserve prior attempts, and completed stages are not repeated without an explicit reason | Integration tests for each defined failure category |
| S10 | Structured output validity | 100% of accepted AI-assisted reports conform to the approved schema and have `passed` structural, reference, and deterministic grounding validation; 0 reports are `valid` when any required validation is `failed` or `not_run` | Validation-gate tests covering every required validation status, including failed and not-run cases; S06 separately verifies claim-level typed grounding |

Performance thresholds will be set only after the evaluation environment and
minimum evidence sources are defined. Until then, latency observations are
reported descriptively and are not pass/fail criteria.

## Prototype Customer Validation Metrics

Prototype customer validation measures whether the proposed workflow and its
outputs help the simulated stakeholder roles perform review tasks. These
measures do not claim real-world business impact.

| ID | Validation measure | Initial acceptance threshold | Planned method |
| --- | --- | --- | --- |
| C01 | Context capture sufficiency | All four stakeholder roles can identify the intended use, environment, criticality, expected lifetime, risk tolerance, and decision owner in each walkthrough | Role-based review of at least three representative assessment scenarios |
| C02 | Evidence traceability task | At least 90% of sampled material claims can be traced without facilitator correction to the type-correct record in the fixed report input set: direct facts to `EvidenceRecord`, calculations to `MetricResult`, and policy conclusions to `PolicyFinding` | Give each role a fixed set of direct-fact, calculated-claim, and policy-conclusion traceability tasks and record task completion |
| C03 | Uncertainty recognition | All four stakeholder roles correctly identify intentionally missing evidence and state that it requires lower confidence or further investigation | Include missing-evidence cases in the walkthrough set |
| C04 | Decision readiness | For every walkthrough, the designated human reviewer can either select one allowed disposition or name the specific additional evidence required | Observe the final review task and record disposition or investigation request |
| C05 | Role and handoff clarity | All four stakeholder roles can state their responsibility and the next owner at each handoff relevant to them | Structured workflow walkthrough and comprehension questions |
| C06 | Audit-record usability | All four stakeholder roles can locate the original request, cited evidence, policy version, report, human decision, and timestamps in a completed example | Fixed retrieval tasks against the prototype record |
| C07 | Workflow fit | For every required step in each of at least three scenarios, at least three of the four respondents answer Yes to: "Can you complete your assigned responsibility at this step without bypassing the step or using information outside the assessment record?" Every No response has a documented reason. | One respondent from each stakeholder role—Platform Engineering Lead, Application Security Engineer, Staff Software Engineer, and Engineering Manager—answers independently. A written mitigation may satisfy a failing step only when the Platform Engineering Lead and Application Security Engineer jointly approve that it remains within locked scope and preserves security and audit boundaries. |

Because the customer is simulated, Day 1 can define these exercises but cannot
report authentic customer results. Any later simulated walkthrough result must
be labeled as simulated.

## Required Evaluation Scenarios

The final evaluation set should include at least:

1. a complete evidence case that can proceed to human decision;
2. a case with required evidence unavailable;
3. a case with stale or partial evidence;
4. a case that triggers a policy condition or further investigation;
5. a retryable collector failure; and
6. invalid or unsupported generated claims.

Specific repositories and use cases will be selected later and recorded with
the evaluation methodology. Selection must not expand beyond public GitHub
repositories or the scoped workflow.

## Evidence Required for a Completion Claim

The engagement may call the prototype workflow complete only when:

* the system metrics above have recorded results and material failures are
  resolved or explicitly accepted;
* each generated report in the evaluation set passes structured grounding
  review;
* each final decision is human-recorded;
* customer validation observations are reported separately from system results;
* known limitations and sample sizes are visible; and
* the handoff does not describe planned or mocked behavior as production-ready.

## Explicit Non-Claims

The engagement does not currently claim:

* reduced review time;
* reduced security incidents;
* increased developer productivity;
* lower operating cost;
* improved adoption quality;
* production reliability; or
* organization-wide customer acceptance.

Such claims require real baselines, real users, an appropriate sample, and an
agreed measurement period outside Day 1 documentation.
