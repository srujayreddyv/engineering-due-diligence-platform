# Engineering Due Diligence Platform

> **Current status:** The Day 1 engagement foundation, reviewed Day 2 domain and
> failure models, deterministic Day 3 slice, Day 4 transient in-memory result
> assembly, and Day 5 transient request validation boundary are complete.
> GitHub existence checks, persistence, workflow, audit, collectors, reports,
> APIs, and human decisions remain unimplemented.

## Customer Problem

The simulated customer, Northstar Software, is a medium sized software
organization with approximately 60 engineers across six product teams. Teams
use inconsistent practices to evaluate open source repositories, and critical
dependencies require manual security review. Evidence, rationale, conditions,
and approvals can be difficult to reproduce across teams and over time.

This is a simulated four week Forward Deployed Engineering engagement. It does
not claim real customer interviews, production use, or measured business
impact.

## Project Mission

Build a reliable and auditable decision support workflow for evaluating whether
a public open source repository is appropriate for a specified engineering use
case.

The core abstraction is an assessment decision, not a repository. Intended use,
environment, criticality, expected lifetime, and organizational risk tolerance
can lead to different decisions about the same repository.

## Target Workflow

The scoped workflow will:

1. accept a public GitHub repository and its engineering use-case context;
2. validate the request;
3. collect evidence from authoritative sources;
4. store raw evidence with status and provenance;
5. calculate deterministic, versioned metrics;
6. evaluate context-specific, versioned policy;
7. generate a structured, evidence-grounded decision brief;
8. support engineering, security, and management review;
9. require a human to record the final decision; and
10. preserve the request, evidence, versions, report, decision, and audit
    timestamps.

AI is limited to grounded synthesis, tradeoff explanation, uncertainty
communication, and reviewer questions. It does not collect authoritative
evidence, calculate deterministic metrics, enforce policy, control workflow
state, or approve adoption.

## Scope

The four week scope is locked around one end-to-end assessment of a public
GitHub repository for one specified engineering use case. Private repositories,
additional source providers, continuous monitoring, automated installation or
remediation, technology comparisons, vendor reviews, AI model reviews,
automatic approval, and unjustified distributed infrastructure are out of
scope.

Deferred ideas are recorded in [docs/backlog.md](docs/backlog.md). A backlog
entry is not an active commitment.

## Current Project Status

Completed on Day 1:

* project mission, charter, simulated customer, stakeholders, and scope;
* current-workflow model and failure points;
* proposed auditable workflow and responsibility boundaries;
* separate system and prototype customer validation criteria;
* deferred backlog and documentation map; and
* Day 1 execution plan and journal.

Completed on Day 2:

* logical definitions for the seven assessment domain entities;
* entity ownership, identifiers, relationships, lifecycle boundaries,
  immutability, versioning, and audit obligations; and
* documented handling for incomplete evidence, repeat processing, human review,
  reassessment, and workflow interruption;
* final behavioral review of the corrected domain model and failure model; and
* failure taxonomy, stage-specific failure behavior, fail-closed rules,
  idempotency, recovery, audit, and security requirements.

Both Day 2 design documents are complete, passed behavioral review, and are
committed.

Committed on Day 3:

* immutable typed assessment context, evidence, metric, and policy records, with
  local canonical fixtures for the scoped public GitHub facts: archived status,
  license status, latest commit timestamp, and security policy presence;
* fail-closed evidence validation for required and duplicate records, canonical
  kinds, snapshot integrity and normalized values, valid available or
  unavailable states, timezone awareness, and future timestamps;
* versioned metric calculation plus canonical recalculation before policy
  findings are accepted; invalid evidence returns no metric collection, and
  invalid or altered metrics return no finding collection;
* exact UTC elapsed-duration maintenance policy: 180-day and 730-day boundaries
  are inclusive, while one second beyond either boundary fails;
  `days_since_latest_commit` remains a floored display metric;
* intrinsic validation before freshness handling; temporally valid stale or
  unknown evidence remains unavailable and produces `not_evaluable`;
* context-sensitive absent-license policy: `condition_required` for a prototype
  and `fail` for strict production; and
* deterministic, traceable evidence, metric, and finding identifiers, verified
  by 52 passing tests.

Committed on Day 4:

* a frozen transient `DeterministicAssessmentResult` that keeps one assessment
  context, its canonical evidence tuple, exact Day 3 metrics and findings, and
  the caller-supplied aware evaluation timestamp together in memory;
