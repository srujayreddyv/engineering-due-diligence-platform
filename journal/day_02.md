# Day 2 — Domain Model

**Date:** 2026-07-29

**Engagement:** Engineering Due Diligence Platform

**Status:** The domain and failure models passed behavioral review and remain
uncommitted; application implementation not started

## Day 2 Objective

Define the logical domain records, ownership, relationships, lifecycle rules,
immutability, versioning, audit obligations, and incomplete-data behavior for
the scoped assessment workflow before selecting a database schema or writing
application code.

## Context Reviewed

Before planning or editing:

* read `AGENTS.md` and every file under `memory/`;
* read `README.md` and every current document under `docs/`;
* read `plans/day_01_engagement_foundation.md`;
* read `journal/day_01.md`;
* inspected the repository, Git state, templates, source and test placeholders,
  and ADR directory; and
* confirmed that the working tree was clean and no ADRs or application
  implementation existed.

## Work Completed

1. Created `plans/day_02_domain_model.md` before changing the domain
   documentation.
2. Created `docs/domain_model.md` as an implementation-neutral domain contract.
3. Defined the purpose, ownership, required and optional logical fields,
   identifier strategy, lifecycle states, valid transitions, relationships,
   immutability, versioning, audit requirements, and incomplete-data behavior
   for:
   * `AssessmentRequest`;
   * `EvidenceRecord`;
   * `MetricResult`;
   * `PolicyFinding`;
   * `GeneratedReport`;
   * `HumanDecision`; and
   * `AuditEvent`.
4. Defined `AssessmentRequest` as the aggregate root for one repository and one
   specified engineering use case.
5. Defined the primary relationship chain from request through evidence,
   metrics, policy, generated report, and human decision.
6. Defined `AuditEvent` as an append-only activity record that references but
   never replaces authoritative domain records.
7. Defined explicit behavior for failed, missing, stale, and partial evidence;
   recollection; metric recalculation; policy changes; report regeneration;
   human investigation requests; conditional approval; context-specific
   reassessment; and workflow interruption or resumption.
8. Reviewed the draft for contradictory ownership, invalid transitions, hidden
   model authority, evidence-provenance loss, universal scoring, and scope
   expansion.
9. Corrected two review issues:
   * removed policy-engine failure detail from `PolicyFinding` because an engine
     failure is workflow failure, not a policy outcome; and
   * clarified that an audit write failure fails the operation rather than
     becoming a persisted `AuditEvent` lifecycle state.

## Read-Only Review Result

After the original domain model was completed, a read-only review using
`templates/REVIEW_TEMPLATE.md` returned **Needs Changes**.

The review confirmed these findings:

1. final human decisions lacked an explicit one-per-assessment and idempotency
   invariant;
2. freshness at time of use was not fully preserved for historical metric and
   policy reproduction;
3. transient operation states were mixed with authoritative persisted record
   states;
4. generated-report reference resolution did not fully define typed grounding
   or human semantic review;
5. further investigation always returned to evidence collection;
6. predecessor and supersession links lacked explicit type, assessment,
   ordering, self-reference, and cycle constraints;
7. the relationship diagram omitted the direct metric-to-report input; and
8. README still described Day 1 as the current repository state.

The review also concluded that the seven entities remain sufficient for the
locked workflow. It did not recommend another entity.

## Review Corrections Applied

The documentation was corrected to:

* permit at most one authoritative final `HumanDecision` per assessment;
* add `decision_submission_id` and define same-submission replay and conflicting
  final-decision rejection;
* define final-decision recording, assessment completion, and the corresponding
  audit event as one indivisible logical domain operation without selecting
  database transaction syntax;
* preserve the evidence identifier, freshness status used, freshness evaluation
  time, and freshness rule version whenever freshness affects a metric or
  policy result;
* distinguish freshness at collection from freshness at use;
* separate transient orchestration attempts from complete authoritative domain
  records for all seven entities;
* require exact typed report references from the fixed input set and separate
  structural, reference, deterministic grounding, and human semantic review;
* route human investigation requests deterministically to the earliest affected
  collection, metric, policy, or report stage;
* constrain every prior or supersedes link to an earlier, same-assessment,
  type-correct, nonself, acyclic record;
