# Day 2 Failure Model Plan

## Task

Define the failure behavior for every stage of the scoped Engineering Due
Diligence Platform workflow without implementing application code or choosing
runtime, persistence, queue, retry-library, or infrastructure mechanisms.

## Objective

Create one implementation-neutral failure reference that explains how failures
are detected, classified, recorded, retried, surfaced, and recovered without
creating partially valid records or corrupting authoritative history.

Success means a later implementation can fail closed where correctness or
auditability requires it, continue only with explicit policy-permitted
uncertainty, resume from the earliest affected stage, and preserve idempotency
and provenance across every retry.

## Current State

The Day 1 engagement foundation is committed. The Day 2 domain model has passed
final read-only review and defines seven sufficient entities:
`AssessmentRequest`, `EvidenceRecord`, `MetricResult`, `PolicyFinding`,
`GeneratedReport`, `HumanDecision`, and `AuditEvent`.

The domain model already establishes append-only authoritative records,
evidence-before-derivation ordering, typed report grounding, deterministic
workflow ownership, one authoritative final human decision, and an indivisible
final-decision completion operation. No application, database, API, collector,
model integration, retry mechanism, queue, Docker, CI, or infrastructure
implementation exists.

## Assumptions

* This task defines logical failure behavior and invariants, not exception
  classes, status codes, payloads, database records, or retry jobs.
* The existing seven domain entities are sufficient. Failure information is
  preserved through workflow state, complete outcome records where the domain
  permits them, and `AuditEvent`.
* Retry counts, delays, backoff, jitter, circuit thresholds, service-level
  targets, and escalation timing remain deferred configuration.
* Continuing with missing, partial, failed, or stale evidence is allowed only
  when deterministic policy explicitly permits review with visible
  uncertainty.
* Security-sensitive diagnostic detail can be correlated without retaining
  secrets, credentials, or unnecessary external payloads.

## Acceptance Criteria

* The failure model defines twenty-seven failure categories: the original
  twenty-five categories plus narrowly scoped categories for incomplete human
  submissions and non-evidence authoritative-record persistence failures. Each
  category includes retryability, human resolvability, terminality, and normal
  disposition.
* Successful replay and expected invalidation are deterministic control
  outcomes rather than failures, and report generation failure remains
  distinct from candidate validation failure.
* Every proposed workflow stage has a structured failure table covering
  classification, retryability, stop or continue behavior, authoritative record
  behavior, audit behavior, idempotency, recovery entry point, and human
  visibility.
* Failed or interrupted attempts never create partially valid authoritative
  records.
* Evidence failure outcomes remain explicit and never become favorable facts.
* Required request, persistence, metric, policy, report-validation,
  authorization, final-decision, and audit operations fail closed.
* Retry and recovery rules cover request submission, collection, persistence,
  calculation, evaluation, generation, validation, investigation routing,
  human decisions, and audit recording without duplicating authoritative
  results.
* Resumption reuses completed work only when inputs, versions, freshness,
  record validity, and investigation scope remain compatible.
* Human-visible uncertainty, security sanitization, and minimum failure
  information are explicit.
* The model remains consistent with the domain model, proposed workflow,
  success criteria, durable memory, and locked scope.
* No new domain entity, application behavior, database design, API contract,
  dependency, collector, model integration, Docker, CI, monitoring
  configuration, or infrastructure design is introduced.
* `journal/day_02.md` records completed work, decisions, assumptions,
  verification, deferrals, and the exact next task honestly.

## Proposed Solution

1. Define terminology, ownership, failure information, and disposition rules.
2. Classify all required failure categories without inventing operational
   thresholds.
3. Document failure behavior for each workflow and validation stage.
4. Define conceptual retry, idempotency, recovery, resumption, and fail-closed
   invariants.
5. Define reviewer visibility and security/privacy requirements.
6. Validate the failure model against the seven-entity domain model and system
   success criteria.
7. Update the Day 2 journal after the documentation and verification are
   complete.

## Files Affected

* `plans/day_02_failure_model.md` — execution plan for this documentation task.
* `docs/failure_model.md` — failure taxonomy, stage behavior, recovery rules,
  and audit and security requirements.
* `README.md` — current Day 2 documentation status, failure-model index entry,
  and active-plan link.
* `journal/day_02.md` — append-only record of completed Day 2 failure-model
  work.

No memory, domain-model, source, test, dependency, database, API, deployment,
CI, or infrastructure file is expected to change.

## Database Impact

None. This task does not define tables, columns, indexes, constraints,
transactions, repositories, migrations, fixtures, or storage technology.
Logical atomicity and idempotency requirements remain implementation-neutral.

## Testing Strategy

No runtime tests are added because no behavior is implemented.

Documentation verification will:

* confirm all twenty-seven failure categories have retryability and disposition
  rules and that every stage-table assignment matches its category definition;
* confirm F16 applies only before a candidate exists and F17, F18, and F19
  exclusively classify candidate validation failures;
* confirm successful replay and normal invalidation receive no failure
  category;
* confirm all fifteen workflow stages have structured failure behavior;
* confirm partial authoritative records cannot be created;
* confirm missing, partial, failed, and stale evidence never become success;
* confirm retry and resumption rules preserve history and avoid duplicate
  authoritative results;
* confirm fail-closed behavior for every required operation;
* confirm invalid or ungrounded reports cannot reach human review;
* confirm failure records require no secrets or credentials;
* confirm the seven domain entities remain sufficient;
* compare the model with `docs/domain_model.md`,
  `docs/proposed_workflow.md`, `docs/success_criteria.md`, and durable memory;
* validate all local Markdown links and Markdown whitespace;
* run `git diff --check`; and
* confirm no application or infrastructure artifact changed and nothing is
  staged, committed, or pushed.

## Risks

* **Failure taxonomy overlap:** One incident may match several categories.
  Mitigation: require one primary category plus related categories without
  changing disposition authority.
* **Unsafe continuation:** Missing data could be mistaken for success.
  Mitigation: allow continuation only through explicit deterministic policy
  with visible uncertainty.
* **Duplicate history:** Retried operations could create conflicting records.
  Mitigation: define logical idempotency and append-only successor rules for
  every repeated operation.
* **Audit gaps:** A business operation could appear complete without its audit
  event. Mitigation: fail closed for required audit recording and define
  idempotent recovery.
* **Sensitive diagnostics:** External errors could expose credentials or
  protected resource details. Mitigation: separate sanitized human
  explanations from internal diagnostic references and prohibit secrets.
* **Premature implementation design:** Retry or persistence details could imply
  a runtime architecture. Mitigation: defer operational values and mechanisms.

## Rollback Plan

Remove the new failure-model plan and document and revert only the appended
failure-model journal section. No runtime behavior, persisted assessment data,
external system, or committed Day 1 history would be affected.

## Implementation Checklist

* [x] Read required agent guidance, memory, project documentation, plans,
  journals, and templates.
* [x] Inspect the repository and confirm the Day 2 domain model passed review.
* [x] Define assumptions, acceptance criteria, and verification strategy.
* [x] Define the failure taxonomy and dispositions.
* [x] Define stage-specific failure behavior.
* [x] Define idempotency, recovery, resumption, fail-closed, audit, and security
  rules.
* [x] Validate domain-model and success-criteria alignment.
* [x] Update `journal/day_02.md` honestly.
* [x] Run the complete documentation and repository-scope verification.
