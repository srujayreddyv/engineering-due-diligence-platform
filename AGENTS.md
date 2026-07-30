# AI Software Engineering Memory

## Project Mission

Build a reliable and auditable decision support workflow for evaluating whether
a public open source repository is appropriate for a specified engineering use
case.

## Mandatory Context

Before planning or editing, read:

1. memory/CODEBASE.md
2. memory/ARCHITECTURE.md
3. memory/PATTERNS.md
4. memory/DECISIONS.md
5. docs/project_charter.md
6. docs/backlog.md
7. The relevant ADRs and task plan

## Scope Control

The four week scope is locked.

Do not introduce new domains, frameworks, infrastructure, agents, interfaces,
or collectors unless they are required by the primary workflow, correctness,
security, reliability, evaluation results, or essential customer feedback.

Record useful but nonessential ideas in docs/backlog.md.

## Implementation Rules

1. Preserve the distinction between evidence, metrics, policy findings, model
   interpretation, and human decisions.
2. Store raw evidence before calculating conclusions.
3. Keep deterministic logic outside model prompts.
4. Require type-correct references for significant generated claims: direct
   factual claims cite `EvidenceRecord`, calculated claims cite the exact
   `MetricResult`, and policy conclusions cite the exact `PolicyFinding`.
   Every reference must belong to the fixed report input set.
5. Prefer a modular application over unnecessary distributed infrastructure.
6. Add tests for every behavior change.
7. Do not perform unrelated refactoring.
8. Do not update memory with ordinary task history.
9. Create ADRs for meaningful architectural decisions.
10. Update the daily journal after completing work.

## Before Implementation

1. Understand the task and expected outcome.
2. Read:
   * `memory/CODEBASE.md`
   * `memory/ARCHITECTURE.md`
   * `memory/PATTERNS.md`
   * `memory/DECISIONS.md`
3. State assumptions and unclear requirements.
4. Create a task plan before changing code.
5. Define how the work will be verified.

## Implementation

1. Follow the approved plan.
2. Prefer existing patterns.
3. Make minimal changes.
4. Avoid unrelated refactoring.
5. Preserve architectural boundaries.
6. Update tests when behavior changes.
7. Keep new abstractions justified by current needs.
8. Remove only unused code introduced by the task.

## Review

Review:

* Correctness
* Security
* Performance
* Maintainability
* Backward compatibility
* Test coverage

Document material risks before finalizing the work.

## Information Layers

Keep these documentation layers distinct:

* `memory/` stores durable repository knowledge that future agents must read before every task. Do not put daily progress, issue status, or task notes here.
* `docs/` stores complete human-facing project and engagement documentation, including the project charter, discovery, workflows, architecture, domain and failure models, evaluation methodology, deployment instructions, ADRs, and checkpoints.
* `plans/` stores temporary implementation plans created before meaningful coding tasks. Plans describe how the current task will be executed and may become obsolete.
* `journal/` stores chronological records of what happened during the engagement, organized as daily entries.

Classify information by its future use:

* Memory is what future agents must know.
* Docs are what humans need to understand the project.
* Plans describe how the current task will be executed.
* Journal entries record what happened.

Do not use one layer as a substitute for another. When task or journal information reveals a durable fact, record only the durable fact in the appropriate memory file rather than copying the task history.

`templates/` contains reusable document structures. Use `TASK_PLAN_TEMPLATE.md` for plans and `REVIEW_TEMPLATE.md` for reviews; do not store task-specific plans or reviews in `templates/`.

## Memory Updates

Update memory when:

* Repository structure changes
* Architecture changes
* Patterns change
* New engineering decisions are made
* Existing decisions are superseded

Do not update memory for ordinary task history, release notes, or implementation details that are obvious from source code.

## Additional Rules

* Prefer consistency over novelty.
* Document assumptions.
* Document risks.
* Prefer incremental changes.
* Preserve existing conventions.
* Keep files concise and high signal.
* Do not invent process when memory is enough.