* add the direct `MetricResult` to `GeneratedReport` relationship; and
* update README with the Day 1 completion, Day 2 correction status,
  domain-model link, absence of application code, and active Day 2 plan.

## Domain Decisions Documented

* The assessment is the aggregate root; a repository does not have one
  context-free disposition.
* Opaque record identifiers are stable and do not encode repository or mutable
  business meaning. The identifier algorithm remains deferred.
* Submitted assessment context becomes immutable. Material corrections or a
  different use case create a related assessment.
* Stored evidence and derived records are append-only. Repeated work creates
  linked successor records.
* Evidence collection outcome and evidence freshness are separate from workflow
  lifecycle state.
* Failed or unavailable evidence remains a domain fact and cannot silently
  become a metric value or policy pass.
* Deterministic software owns validation, workflow state, metrics, policy, and
  reference validation.
* AI output is preserved and validated but is not authoritative evidence,
  policy, workflow state, or a human decision.
* A human request for further investigation is a recorded nonfinal disposition
  that returns the assessment to the affected stages.
* Approve, approve with conditions, and reject are final for the assessment
  context. Later facts or policy require a new assessment rather than mutation.
* Audit events accompany domain changes but are not the only location for
  domain content.

## Important Assumptions

* The domain fields are logical attributes, not database columns or API fields.
* The first workflow continues to cover one public GitHub repository and one
  specified engineering use case.
* Deterministic policy may permit human review with explicit unavailable
  evidence in some contexts; missing evidence is never silently favorable.
* Versioned authorization rules can express required human participation.
* The retained source snapshot can preserve authoritative facts and provenance
  without retaining secrets or unnecessary personal information.
* Recording condition text, owner, and verification criterion is sufficient for
  the scoped decision record without implementing condition monitoring.

## Unresolved Questions

* Which evidence kinds and authoritative GitHub sources are mandatory for the
  first vertical slice?
* Who approves nonsecurity policy, and which reviewer roles are required for
  each criticality?
* Which freshness rule applies to each evidence kind, and who approves changes?
* What retention and access-control requirements apply to evidence, model
  output, reviewer identity, and audit history?
* Is a separately governed correction process required for an accidentally
  recorded final decision, or must correction always use a new assessment?
* Which identifier algorithm, integrity mechanism, and persistence transaction
  strategy will implement the logical guarantees?

These questions were documented but not answered without customer or
architecture evidence.

## Work Not Implemented

No application behavior was implemented. Specifically, Day 2 did not add:

* Pydantic or other runtime domain models;
* FastAPI routes or request handling;
* a database schema, PostgreSQL migration, query, repository, or fixture;
* collectors or GitHub API integration;
* metric calculators or policy rules;
* prompt content, model integration, or report-generation code;
* human-review interfaces or authorization;
* workflow orchestration, audit persistence, or observability;
* Docker, CI, deployment, or infrastructure; or
* continuous monitoring, automated remediation, or other backlog scope.

## Original Verification Performed

* Confirmed all seven required entity sections exist.
* Confirmed every entity contains all twelve required definition categories.
* Confirmed all twelve required cross-cutting scenarios have explicit behavior.
* Compared the model with the charter, current workflow, proposed workflow,
  success criteria, architecture memory, engineering patterns, and durable
  decisions.
* Reviewed lifecycle transitions and terminal-state behavior.
* Searched for hidden AI approval or deterministic authority.
* Confirmed the model rejects a universal repository score.
* Confirmed persistence representation and runtime implementation remain
  explicitly deferred.
* Ran Git whitespace and diff validation during drafting.
* Validated every local Markdown link across the repository.
* Confirmed the only working-tree changes are the Day 2 plan, domain model, and
  journal entry.
* Confirmed the existing Python files remain empty package markers and no
  runtime, dependency, schema, Docker, CI, or infrastructure artifact was
  added.

## Correction Verification Performed

* Reviewed the complete README diff and the complete corrected contents of the
  Day 2 plan, domain model, and journal.
* Ran `git diff --check` and checked the corrected Markdown files for trailing
  whitespace and final newlines.
* Validated every local Markdown link across all 19 Markdown files.
* Confirmed all seven entities remain sufficient and retain every required
  definition category.
* Confirmed one authoritative final `HumanDecision` per assessment, idempotent
  replay, conflicting-final rejection, and indivisible completion behavior are
  explicit.
