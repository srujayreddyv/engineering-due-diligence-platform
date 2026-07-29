# Engineering Due Diligence Platform

> **Current status:** Day 1 engagement foundation. The repository contains the
> project definition, durable engineering context, and documentation scaffold.
> The assessment workflow is planned but not implemented.

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

Not yet implemented:

* assessment APIs or workflow orchestration;
* evidence collectors or persistence;
* metric calculators or policy evaluation;
* AI or model integrations;
* human-review interfaces or audit storage;
* databases, Docker, CI, deployment, or production observability; and
* prototype evaluation results.

## Four Week Milestones

| Week | Milestone | Status |
| --- | --- | --- |
| 1 | Engagement definition, domain and failure models, evaluation methodology, architecture decisions, and implementation plan | Day 1 foundation complete; remaining design work planned |
| 2 | Tested deterministic foundation for assessment context, evidence, metrics, policy, persistence, and workflow | Planned |
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

The Python package and test package currently contain empty `__init__.py`
markers only. There are no installation or runtime instructions because no
application has been scaffolded.

## Working in This Repository

Before planning or editing:

1. read `AGENTS.md`;
2. read every file under `memory/`;
3. read the project charter and backlog;
4. read relevant ADRs and the current task plan; and
5. preserve the locked scope and documentation-layer boundaries.

The current execution plan is
[plans/day_01_engagement_foundation.md](plans/day_01_engagement_foundation.md).