* one `evaluate_assessment` boundary that snapshots caller evidence once,
  delegates exactly once to `evaluate_slice`, canonically orders validated
  evidence, and constructs no partial result on failure;
* preservation of timestamp representations and complete evidence-to-metric-to-
  finding reference closure without duplicating Day 3 validation; and
* nine focused Day 4 tests, with all 61 repository tests passing.

Completed on Day 5:

* frozen transient `AssessmentRequestInput`,
  `AssessmentRequestValidationError`, and
  `AssessmentRequestValidationResult` contracts;
* one deterministic `validate_assessment_request` boundary that accepts
  submitted context, validates every field in a stable order, and produces the
  existing `AssessmentContext` only after the complete request is valid;
* structured field-level validation errors with one first-precedence error per
  field and no partial context or normalized identity on invalid input;
* strict HTTPS `github.com/<owner>/<repository>` locator validation and
  canonical `github.com/<owner>/<repository>` identity construction while
  preserving owner and repository casing and the exact submitted request; and
* 14 focused Day 5 tests, with all 75 repository tests passing.

Not yet implemented:

* persistence or workflow orchestration;
* GitHub repository existence or visibility checks and evidence collectors;
* audit recording or storage;
* assessment APIs;
* generated reports or AI/model integrations;
* human decisions or review interfaces;
* metrics and policy outside the four-kind local deterministic slice;
* databases, Docker, CI, deployment, or production observability; and
* prototype evaluation results.

## Four Week Milestones

| Week | Milestone | Status |
| --- | --- | --- |
| 1 | Engagement definition, domain and failure models, evaluation methodology, architecture decisions, and implementation plan | Day 1 foundation and Day 2 domain and failure models complete and committed; remaining Week 1 design work planned and not implemented |
| 2 | Tested deterministic foundation for assessment context, evidence, metrics, policy, persistence, and workflow | Transient request validation, deterministic context-to-policy slice, and result assembly verified; persistence and workflow remain planned |
| 3 | Minimum public GitHub collection, grounded report generation, human review, audit history, and essential observability | Planned |
| 4 | Evaluation, reliability improvements, limitations, and engagement handoff | Planned |

Milestones describe intended sequencing and are not claims of completed
capability.

## Documentation

### Engagement Documents

* [Project charter](docs/project_charter.md) — mission, customer, stakeholders,
  scope, deliverables, and governance.
* [Customer discovery](docs/customer_discovery.md) — simulated hypotheses,
  stakeholder questions, assumptions, and planned validation.
* [Current workflow](docs/current_workflow.md) — informal process and failure
  points to validate.
* [Proposed workflow](docs/proposed_workflow.md) — target workflow and system,
  AI, and human boundaries.
* [Domain model](docs/domain_model.md) — logical entities, relationships,
  lifecycle boundaries, immutability, versioning, and audit requirements.
* [Failure model](docs/failure_model.md) — failure taxonomy, stage behavior,
  idempotency, recovery, fail-closed, audit, and security requirements.
* [Success criteria](docs/success_criteria.md) — system metrics and separate
  prototype customer validation measures.
* [Backlog](docs/backlog.md) — deferred ideas outside active scope.

### Engineering Context

* `AGENTS.md` defines contributor behavior, required context, and scope
  controls.
* `memory/` contains durable repository knowledge that agents read before
  tasks.
* `docs/adr/` holds meaningful architectural decisions.
* `docs/checkpoints/` holds engagement checkpoints.
* `plans/` holds temporary task execution plans.
* `journal/` records what actually happened during the engagement.
* `templates/` contains reusable planning and review structures.

## Repository Structure

```text
.
├── AGENTS.md
├── README.md
├── data/
├── docs/
│   ├── adr/
│   └── checkpoints/
├── examples/
├── journal/
├── memory/
├── plans/
├── scripts/
├── src/engineering_due_diligence/
├── templates/
└── tests/
```

The Python package now contains the dependency-free transient request
validation boundary, deterministic slice, and in-memory result assembly. It is
library code rather than an API or deployed application. Run its tests from the
repository root with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Working in This Repository

Before planning or editing:

1. read `AGENTS.md`;
2. read every file under `memory/`;
3. read the project charter and backlog;
4. read relevant ADRs and the current task plan; and
5. preserve the locked scope and documentation-layer boundaries.

The current active plan is
[plans/day_05_assessment_request_validation.md](plans/day_05_assessment_request_validation.md).