* Confirmed `MetricResult` and `PolicyFinding` preserve the evidence identifier,
  freshness status used, evaluation timestamp, and freshness rule version.
* Confirmed every entity distinguishes transient orchestration activity from
  the beginning of a complete authoritative record.
* Confirmed direct evidence, metric-derived, and policy claims use exact typed
  references from the report's fixed input set, with separate structural,
  reference, deterministic grounding, and human semantic checks.
* Confirmed further investigation can resume at evidence collection, metric
  calculation, policy evaluation, or report generation as determined by
  deterministic workflow logic.
* Confirmed successor links are append-only, type-correct, same-assessment,
  earlier, nonself, and acyclic.
* Confirmed the only working-tree changes are README and the three Day 2
  documentation files; nothing is staged.
* Confirmed both Python package markers remain empty and no application,
  dependency, database, API, Docker, CI, collector, model, or infrastructure
  artifact was added.
* Confirmed no commit or push occurred; `HEAD` remains at the committed Day 1
  cleanup.

## Exact Next Task

Repeat the read-only Day 2 domain-model review using
`templates/REVIEW_TEMPLATE.md`. If it returns Pass, create
`plans/day_02_failure_model.md`, then create `docs/failure_model.md` defining
failure categories, retryability, stage-specific stop or continue rules,
idempotent recovery, and audit behavior for the already scoped workflow. No
application code begins before that review passes.

## Second Review and Correction Follow-Up

The second read-only domain-model review returned **Needs Changes** with two
remaining documentation findings:

1. `GeneratedReport` defined deterministic grounding validation but did not
   require that validation to pass in every lifecycle rule that allowed a
   report to become valid or advance to human review.
2. Repository-level grounding language still named only evidence and policy
   findings, which conflicted with the domain rule requiring calculated claims
   to cite the exact `MetricResult`.

Corrections completed:

* made `validation_status=valid` conditional on `passed` structural, reference,
  and deterministic grounding validation;
* made any `failed` or `not_run` required validation produce an unusable report
  that cannot advance to human review;
* clarified that an unsupported material claim makes the report unusable rather
  than merely lowering confidence;
* clarified that human semantic review begins only after the deterministic
  validity gate and may still reject, question, or request investigation into
  a valid report;
* preserved deterministic ownership of all three validation layers and denied
  the model authority to validate its own output;
* aligned agent instructions, durable patterns and decisions, the charter,
  proposed workflow, customer discovery, and success criteria with typed
  references from the fixed report input set; and
* updated the Day 2 plan acceptance and verification language without changing
  its completed scope.

Verification performed:

* reviewed the complete documentation diff;
* ran `git diff --check`;
* validated all 19 local Markdown links across all 19 Markdown files;
* searched for older statements requiring only evidence or policy-finding
  references and found none remaining;
* confirmed the domain model permits `valid` only when all three deterministic
  validation statuses are `passed`;
* confirmed `failed` or `not_run` deterministic grounding cannot advance an
  assessment to `awaiting_human_review`;
* confirmed human semantic review remains distinct and follows the
  deterministic gate;
* confirmed all seven domain entities remain unchanged and sufficient;
* confirmed both Python package files remain empty; and
* confirmed no application, database, API, dependency, Docker, CI, collector,
  model integration, or infrastructure artifact was added.

No application code exists. Nothing was staged, committed, or pushed during
these corrections.

### Exact Next Task After Second Corrections

Repeat the read-only Day 2 domain-model review using
`templates/REVIEW_TEMPLATE.md`. If the result is Pass, create
`plans/day_02_failure_model.md` and then `docs/failure_model.md` for the already
scoped workflow. Do not begin application implementation before the corrected
domain model passes review.

## Failure Model Work

After the Day 2 domain model passed final read-only review:

1. Created `plans/day_02_failure_model.md` before writing the failure model.
2. Created `docs/failure_model.md` as an implementation-neutral contract for
   classifying, recording, retrying, surfacing, and recovering from failures.
3. Defined all twenty-five originally required failure categories with
   detection, retryability, human resolvability, terminality, and normal
   disposition. A later combined-review correction added two narrowly scoped
   categories, bringing the final taxonomy to twenty-seven.
4. Defined structured failure behavior for all fifteen workflow and validation
   stages.
5. Defined the eight allowed workflow responses and the conditions under which
   each is permitted.
6. Defined minimum failure information through workflow state and `AuditEvent`
   without creating a new domain entity.
7. Defined conceptual idempotency for request submission, evidence collection
   and persistence, metric calculation, policy evaluation, report generation
   and validation, investigation routing, human decisions, and audit recording.
8. Defined earliest-stage recovery, record-reuse requirements, fail-closed
   behavior, human-visible uncertainty, and security and privacy boundaries.
9. Validated the failure behavior against the domain model and success
   criteria. No contradiction requiring a domain-model change was found.
10. Updated `README.md` with the passed domain-model status, documented
    failure-model status, failure-model index entry, and active plan.

### Important Failure Decisions

* Failed or interrupted operations create no partially valid authoritative
  record.
* Complete evidence attempts may record available, partial, unavailable, or
  failed outcomes, but absence and failure never become favorable evidence.
* Continuing with uncertainty requires explicit deterministic policy
  permission and visible uncertainty.
* Persistence, required calculations and policy evaluation, all report
  validation layers, reviewer authorization, final-decision uniqueness, and
  final completion with audit recording fail closed.
* Report structural, reference, or deterministic grounding status of `failed`
  or `not_run` makes the report unusable.
* Identical logical retries do not duplicate authoritative results. Changed
  inputs, versions, freshness evaluations, or context create append-only
  successors.
* Audit recording failure prevents acknowledgement of the owning operation;
  `AuditEvent` never replaces a domain record.
* Internal invariant violations and unknown failures stop and require
  engineering investigation rather than guessed recovery.

### Failure-Model Assumptions

* Deterministic components can produce versioned failure classifications.
* Logical attempt and submission identities can be implemented without adding
  another domain entity.
* Policy can state when human review may continue with explicit uncertainty.
* Safe human-facing explanations can remain separate from protected diagnostic
  detail.
* Recovery can determine whether an authoritative record or event already
  became durable before replay.

### Unresolved Operational Values

The failure model intentionally does not choose:

* retry counts, budgets, delays, backoff, jitter, or timeout values;
* source-specific rate-limit and escalation thresholds;
* operational ownership and escalation timing;
* exact evidence and policy requirements;
* reviewer-authorization and policy-owner matrices;
* freshness rules;
* diagnostic and audit retention or access controls;
* identifier, integrity, atomicity, or persistence mechanisms; or
* a terminal-failure threshold for repeated nonterminal failures.

### Failure-Model Verification Performed

* Confirmed all 27 final failure categories are present once and have
  retryability and disposition rules.
* Confirmed all 15 required stages have a structured nine-column failure table.
* Confirmed the eight dispositions, ten idempotency cases, eight recovery
  scenarios, ten fail-closed requirements, ten domain alignments, and ten
  success-criteria alignments are documented.
* Confirmed partial authoritative records cannot be created.
* Confirmed missing, partial, failed, and stale evidence never become success.
* Confirmed final decision and audit operations fail closed and remain
  idempotent.
* Confirmed reports cannot bypass structural, reference, or deterministic
  grounding validation.
* Confirmed failure records require no secrets, credentials, or sensitive raw
  payloads.
* Confirmed all seven domain entities remain sufficient.
* Ran `git diff --check`.
* Validated all 25 local Markdown links across all 21 Markdown files.
* Confirmed both Python package files remain empty.
* Confirmed no application, dependency, database, API, queue, Docker, CI,
  collector, model integration, monitoring, or infrastructure artifact was
  added.
* Confirmed nothing is staged, committed, or pushed.

### Work Not Implemented

No failure-handling runtime behavior was implemented. There are no exception
types, retry jobs, queues, persistence operations, API responses, collectors,
model calls, monitoring rules, infrastructure changes, or measured reliability
results.

### Exact Next Task After the Failure Model

Perform a read-only review of `plans/day_02_failure_model.md`,
`docs/failure_model.md`, and this journal entry using
`templates/REVIEW_TEMPLATE.md`. Validate the failure model against
`docs/domain_model.md`, `docs/proposed_workflow.md`, and
`docs/success_criteria.md`. Do not begin application implementation until the
failure model passes review.

## Combined Day 2 Review and Taxonomy Corrections

The combined read-only review of the domain and failure models returned
**Needs Changes**. The domain model remained coherent; the failure model had two
material taxonomy findings:

1. F02, F11, F23, and F24 were assigned to some conditions outside their
   declared meanings. In particular, successful replay and expected
   invalidation were being treated as failures, and human-input and
   non-evidence persistence failures lacked precise categories.
2. F16 overlapped candidate validation failures even though generation failure
   and deterministic validation failure require different recovery behavior.

### Corrections Made

* Restricted F02 to missing required assessment context during request
  submission or validation.
* Restricted F11 to `EvidenceRecord` persistence failure.
* Restricted F23 to interrupted operations or processes.
* Restricted F24 to impossible or contradictory internal state that violates a
  declared invariant.
* Added F26 for incomplete or malformed human review, investigation, or
  decision submissions. The rejected action creates no partial
  `HumanDecision`; the assessment remains at the appropriate human interaction
  stage and awaits corrected input.
* Added F27 for persistence failure affecting a non-evidence authoritative
  record when no more specific category applies. Evidence persistence remains
  F11 and required audit recording remains F22.
* Reclassified successful idempotent replay as a deterministic control outcome
  that returns or references the existing result, creates no duplicate, and
  receives no failure category.
* Reclassified expected invalidation from changed inputs, versions, freshness,
  policy, authoritative facts, or investigation scope as a deterministic
  control outcome. Prior records remain immutable, routing resumes at the
  earliest affected stage, and later outputs are append-only successors.
* Narrowed F16 to generation-operation failures that prevent any candidate from
  existing. Once a candidate exists, structural, reference, and deterministic
  grounding failures belong exclusively to F17, F18, and F19.
* Reviewed all fifteen stage tables and aligned request, persistence, report,
  human-interaction, completion, and audit rows with the corrected taxonomy.
* Updated the ten idempotency cases so successful replay, retry after failure,
  uncertain-durability recovery, changed-input successors, and rejected
  conflicts remain distinguishable.
* Updated the failure-model plan to use the final count of twenty-seven
  categories and to verify the replay, invalidation, and report-validation
  boundaries.

### Verification Performed After Taxonomy Corrections

* Reviewed the complete diff and ran `git diff --check`.
* Validated every local Markdown link in the repository.
* Manually checked every use of F02, F11, F23, and F24 against its taxonomy
  definition.
* Confirmed successful replay and normal invalidation use no failure category.
* Confirmed F24 appears only for declared internal invariant violations.
* Confirmed F16 applies only before candidate output exists and F17, F18, and
  F19 exclusively own candidate validation failures.
* Confirmed incomplete human submissions are nonterminal for an otherwise
  valid assessment.
* Confirmed evidence and non-evidence persistence failures remain distinct.
* Confirmed all twenty-seven category definitions and all fifteen stage tables
  are present.
* Confirmed all seven domain entities remain unchanged and sufficient.
* Confirmed both Python package files remain empty.
* Confirmed no application, database, API, dependency, Docker, CI, queue,
  collector, model integration, monitoring, or infrastructure artifact was
  added.
* Confirmed nothing was staged, committed, or pushed.

### Remaining Questions

Retry budgets, delays, backoff, jitter, timeouts, source-specific recovery
thresholds, authorization matrices, freshness rules, audit retention and
access controls, persistence mechanisms, and repeated-failure termination
criteria remain intentionally deferred.

No implementation was added during these corrections.

### Exact Next Task After Taxonomy Corrections

Perform a read-only combined review of `docs/domain_model.md`,
`docs/failure_model.md`, both Day 2 plans, `journal/day_02.md`, and `README.md`
using `templates/REVIEW_TEMPLATE.md`. If the complete Day 2 baseline passes,
it is ready for the user to approve a commit; do not begin application
implementation as part of that review.

## Final Combined Review and Status Corrections

The final combined review confirmed that the behavioral design and failure
taxonomy passed. Its only findings were two stale status references in
`README.md` and `docs/proposed_workflow.md`.

The README now records both Day 2 design documents as complete, behaviorally
reviewed, and uncommitted. The proposed workflow now links to the completed
failure model instead of describing it as future work.

No behavioral design changed. No application code or infrastructure was added,
and nothing was staged, committed, or pushed during this correction.

The exact next action is final verification followed by committing the Day 2
design baseline.
