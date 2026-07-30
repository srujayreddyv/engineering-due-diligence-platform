# Failure Model

## Status and Scope

This document defines failure behavior for the planned Engineering Due
Diligence Platform. It is a logical behavior contract for later implementation,
not a description of working runtime behavior.

The model covers the scoped workflow for assessing one public GitHub repository
for one specified engineering use case. It does not define exception classes,
API responses, database records, queues, retry libraries, monitoring
configuration, infrastructure, or operational thresholds.

The seven entities in [domain_model.md](domain_model.md) remain sufficient.
There is no separate failure entity. Complete failure outcomes are represented
by an existing domain record only where that entity permits the outcome.
Otherwise, deterministic workflow state and `AuditEvent` preserve the failure
and recovery activity without substituting for a missing authoritative record.

## Goals

For every workflow stage, the failure model defines:

1. what can fail and how deterministic software detects it;
2. retryability and whether human or engineering action is required;
3. whether the workflow stops, retries, continues with explicit uncertainty,
   rejects an operation, or terminates the current assessment;
4. whether a complete authoritative domain record is created;
5. required audit, correlation, and idempotency behavior;
6. the earliest safe recovery stage and reusable completed records; and
7. what a human reviewer must be able to see.

The model prioritizes correctness, reproducibility, provenance, and safe human
decision support over silent progress.

## Failure Ownership and Detection

Deterministic workflow orchestration owns failure detection, classification,
retryability, stage disposition, idempotency, and workflow state. Collectors,
calculators, policy evaluators, report validators, authorization rules, and
persistence components provide deterministic signals to orchestration.

Humans may correct input, provide an authorized decision, request
investigation, or approve a policy-permitted continuation with uncertainty.
Humans do not rewrite failure history or set workflow state directly.

The AI model may explain a sanitized, deterministically classified failure or
its consequence. It must not classify a failure, decide retryability, select a
recovery stage, invent missing evidence, or replace a deterministic status with
narrative.

One incident may have one primary failure category and related categories. The
primary category controls disposition; related categories add diagnostic
context but do not weaken fail-closed rules.

## Core Failure Invariants

1. A failed or interrupted operation creates no partially valid authoritative
   record.
2. A terminal evidence attempt may create a complete `EvidenceRecord` with
   `available`, `partial`, `unavailable`, `failed_retryable`, or
   `failed_nonretryable`.
3. Missing, partial, failed, or stale evidence is never converted to a favorable
   fact, zero-risk value, policy pass, or invented content.
4. Continuing with uncertainty is allowed only when deterministic policy
   explicitly permits it and the uncertainty remains visible.
5. A failed metric calculation cannot create a successful `MetricResult`.
6. A failed policy-engine execution cannot create a successful or failed
   `PolicyFinding`; a complete policy finding exists only for a deterministically
   evaluated requirement outcome.
7. An invalid or ungrounded `GeneratedReport` remains `unusable`.
8. A report reaches human review only when structural, reference, and
   deterministic grounding validation all equal `passed`.
9. A failed final-decision operation creates neither a partial `HumanDecision`
   nor a partially completed `AssessmentRequest`.
10. Final decision creation, assessment completion, and required audit
    recording are one indivisible logical operation.
11. `AuditEvent` records activity but never replaces the authoritative domain
    record whose content the activity concerns.
12. Retries and recoveries are deterministic, idempotent, and auditable.
13. Changed inputs, versions, freshness evaluations, or assessment context
    create append-only successor records rather than mutating or silently
    reusing incompatible history.
14. Internal invariant violations and unknown failures fail closed until safely
    classified and resolved.

## Retryability Vocabulary

| Classification | Meaning |
| --- | --- |
| `retryable` | The same logical operation may be attempted again without changing authoritative inputs after a transient condition clears |
| `nonretryable` | Repeating the same operation with the same inputs cannot produce a valid result |
| `conditionally_retryable` | Retry is allowed only after a named condition changes, such as corrected input, restored source, applicable version, or repaired deterministic logic |
| `human_resolvable` | A human may supply or correct authorized information, choose an allowed action, or initiate a new assessment; automation cannot resolve it alone |
| `terminal_for_current_assessment` | The current assessment identity cannot progress; correction requires a new assessment or separately governed action |

Retryability is not permission for unbounded repetition. Retry counts, delays,
backoff, jitter, rate-limit windows, circuit thresholds, timeouts, escalation
timing, and service-level targets are deferred configuration.

## Failure Taxonomy

The final taxonomy contains twenty-seven categories. Failure categories are
classifications for auditable behavior, not additional domain entities.

| ID | Failure category | Detection | Normal retryability | Human resolvable | Terminal for current assessment | Normal disposition |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | Invalid request or unsupported target | Deterministic request and supported-target validation fails | Nonretryable for the same submitted request | Yes, through a corrected new request | Yes for that request identity | Record `validation_failed`; stop |
| F02 | Missing required assessment context | Required-field validation identifies an absent or invalid context value | Nonretryable for the same submitted request | Yes, through a corrected new request | Yes for that request identity | Record explicit validation errors; stop |
| F03 | Authentication or authorization failure | Deterministic identity, credential, permission, or role check fails | Conditionally retryable after valid authority is established | Usually | Conditional; never bypass authorization | Stop without revealing protected details |
| F04 | External rate limiting | Authoritative source returns an explicit rate-limit signal or equivalent deterministic response | Retryable after the source-defined or configured eligibility condition | No | No | Bounded automatic retry or blocked collection |
| F05 | Network timeout or transient connectivity failure | Deterministic timeout, connection, or transient transport classification | Retryable | No | No | Bounded automatic retry; otherwise record terminal attempt failure |
| F06 | Authoritative source unavailable | Source or required resource is deterministically unavailable | Conditionally retryable after source recovery | Sometimes | No unless policy requires the fact and no resolution exists | Record unavailable or failed evidence; stop or continue only by policy |
| F07 | Malformed or unexpected external response | Collector schema, type, integrity, or semantic validation fails | Conditionally retryable through fresh retrieval or corrected collector support | Engineering may resolve | No by itself | Record failed attempt; do not normalize invented content |
| F08 | Partial evidence collection | Completeness rules identify captured content and named omissions | Conditionally retryable through recollection | Sometimes | No by itself | Store complete `partial` outcome; continue only when consumers support it |
| F09 | Missing evidence | Expected evidence is explicitly absent or cannot be obtained | Conditionally retryable when the source or request changes | Sometimes | Conditional on deterministic policy | Store `unavailable`; derive unavailable or conservative outcomes |
| F10 | Stale evidence | Versioned freshness evaluation at collection or use yields `stale` | Conditionally retryable through recollection or an applicable approved rule | Sometimes | Conditional on deterministic policy | Recollect or continue with explicit stale status only when policy permits |
| F11 | Evidence persistence failure | Durable-write, integrity, or read-after-write verification fails | Retryable when the persistence condition is transient; otherwise conditional | Engineering may resolve | No, but dependent stages remain blocked | Fail closed; no authoritative `EvidenceRecord` until durable |
| F12 | Metric calculation failure | Calculator execution, invariant, determinism, or output validation fails | Conditionally retryable after deterministic cause resolution | Engineering may resolve | No by itself | Store a complete `failed` result only when permitted; block required dependents |
| F13 | Unsupported metric input | Versioned calculator rejects the evidence kind, shape, status, or combination | Nonretryable for identical inputs and version | Sometimes through new evidence or definition | Conditional if metric is required | Store `unavailable` with reason; never guess a value |
| F14 | Policy evaluation failure | Policy-engine execution or complete-finding validation fails | Conditionally retryable after engine or input correction | Engineering may resolve | No by itself | Stop; create no partial or fabricated finding |
| F15 | Missing or incompatible policy version | Required approved policy or requirement version cannot be resolved or applied | Nonretryable until an applicable approved version exists | Policy owner resolves | Conditional; required evaluation cannot proceed | Fail closed before evaluation |
| F16 | AI report generation failure before a candidate exists | Provider, transport, timeout, empty or truncated response, provider refusal, unavailable model, or another failure prevents obtaining any candidate output | Conditionally retryable under unchanged inputs when safe | No | No | Preserve a complete unusable generation outcome when possible; otherwise audit the attempt |
| F17 | Structured output validation failure | Deterministic schema validation is `failed` or `not_run` for a candidate | Nonretryable for the exact candidate; regeneration is conditional | No | No | Mark report `unusable`; do not enter human review |
| F18 | Reference validation failure | A claim reference is missing, unresolved, wrong type, wrong assessment, or outside the fixed input set | Nonretryable for the exact candidate; regeneration is conditional | No | No | Mark report `unusable`; do not enter human review |
| F19 | Deterministic grounding validation failure | Mechanical comparison finds unsupported facts, metrics, policy outcomes, or uncertainty handling | Nonretryable for the exact candidate; regeneration is conditional | No | No | Mark report `unusable`; do not enter human review |
| F20 | Human authorization failure | Identity, role, participation, or authorization-rule validation fails | Nonretryable for the same unauthorized action; conditional with an authorized actor | Yes | No unless no authorized path exists | Reject the submission; leave assessment awaiting review |
| F21 | Conflicting final decision submission | `decision_submission_id`, assessment state, and canonical content comparison prove that a submission conflicts with an existing decision or completed assessment | Nonretryable for the current assessment | A new assessment or governed correction may resolve the need | The existing completed assessment remains terminal | Reject the conflict without changing authoritative history |
| F22 | Audit recording failure | Required event durability, integrity, or completeness verification fails | Retryable or conditionally retryable | Engineering may resolve | No, but the owning operation cannot be acknowledged complete | Fail closed and retry audit-aware operation idempotently |
| F23 | Interrupted workflow | Orchestration records cancellation, process loss, shutdown, lease loss, or other interruption before completion | Retryable or conditionally retryable based on cause | Sometimes | No by itself | Preserve completed records; resume earliest incomplete stage |
| F24 | Internal invariant violation | Deterministic consistency check detects impossible state, cross-assessment link, history conflict, or authority breach | Nonretryable until engineering establishes safe recovery | Engineering resolves | Conditional; fail the assessment if integrity cannot be proven | Stop and escalate; never repair by silent mutation |
| F25 | Unknown failure | No approved deterministic category explains the observed failure | Nonretryable until classified; then follows the approved category | Engineering resolves | Conditional | Fail closed, sanitize, preserve diagnostic correlation, investigate |
| F26 | Incomplete or malformed human submission | Deterministic validation finds missing, malformed, or incompatible required content in a human review, investigation, or decision submission after the assessment request is valid | Nonretryable for identical content; corrected content may be submitted | Yes | No | Reject only the submitted action, preserve the assessment stage, and await corrected human input |
| F27 | Non-evidence authoritative record persistence failure | Durable-write or integrity verification fails for `AssessmentRequest`, `MetricResult`, `PolicyFinding`, `GeneratedReport`, or `HumanDecision`; it applies to required `AuditEvent` content only when F22 is not the more specific category | Retryable when transient; otherwise conditionally retryable after persistence or integrity recovery | Engineering may resolve | No by itself, but the affected stage fails closed | Create no partial authoritative record and do not acknowledge the affected operation |

F16 ends before a candidate output exists. Once any candidate output exists,
candidate validation failures belong exclusively to F17, F18, or F19. F17,
F18, and F19 make that candidate unusable; a later regeneration is a new,
auditable candidate attempt. The model does not classify its own generation or
validation failure.

## Failure Disposition Rules

| Workflow response | Allowed only when |
| --- | --- |
| Automatic retry | The failure is `retryable`, authoritative inputs are unchanged, the logical attempt is identifiable, no fail-closed precondition is bypassed, and configured eligibility permits another attempt |
| Stop and await human correction | Required request context, authorization, policy governance, or a human-owned choice cannot be resolved deterministically |
| Continue with explicit missing or partial evidence | A complete evidence outcome exists, downstream behavior represents insufficiency explicitly, and deterministic policy permits human review with that uncertainty |
| Resume from the earliest affected stage | Completed records pass all reuse checks and deterministic orchestration identifies the first stage invalidated by the failure or investigation request |
| Mark the current attempt unusable | A complete attempted output is preservable but cannot serve as an authoritative successful input, including an invalid generated report |
| Fail the current assessment terminally | Request validation fails for the immutable submitted request, integrity cannot be reestablished, or another explicit domain terminal rule applies |
| Reject a conflicting operation | An idempotency or finality check proves that accepting the operation would duplicate or contradict authoritative history |
| Escalate an invariant violation for engineering investigation | State, history, authority, or integrity contradicts the domain invariants, or an unknown failure cannot be classified safely |

Automatic retry never converts a terminal outcome into success without a new
attempt. Human correction never edits an immutable authoritative record.
Continuation never hides uncertainty. A stopped stage remains blocked until its
documented recovery precondition is satisfied.

## Control Outcomes That Are Not Failures

Successful replay and normal invalidation are deterministic control outcomes,
not failure categories:

* **Successful idempotent replay** returns or references the existing
  authoritative result, creates no duplicate record, and does not change the
  workflow stage unless uncertain durability must first be reconciled. Replay
  detection may create an `AuditEvent` when useful and is required only when
  the critical operation's audit rules require it. If the existing result
  records a prior failure, that historical result keeps its failure category;
  the successful replay operation receives no new failure category.
* **Normal invalidation** occurs when changed inputs, versions, freshness,
  policy, authoritative facts, or investigation scope make a prior record
  ineligible for the current continuation. The prior record remains immutable,
  orchestration routes to the earliest affected stage, successor records
  preserve new output, and an `AuditEvent` records the invalidation and route.

| Auditable outcome | Failure category behavior |
| --- | --- |
| Actual failure | Uses exactly one primary F-category and optional compatible related categories |
| Successful replay | Uses no failure category |
| Normal invalidation | Uses no failure category |
| Rejected conflicting final operation | Uses F21 |
| Interrupted attempt | Uses F23 |
| Genuine invariant violation | Uses F24 |
| Correctable incomplete human input | Uses F26 for the rejected submission; corrected resubmission is a new control attempt |
| Evidence persistence failure | Uses F11 |
| Other authoritative-record persistence failure | Uses F27 unless F22 specifically governs required audit recording |
| Report candidate validation failure | Uses F17, F18, or F19 according to the failed layer, never F16 |

## Minimum Failure Information

Failure information is preserved through deterministic workflow state and
`AuditEvent`; it is not a new entity. When a failure occurs before a downstream
record exists, the audit activity references the `AssessmentRequest` and the
operation attempt identifier.

| Information | Requirement |
| --- | --- |
| Failure category | One approved primary category, plus optional related categories |
| Failure code | Stable, versioned deterministic code within the category |
| Affected stage | Exact workflow stage at detection |
| Detection timestamp | Unambiguous time the failure was detected |
| Attempt identifier | Collection, persistence, calculation, evaluation, generation, validation, decision, or audit attempt correlation |
| Assessment identifier | Owning `AssessmentRequest` |
| Related record identifiers | Existing authoritative inputs or outcome records; never fabricated identifiers |
| Retryability classification | Retryable, nonretryable, conditionally retryable, or human resolvable |
| Stop or continue disposition | Deterministic workflow response and authority for it |
| Safe human-facing explanation | Sanitized statement of impact and uncertainty |
| Internal diagnostic reference | Opaque reference to protected diagnostic context, not the sensitive payload itself |
| Recovery action | Allowed next operation and prerequisite |
| Recovery outcome | Succeeded, failed, interrupted, rejected, or still blocked |
| Predecessor attempt | Prior attempt identifier when retrying or recovering |

Failure details must not require access tokens, credentials, secrets, raw
authorization headers, or unnecessary sensitive external payloads.

## Stage-Specific Failure Behavior

The tables below use the taxonomy identifiers above. “Audit” means a complete
`AuditEvent` when audit persistence is available. If audit recording itself
fails, F22 applies and the owning operation is not acknowledged as complete.

### 1. Submit Adoption Request

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Submitter lacks authority to create an assessment | F03 | Conditionally retryable with authorized identity | Stop | No submitted `AssessmentRequest` is created | Record actor, rule version, sanitized denial, and attempt | Replay by the same unauthorized actor remains rejected | Submit adoption request | State that submission was not accepted and name the safe next action |
| Submission is interrupted before the complete request is durable | F23 | Retryable | Stop without acknowledging submission | No partial `AssessmentRequest` exists | Record attempt, interruption, and whether a request identity was reserved | Same logical submission resolves to an existing complete request or creates one, never both | Submit adoption request | Show that no request was accepted yet |
| A logically identical request submission is replayed | Not a failure; successful replay control | Not applicable | Return the existing request without changing stage | Return or reference the existing `AssessmentRequest`; do not duplicate it | Replay detection may be audited; it is required only when submission audit rules require it | Canonical identical content and logical submission identity must match | Existing stage, normally validate request | Show the existing assessment reference |
| `AssessmentRequest` persistence or integrity verification fails | F27 | Retryable or conditionally retryable | Fail closed | No authoritative submitted request is acknowledged | Record safe diagnostic correlation; F22 applies if required audit recording also fails | Retry the same logical submission without duplicating a durable request | Submit adoption request | Show submission blocked and whether human retry is safe |

### 2. Validate Request

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Repository target is invalid, unsupported, or not a supported public GitHub target | F01 | Nonretryable for this request | Terminally stop this assessment identity | Existing request transitions to `validation_failed`; no downstream record | Record validation version, errors, target category, and transition | Revalidation with identical inputs and rules returns the same result | Submit a corrected new request | Show exact safe validation errors without protected details |
| Required assessment context is missing or invalid | F02 | Nonretryable for this request | Terminally stop this assessment identity | Request records `validation_failed`; submitted context is not mutated | Record missing field codes and validation-rule version | Identical replay cannot change the result | Submit a corrected new request | Show required corrections |
| Validation logic encounters an impossible state | F24 | Nonretryable until investigated | Stop and escalate | Do not mark the request valid or create downstream records | Record invariant code, versions, and diagnostic reference | Replays remain blocked until safe deterministic resolution | Validate request after repair, or create a new assessment if integrity is uncertain | Show workflow blocked and engineering action required |

### 3. Collect Authoritative Evidence

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Collector authentication or source authorization fails | F03 | Conditionally retryable after authority correction | Stop that evidence attempt | Create a complete failed evidence outcome only when failure fields and safe provenance are durable | Record collector version, source identity, sanitized category, and attempt | New authorized retry uses a new attempt; never overwrites failure history | Collect authoritative evidence | Show source failed without exposing protected resource details |
| Source rate limits collection | F04 | Retryable when eligible | Automatically retry when configured; otherwise stop collection | Each terminal attempt may create `failed_retryable`; no source fact is invented | Record source signal, retry eligibility reference, and attempt chain | Each attempt is distinct; repeated delivery of one attempt is deduplicated | Collect authoritative evidence | Show rate-limited source and current blocked state |
| Network timeout or transient connectivity fails | F05 | Retryable | Automatically retry when configured; otherwise store failure | A terminal failed attempt may create `failed_retryable` | Record transport category, attempt, collector version, and predecessor | Same attempt cannot create multiple evidence records | Collect authoritative evidence | Show temporary collection failure and retry history |
| Authoritative source is unavailable | F06 | Conditionally retryable after source recovery | Stop, recollect later, or continue only under deterministic policy | Store complete `unavailable` or failed `EvidenceRecord` with reason | Record source, outcome, freshness basis, retryability, and provenance available | Recollection creates a successor record and preserves the unavailable outcome | Collect authoritative evidence, or calculate metrics if policy permits uncertainty | Show unavailable source, consequence, and next action |
| Required evidence is explicitly missing from an available source | F09 | Conditionally retryable when the source or request changes | Stop, recollect later, or continue only under deterministic policy | Store complete `unavailable` `EvidenceRecord` with absence reason | Record source, absence, freshness basis, retryability, and provenance | Recollection creates a successor record and preserves the absence | Collect authoritative evidence, or calculate metrics if policy permits uncertainty | Show missing evidence, consequence, and next action |
| External response is malformed or unexpected | F07 | Conditionally retryable | Stop; never normalize guessed content | Store complete failed evidence outcome, not `available` evidence | Record schema/collector version, safe error code, and integrity reference | Fresh retrieval is a new attempt; collector changes require a version change | Collect authoritative evidence | Show unusable source response and whether engineering support is needed |
| Response contains only partial evidence | F08 | Conditionally retryable | Recollect, or continue only when deterministic consumers and policy permit | Store complete `partial` `EvidenceRecord` with omissions and snapshot | Record captured components, omissions, source, and attempt | Recollection creates an append-only successor | Collect evidence or calculate metrics when allowed | Show partial status and named omissions |
| Collected evidence is stale at collection | F10 | Conditionally retryable | Recollect, or continue only under an applicable deterministic rule and policy | Store the evidence with explicit stale status and rule version | Record timestamps, freshness basis, rule version, and disposition | Recollection creates a successor; stale record remains immutable | Collect evidence or calculate metrics when allowed | Show staleness, rule, and effect on confidence |
| Collection is interrupted before a terminal outcome | F23 | Retryable or conditional | Stop without a partial record | No `EvidenceRecord` exists for the incomplete attempt | Record assessment, source, attempt, interruption, and completed prior records | Resume or retry by attempt identity without duplicating a terminal record | Collect authoritative evidence | Show interrupted source and prior attempts |

### 4. Persist Raw Evidence

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Evidence payload or outcome cannot be made durable | F11 | Retryable or conditional | Fail closed; block all dependent stages | No authoritative `EvidenceRecord` exists until payload, outcome, provenance, digest, and required fields are durable | Record persistence attempt and safe diagnostic reference against assessment and collection attempt | Retrying the same complete outcome must resolve to one evidence record | Persist raw evidence | Show evidence persistence blocked, not evidence unavailable |
| Evidence persistence integrity verification does not match the intended snapshot | F11 | Conditionally retryable after safe diagnosis | Stop and escalate if integrity cannot be proven | Do not acknowledge or use the record | Record expected verification class, observed failure, versions, and attempt | A corrected write remains the same logical persistence attempt only when content is identical | Persist raw evidence after repair, otherwise recollect | Show integrity block and required engineering action |
| Persistence is interrupted with uncertain outcome | F23 | Retryable | Resolve durability before retrying or continuing | Exactly one complete record may exist; never create a second until outcome is resolved | Record attempt and recovery check when audit is available | Lookup by logical attempt identity and digest returns existing record or safely retries | Persist raw evidence | Show blocked state until durability is known |

### 5. Calculate Deterministic Metrics

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Required evidence is missing, partial, failed, or stale beyond the applicable rule | F08, F09, F10, or F13 | Conditionally retryable with compatible evidence | Produce explicit unavailable result; stop required dependents or continue only when policy permits | A complete `MetricResult` may be `unavailable`; it cannot contain a placeholder value | Record exact evidence IDs, statuses, freshness evaluations, calculator version, and reason | Identical inputs and version resolve to equivalent content or a verified existing result | Collect evidence or calculate metrics after compatible input exists | Show unavailable metric and causing evidence |
| Calculator execution or output validation fails | F12 | Conditionally retryable after cause resolution | Stop required metric path | A complete `failed` `MetricResult` may be stored; never `available` | Record attempt, input IDs/digest, definition version, failure code, and diagnostic reference | Retry with identical definition and inputs cannot silently produce conflicting content | Calculate metrics after deterministic resolution | Show failed metric and blocked dependents |
| Calculator does not support the supplied input shape or status | F13 | Nonretryable for identical inputs and version | Stop or carry explicit unavailability according to policy | Store `unavailable` with reason when complete | Record input IDs, unsupported reason, and versions | Changed evidence or definition creates a successor result | Collect evidence or calculate with an applicable version | Show unsupported input and required change |
| Complete `MetricResult` cannot be made durable | F27 | Retryable or conditionally retryable | Fail closed; do not evaluate dependent policy | No authoritative metric result exists until complete and durable | Record calculation and persistence attempt, intended result status, input digest, and safe diagnostic reference | Resolve uncertain durability before creating or retrying one logical result | Calculate deterministic metrics after persistence recovery | Show metric persistence blocked, not metric unavailability |
| Calculation is interrupted before a complete outcome | F23 | Retryable | Stop without a partial metric | No `MetricResult` exists for the interrupted attempt | Record calculation attempt, inputs, version, and interruption | Same attempt resolves to one terminal result; recalculation is a new attempt | Calculate deterministic metrics | Show interrupted metric calculation |
| Repeated identical calculation yields nonequivalent content | F24 | Nonretryable until investigated | Fail closed and escalate | Preserve prior records; do not select the conflicting output | Record both digests, versions, attempts, and invariant code | Do not retry as ordinary calculation until integrity is restored | Engineering investigation, then metric calculation | Show determinism violation and blocked workflow |

### 6. Evaluate Context-Specific Policy

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Required approved policy or requirement version is missing or incompatible | F15 | Nonretryable until an applicable approved version exists | Fail closed | No `PolicyFinding` is created | Record requested policy identity/version, engine version, and governance action needed | Replay remains blocked under the same unavailable version | Evaluate policy after approved version resolution | Show policy-version block and responsible human role |
| Policy engine execution or finding-set validation fails | F14 | Conditionally retryable after deterministic repair | Stop; do not generate a report | No partial or fabricated `PolicyFinding` is created | Record evaluation ID, inputs, versions, failure code, and diagnostic reference | Exact retry cannot create duplicate or contradictory findings | Evaluate policy after resolution | Show evaluation failure and affected requirements |
| Required facts are explicitly unavailable or insufficient | F08, F09, F10, or F13 | Conditionally retryable through upstream recovery | Continue only through a defined conservative policy outcome | Complete findings may be `not_evaluable` or `investigation_required`; never pass by omission | Record exact evidence/metric IDs, freshness evaluations, policy and requirement versions | Identical inputs and versions produce equivalent findings or reuse verified findings | Collect evidence, calculate metrics, or generate report if policy permits review | Show unresolved requirement, uncertainty, and required action |
| Complete `PolicyFinding` set cannot be made durable | F27 | Retryable or conditionally retryable | Fail closed; do not generate a report | No partial or authoritative finding set exists | Record evaluation and persistence attempt, intended outcomes, input digest, and safe diagnostic reference | Resolve uncertain durability before producing or retrying one logical finding set | Evaluate policy after persistence recovery | Show policy persistence blocked, not a policy outcome |
| Evaluation is interrupted before a complete finding set | F23 | Retryable | Stop without partial findings | No incomplete `PolicyFinding` is authoritative | Record evaluation ID, inputs, versions, completed prior records, and interruption | Resumption produces one complete finding set | Evaluate context-specific policy | Show interrupted policy evaluation |

### 7. Generate the AI-Assisted Decision Brief

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Provider, transport, timeout, empty or truncated response, refusal, unavailable model, or equivalent operation failure prevents obtaining any candidate | F16 | Conditionally retryable when safe | Retry generation when eligible or stop | A complete `unusable` `GeneratedReport` may be stored with failure details; otherwise no report record | Record fixed inputs, prompt/model/configuration versions, attempt, provider outcome, and safe correlation | Same generation delivery creates at most one outcome record; a later generation is a successor attempt | Generate decision brief | Show pre-candidate generation failure and retry state without raw provider payload |
| Expected changed or ineligible inputs invalidate the planned fixed input set before generation | Not a failure; normal invalidation control | Not applicable | Route to the earliest affected stage | Preserve prior records; no candidate is generated from ineligible inputs | Record changed inputs, invalidation reason, reused records, and deterministic route | Replaying the same invalidation does not duplicate transitions | Earliest affected evidence, metric, policy, or report stage | Show which input changed and the next stage |
| Input assembly contains cross-assessment, wrong-type, or otherwise impossible records | F24 | Nonretryable until engineering establishes safe recovery | Fail closed and escalate | No candidate report is accepted; no valid report exists | Record offending identifiers, expected types, assembly version, and invariant code | Retry remains blocked until integrity is restored | Engineering investigation, then earliest safe stage | Show report generation blocked by an integrity violation |
| Generation is interrupted before a terminal report outcome | F23 | Retryable or conditional | Stop without a partial authoritative report | No `GeneratedReport` exists unless a complete unusable outcome is durable | Record generation attempt, fixed inputs, versions, and interruption | Resume or regenerate without duplicating a terminal attempt | Generate decision brief | Show interrupted generation and preserved prior reports |

### 8. Perform Structural Validation

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Candidate does not conform to the approved report schema | F17 | Nonretryable for this candidate | Mark unusable; do not proceed to reference validation as a valid candidate or human review | Complete report records `structural_validation_status=failed` and `validation_status=unusable` | Record schema/report versions, deterministic errors, and attempt | Revalidating identical candidate and versions returns the same result | Generate decision brief | Show unusable report and structural failure summary |
| Structural validation completes as `not_run` for the candidate | F17 | Nonretryable for this completed candidate outcome | Mark unusable; do not advance | Complete report records `not_run` and `unusable` | Record reason, attempt, schema/report versions, and candidate digest | Identical validation replay returns the existing outcome without a failure category for the replay itself | Generate decision brief | Show structural validation did not run and review is blocked |
| Structural validation operation is interrupted before a complete outcome | F23 | Retryable when safely resumable | Stop without a partial validation outcome | No valid report exists; incomplete activity does not create a partial authoritative report | Record validation attempt, candidate digest, versions, and interruption | Resume the interrupted operation or reconcile an existing complete outcome | Perform structural validation | Show validation interrupted and review blocked |
| Validator produces an impossible or inconsistent result | F24 | Nonretryable until investigated | Fail closed and escalate | Do not mark report valid | Record invariant code, validator version, candidate digest, and diagnostic reference | No ordinary retry until integrity is restored | Engineering investigation, then structural validation | Show validation system failure |

### 9. Perform Reference Validation

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A material claim lacks its required typed reference | F18 | Nonretryable for this candidate | Mark unusable; do not continue to human review | Report records reference failure and `unusable` | Record claim path, expected entity type, report version, and attempt | Identical candidate and inputs reproduce the failure | Generate decision brief | Show missing typed reference without presenting the claim as supported |
| Reference is unresolved, wrong type, wrong assessment, or outside the fixed input set | F18 | Nonretryable for this candidate | Mark unusable and stop validation success path | Report remains an immutable unusable attempt | Record offending identifier, expected type, fixed-input digest, and reason | Revalidation cannot make an unchanged invalid reference valid | Earliest affected input stage if inputs are wrong; otherwise report generation | Show unusable report and reference category |
| Reference validation completes as `not_run` for the candidate | F18 | Nonretryable for this completed candidate outcome | Mark unusable; do not advance | Complete report records `not_run` and `unusable` | Record reason, candidate digest, fixed-input digest, and validator version | Identical replay returns the existing outcome without classifying the replay as failure | Generate decision brief | Show reference validation did not run and review is blocked |
| Reference validation operation is interrupted | F23 | Retryable when safely resumable | Stop without a partial validation outcome | No valid report exists | Record validation attempt, candidate, inputs, versions, and interruption | Resume or reconcile one complete outcome | Perform reference validation | Show validation interrupted and review blocked |
| Reference validator produces an impossible or contradictory result | F24 | Nonretryable until investigated | Fail closed and escalate | Do not mark report valid | Record invariant code, candidate digest, fixed inputs, and validator version | No ordinary retry until integrity is restored | Engineering investigation, then reference validation | Show validation integrity failure |

### 10. Perform Deterministic Grounding Validation

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Direct fact does not match its `EvidenceRecord` | F19 | Nonretryable for this candidate | Mark unusable; do not enter human review | Report records grounding failure and `unusable` | Record claim path, evidence ID, rule version, and safe mismatch code | Same candidate and inputs reproduce the failure | Generate decision brief | Show unsupported direct factual claim |
| Calculated claim does not match the exact `MetricResult` | F19 | Nonretryable for this candidate | Mark unusable | Report remains an immutable unusable attempt | Record claim path, metric-result ID, expected value/unit check, and validator version | Revalidation cannot alter an unchanged claim | Generate decision brief | Show unsupported calculated claim |
| Policy conclusion does not match the exact `PolicyFinding` | F19 | Nonretryable for this candidate | Mark unusable | No valid report exists | Record claim path, finding ID, expected outcome check, and validator version | Same inputs and rules produce the same result | Generate decision brief | Show unsupported policy conclusion |
| Required uncertainty marker is absent or contradicts missing, partial, failed, or stale evidence | F19 | Nonretryable for this candidate | Mark unusable; never lower confidence as a substitute | Report records grounding failure | Record affected evidence/metric/finding IDs and required marker rule | Regeneration creates a successor attempt | Generate decision brief | Show omitted uncertainty and source limitation |
| Grounding validation completes as `not_run` for the candidate | F19 | Nonretryable for this completed candidate outcome | Mark unusable; do not enter human review | Complete report records `not_run` and `unusable` | Record reason, candidate digest, fixed inputs, and validator version | Identical replay returns the existing outcome without classifying replay as failure | Generate decision brief | Show grounding validation did not run and review is blocked |
| Grounding validation operation is interrupted | F23 | Retryable when safely resumable | Stop without a partial validation outcome | No valid report exists | Record attempt, candidate digest, fixed inputs, versions, and interruption | Resume or reconcile one complete outcome | Perform grounding validation | Show validation interrupted and review blocked |
| Grounding validator produces an impossible or contradictory result | F24 | Nonretryable until investigated | Fail closed and escalate | Do not mark report valid | Record invariant code, candidate digest, fixed inputs, and validator version | No ordinary retry until integrity is restored | Engineering investigation, then grounding validation | Show validation integrity failure |
| Complete `GeneratedReport` outcome cannot be made durable | F27 | Retryable or conditionally retryable | Fail closed; do not enter human review | No authoritative valid or unusable report exists until complete and durable | Record report persistence attempt, candidate/input digests, validation statuses, and safe diagnostic reference | Resolve uncertain durability before persisting or retrying one logical report outcome | Deterministic report validation after persistence recovery | Show report persistence blocked |

### 11. Conduct Human Review

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Reviewer is not authorized or required participation is absent | F20 | Conditionally retryable with authorized participation | Stop; retain `awaiting_human_review` | No `HumanDecision` is created | Record actor, role, authorization-rule version, sanitized denial, and required roles | Repeated unauthorized action remains rejected | Conduct human review with authorized participants | Show missing authority or participation without protected details |
| A human review submission is incomplete or malformed but is not yet an investigation request or final decision | F26 | Nonretryable for identical content; human resolvable with corrected input | Reject only the submission; retain `awaiting_human_review` | No partial `HumanDecision` or workflow transition exists | Record validation codes, actor, report, and submission attempt | Identical malformed content remains rejected; corrected content is a new submission attempt | Conduct human review with complete input | Show the fields or corrections required |
| Evidence becomes stale under the applicable at-use freshness rule during review | F10 | Conditionally retryable through recollection or permitted policy handling | Stop current review and route deterministically | Existing report remains immutable but is not current decision input | Record evidence ID, freshness status, rule version, invalidation, and route | Repeating the same detection does not duplicate rerouting | Evidence collection or policy evaluation as determined by the rule | Show stale evidence, effect, and next stage |
| Changed evidence, metrics, policy, authoritative facts, versions, or investigation scope make the report ineligible | Not a failure; normal invalidation control | Not applicable | Stop current review and route deterministically | Preserve the report; mark it ineligible only for current continuation and create successors downstream | Record invalidation reason, affected and reused records, and deterministic route | Replaying the same invalidation does not duplicate transitions | Earliest affected evidence, metric, policy, or report stage | Show why the report is no longer eligible and what remains reusable |
| Human semantic review identifies an unsupported explanation or material concern | Not a failure; human semantic review outcome | Human resolvable | Request investigation or regeneration; do not mutate report | Valid report remains immutable but becomes ineligible for current decision | Record reviewer, concern, affected conclusion, and selected route | Repeating the same review action returns the existing nonfinal request | Request further investigation | Show cited concern, affected conclusion, and next step |
| Review is interrupted before a disposition is recorded | F23 | Retryable | Remain awaiting review | No partial `HumanDecision` exists | Record review attempt, authorized participants, and interruption without sensitive notes | Resumption references the same report and policy evaluation | Conduct human review | Show review incomplete |

### 12. Request Further Investigation

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Investigation request omits the question, concern, affected conclusion, or known evidence need | F26 | Nonretryable for identical content; human resolvable with corrected input | Reject incomplete submission; remain awaiting review | No partial `HumanDecision` is created | Record validation codes, actor, report, and attempt | Identical incomplete replay remains rejected; corrected content is a new submission attempt | Request further investigation with complete content | Show missing investigation fields |
| Identical investigation submission is replayed | Not a failure; successful replay control | Not applicable | Return existing nonfinal decision and route without changing stage | Do not duplicate `HumanDecision` or workflow transition | Replay detection may be audited; it is required only when investigation audit rules require it | `decision_submission_id` and canonical content must match | Existing routed stage | Show existing request and current progress |
| Routing inputs contradict declared workflow invariants and no valid earliest stage can exist | F24 | Nonretryable until engineering establishes safe recovery | Fail closed and escalate | Investigation decision remains authoritative; workflow does not guess a route | Record inputs, routing-rule version, contradiction, and invariant code | Retry only after integrity is restored | Engineering investigation, then routing determination | Show routing blocked by an integrity violation |
| Routing fails for a reason that has not yet been deterministically classified | F25 | Nonretryable until classified | Fail closed and investigate | Investigation decision remains authoritative; workflow does not guess a route | Record safe inputs, routing-rule version, and diagnostic reference | Retry only after an approved category and recovery are established | Routing determination after classification | Show routing blocked and engineering action required |
| Routing succeeds | Not a failure; deterministic recovery control | Not applicable | Repeat only the earliest affected stage and downstream stages | Earlier authoritative records remain; successors are append-only | Record selected stage, invalidated records, reused records, and reason | Replaying the same route does not duplicate stage transitions | Evidence collection, metric calculation, policy evaluation, or report generation | Show investigation scope, reused work, and next action |

### 13. Record the Human Decision

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Decision maker or required participants lack authorization | F20 | Conditionally retryable with authorized participants | Reject; keep assessment awaiting review | No `HumanDecision` is created | Record actor, role, rule version, required roles, and sanitized rejection | Same unauthorized submission remains rejected | Conduct human review with authorized participants | Show authorization failure and safe next role |
| Required rationale, conditions, investigation detail, report, or policy reference is missing or malformed | F26 | Nonretryable for identical content; human resolvable with corrected input | Reject incomplete submission; keep assessment awaiting review | No partial decision exists | Record validation codes, decision submission identity, and attempt | Identical incomplete replay remains rejected; corrected content is a new submission attempt | Record a complete human decision | Show missing or malformed decision requirements |
| Identical decision submission is replayed | Not a failure; successful replay control | Not applicable | Return or reference existing decision without changing stage | No duplicate authoritative decision | Replay detection is audited for this critical final-decision operation | Same assessment, submission ID, and canonical content must match | Existing workflow state | Show existing disposition |
| Conflicting final submission follows completion | F21 | Nonretryable for this assessment | Reject conflicting operation | No second final decision and no state change | Record conflict safely when audit is available; never expose protected rationale unnecessarily | Conflict cannot be converted into replay | New assessment or governed correction process | Show assessment already completed and allowed next action |
| Complete `HumanDecision` cannot be made durable | F27 | Retryable or conditionally retryable | Fail closed; keep assessment awaiting review | No partial or authoritative decision and no partial completion exist | Record decision and persistence attempt, submission identity, intended disposition, and safe diagnostic reference | Reconcile uncertain durability before retrying the same logical decision | Record the human decision after persistence recovery | Show decision not recorded |
| Required audit recording fails during final decision | F22 | Retryable or conditional | Fail closed; do not acknowledge completion | Final decision, completed state, and audit event are not partially exposed as complete | Preserve recovery correlation outside authoritative success until audit can be durably recorded | Retry the same logical submission as one indivisible operation | Record human decision after audit capability recovers | Show decision not recorded and assessment not completed |

### 14. Complete the Assessment

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Orchestration attempts completion despite an absent final decision, valid report, policy evaluation, or authorization precondition | F24 | Nonretryable until the invariant failure is investigated and safe state is established | Fail closed and escalate | Assessment does not transition to `completed` | Record missing precondition and invariant code | Repeated completion remains blocked; prerequisite work is recovered separately rather than treating the contradiction as normal invalidation | Engineering investigation, then the earliest missing prerequisite stage | Show completion blocked by an internal state contradiction |
| Completion is interrupted or outcome is uncertain | F23 | Retryable only through idempotent state resolution | Resolve existing state before another attempt | At most one final decision and one completed transition may become authoritative | Record recovery check and correlation when possible | Same decision submission resolves to completed existing operation or safely retries it | Record human decision/completion operation | Show completion pending, never completed optimistically |
| Completed `AssessmentRequest` state cannot be made durable | F27 | Retryable or conditionally retryable only as part of the indivisible final operation | Fail closed | Assessment does not appear completed and no partial final operation is acknowledged | Record completion persistence attempt and safe diagnostic reference; F22 applies separately to required audit failure | Reconcile the same logical final operation without duplicating the decision | Complete assessment after persistence recovery | Show assessment not completed |
| Required completion audit event cannot be recorded | F22 | Retryable or conditional | Fail closed | Assessment must not appear completed | The recovery event later records the original failure and final outcome | Retry same indivisible logical operation without duplicating decision | Complete assessment after audit recovery | Show assessment not completed |
| A new final completion conflicts with the existing completed decision | F21 | Nonretryable | Reject the conflicting operation | Preserve existing authoritative history; create no competing completion | Record conflict safely | No alternate final completion for the same assessment | Existing completed state | Show the existing completion |
| Persisted state contains contradictory final decisions or an impossible completion history | F24 | Nonretryable until engineering establishes safe recovery | Fail closed and escalate | Preserve all existing records; create no new completion or silent repair | Record invariant code, related decision/event IDs, and diagnostic reference | No ordinary retry until integrity is proven | Engineering investigation | Show completion blocked by an integrity violation |

### 15. Preserve Audit History

| Failure condition | Category | Retryability | Stop or continue | Authoritative record behavior | Audit behavior | Idempotency | Recovery entry point | Human visibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Required audit event cannot be made durable | F22 | Retryable or conditional | Fail the owning auditable operation closed | No partial `AuditEvent`; owning operation is not acknowledged complete | Recovery must later record original activity, failure correlation, and outcome | Same logical event identity resolves to one recorded event | Preserve audit history after recovery | Show affected workflow stage blocked |
| Required audit event content is incomplete, references the wrong assessment or type, or fails integrity validation | F22 | Retryable or conditionally retryable after safe correction | Reject the event and fail the owning operation closed | Invalid event is not authoritative and cannot substitute for domain content | Use protected diagnostic correlation; record correction and recovery as a new complete event | Never mutate or silently replace an existing event; corrected content retains the logical event identity when its meaning is unchanged | Preserve audit history after audit-content recovery | Show audit recording blocked |
| Audit detail contains a secret, credential, protected resource detail, or unsanitized payload | F22 | Conditionally retryable after deterministic sanitization | Reject audit content and block owning operation when event is required | No unsafe `AuditEvent` is persisted | Record only safe diagnostic correlation through approved protected handling | Sanitized retry keeps the same logical event identity when event meaning is unchanged | Preserve audit history with sanitized fields | Show a generic audit-recording failure, not the sensitive content |
| Audit recording operation is interrupted before durability is known | F23 | Retryable after resolving existing state | Stop and reconcile before replay | At most one complete event exists | Record interruption and recovery through the eventual audit-aware recovery outcome | Existing event is returned or one safe retry occurs | Preserve audit history | Show audit completion pending |
| Reconciliation proves the required audit event was not durably recorded | F22 | Retryable or conditionally retryable | Fail the owning operation closed until audit recovery | No partial `AuditEvent`; owning operation is not acknowledged complete | Later record original activity, failure correlation, and recovery outcome | Record the same logical event once | Preserve audit history after recovery | Show affected stage blocked by audit failure |

## Retry and Idempotency Rules

Idempotency is a logical guarantee, not a database or API mechanism. Every
operation has a stable logical attempt or submission identity and a canonical
set of authoritative inputs. Identical logical retries do not create duplicate
authoritative results. A successful replay is a control outcome, not a retry
after failure. Actual failures, recovery attempts, rejected conflicts, and
normal invalidations are audited. Replay detection may be audited when useful
and is required only for a critical operation whose audit rules require it.

| Operation | Identical replay behavior | Changed-input behavior | Audit behavior |
| --- | --- | --- | --- |
| Request submission replay | Return or reference the existing complete `AssessmentRequest`; never create two assessments for one logical submission | Materially changed context creates a new assessment and may link to the earlier one | Replay detection may record the canonical comparison result and assessment identifier; a real failed attempt and its recovery are audited |
| Evidence collection retry | A repeated delivery of one completed attempt resolves to the same `EvidenceRecord`; a real retry uses a new attempt and evidence identity | Source result, collector version, or requested evidence change creates a new append-only evidence record | Record predecessor attempt, source, collector version, retry reason, and outcome |
| Evidence persistence retry | Resolve uncertain durability first; identical payload, outcome, provenance, and digest produce one authoritative evidence record | Changed content is not the same persistence retry and requires a new collection outcome | Record persistence attempt, integrity check, existing/new record resolution, and outcome |
| Metric recalculation | Identical evidence, freshness evaluations, and definition version may reuse a verified result or produce equivalent content without conflict | Changed evidence, freshness rule/evaluation, or metric version creates a successor `MetricResult` | Record exact inputs, definition, trigger, reuse or successor, and comparison |
| Policy reevaluation | Identical context, evidence, metrics, freshness evaluations, policy, requirement, and engine versions may reuse verified findings | Changed inputs or versions create a new evaluation ID and successor findings | Record evaluation inputs, versions, reason, reused records, and supersession |
| Report regeneration | Re-delivery of one generation attempt resolves to the same terminal report; a new generation creates a new report identity | Any input, prompt, model, schema, configuration, or report-definition change creates a successor report | Record fixed input set, versions, predecessor, reason, and provider outcome |
| Report validation replay | Identical candidate, fixed inputs, validator rules, and versions return or reproduce the existing structural, reference, and grounding outcomes without a failure category | Changed candidate or validation rules require a new report attempt or explicitly versioned successor | Preserve all validation statuses and versions; replay detection may be recorded when useful, while a changed-input validation attempt is audited |
| Further investigation routing | Replaying the same nonfinal decision and routing inputs returns the existing earliest-stage route without a failure category or duplicate transition | A new human question, concern, affected conclusion, or authoritative input creates a new nonfinal decision or routing evaluation | Preserve the decision, routing-rule version, affected and reused records, and selected stage; identical replay detection may be recorded when useful |
| Human decision submission replay | Same `decision_submission_id`, assessment, and canonical content returns the existing decision | Different content with the same ID fails; a distinct final submission after completion is rejected | Record replay or conflict without duplicating the authoritative decision |
| Audit recording retry | Same logical event identity returns the existing complete event or records it once | Changed event meaning is a new event, not a retry or mutation | Record recovery correlation, original activity time, attempt chain, and final durability outcome |

An identical retry cannot silently adopt a newer input or rule. A changed input,
version, freshness evaluation, or assessment context cannot silently reuse an
incompatible result. Successful replay receives no failure category. Recovery
after uncertain durability first reconciles whether the authoritative result
exists; retry after a proven failure remains an auditable failure recovery;
changed input produces a successor; and a conflicting operation is rejected.

## Recovery and Workflow Resumption

Deterministic orchestration selects the earliest stage whose authoritative
output is missing, invalid, ineligible, or changed. Only that stage and affected
downstream stages repeat.

Completed work may be reused only when all of these conditions hold:

1. its authoritative inputs remain identical;
2. its calculation, policy, schema, prompt, model, authorization, and other
   applicable versions remain valid for the resumed workflow;
3. its freshness requirements remain satisfied at the new time of use;
4. its authoritative record remains complete, valid, and eligible;
5. no investigation request or integrity finding invalidated the result; and
6. reuse is deterministic and audited.

| Recovery scenario | Earliest safe entry | Reuse behavior |
| --- | --- | --- |
| Restart after interruption | Last incomplete stage identified by persisted workflow state and attempt history | Reuse every prior complete record that passes all reuse checks |
| External source recovery | Evidence collection for the affected evidence kind | Preserve prior failures and unavailable outcomes; create successor evidence |
| Recollection after stale evidence | Evidence collection | Reuse unrelated current evidence; recalculate only affected metrics and downstream policy/report records |
| Recalculation after definition change | Metric calculation | Reuse immutable evidence when compatible; create successor metrics and repeat affected downstream stages |
| Policy reevaluation after policy change | Policy evaluation unless the new policy requires new evidence or metrics, in which case route earlier | Reuse compatible evidence and metrics; create new finding set and report |
| Report regeneration after input change | Earliest changed evidence, metric, or policy stage; report generation only when authoritative inputs remain valid | Preserve prior reports; create a successor report with a fixed new input set |
| Human request for further investigation | Evidence collection, metric calculation, policy evaluation, or report generation as selected by deterministic routing | Reuse unaffected completed stages and disclose reused records |
| Retry after audit recording failure | The same unacknowledged auditable operation | Resolve existing domain/event durability and retry idempotently; never repeat the business operation blindly |

If orchestration encounters impossible or contradictory state while determining
the earliest safe stage or record compatibility, F24 applies. If the problem
cannot yet be classified deterministically, F25 applies. In either case the
workflow fails closed; ordinary uncertainty or expected changed inputs follow
the normal invalidation control instead.

## Fail-Closed Requirements

| Required operation | Fail-closed rule |
| --- | --- |
| Required request validation | Invalid, unsupported, or incomplete submitted requests cannot enter evidence collection |
| Raw evidence persistence before dependent calculations | No metric, policy, or report may reference evidence that is not complete and durable |
| Required metric calculation | Failed or unsupported required metrics cannot be replaced with zero, false, guessed, or successful values |
| Required policy evaluation | Missing versions, engine failures, or incomplete finding sets cannot be bypassed by AI or human narrative |
| Report structural validation | `failed` or `not_run` makes the report unusable |
| Report reference validation | Missing, wrong-type, cross-assessment, unresolved, or outside-input references make the report unusable |
| Report deterministic grounding validation | Unsupported material claims or `not_run` validation make the report unusable |
| Human reviewer authorization | Unauthorized or incomplete participation cannot record a disposition |
| Final decision uniqueness | Identical replay returns the existing decision; conflicting final submission is rejected |
| Final decision, assessment completion, and required audit recording | All three succeed as one logical operation or none is acknowledged complete |

An assessment must not appear `completed` when its final audit operation did
not complete successfully. This is a logical atomicity requirement and does not
choose transaction or persistence syntax.

## Human-Visible Failure and Uncertainty

The review experience must show, in safe language:

1. every failed evidence source and evidence kind;
2. missing evidence and its consequence;
3. partial evidence and named omissions;
4. stale evidence, the at-use freshness status, and applicable rule version;
5. retry history and current retryability;
6. reused prior records and why reuse was allowed;
7. unresolved, not-evaluable, failed, or investigation-required policy work;
8. unusable reports and which validation layer blocked them;
9. investigation requests, concerns, affected conclusions, and current route;
10. authorization failures without protected resource or identity detail beyond
    what the viewer is allowed to know;
11. the workflow stage currently blocked; and
12. the next allowed human action, such as correct input, wait for an eligible
    retry, provide authorized participation, request investigation, or begin a
    new assessment.

Technical error payloads are not evidence. The AI model may translate a
sanitized deterministic classification into plain language but may not convert
failure detail into a repository conclusion or claim that missing facts are
known.

## Security and Privacy Requirements

1. Never store secrets, access tokens, passwords, credentials, authorization
   headers, or equivalent values in `AuditEvent` or human-visible failure text.
2. Sanitize and categorize external error messages before presenting them to a
   user.
3. Preserve only the diagnostic context required for investigation; use opaque
   internal references rather than copying unnecessary sensitive payloads.
4. Authorization failures must not reveal whether a protected resource exists,
   its content, or permissions the viewer is not allowed to inspect.
5. AI prompts must not receive unnecessary raw failure payloads, credentials,
   protected diagnostics, or unrelated personal information.
6. Model-generated explanations cannot replace deterministic failure
   classification, retryability, disposition, or workflow routing.
7. Evidence snapshots retain only the minimum authoritative content required by
   the evidence and provenance rules.

## Relationship to the Domain Model

| Domain boundary | Failure-model preservation |
| --- | --- |
| `AssessmentRequest` is the aggregate root | Every failure, attempt, record, event, and recovery remains scoped to one assessment |
| Authoritative records are append-only | Retries create complete new attempts or successors; no historical outcome is overwritten |
| One authoritative final `HumanDecision` | Replays return the existing decision and conflicts are rejected |
| Evidence precedes metrics and conclusions | Persistence failures block all dependent stages |
| Typed report grounding | Direct facts, calculations, and policy conclusions validate against exact typed records in the fixed input set |
| Deterministic workflow ownership | Software owns detection, classification, retry, routing, state, and validation |
| Human decision ownership | Humans supply the authorized disposition, rationale, conditions, or investigation request |
| `AuditEvent` is activity history | Events record activity but never contain the only copy of authoritative domain content |
| Successor integrity | Every predecessor link remains type-correct, same-assessment, earlier, nonself, acyclic, and append-only |
| Reproducibility | Attempts preserve exact inputs, versions, freshness evaluations, outcomes, and recovery decisions |

No contradiction requiring a change to [domain_model.md](domain_model.md) was
found while defining this failure model.

## Success Criteria Alignment

This model defines behavior that a later implementation and evaluation can test.
It does not claim measured reliability or customer impact.

| Success concern | Failure-model support |
| --- | --- |
| Evidence provenance | Every terminal collection outcome preserves source, attempt, collector version, status, available provenance, and audit correlation |
| Evidence before calculation | Persistence failure blocks metric, policy, and report stages |
| Deterministic reproducibility | Retries preserve exact inputs, definition versions, freshness evaluations, and equivalent-result requirements |
| Policy traceability | Findings preserve policy/requirement versions and exact evidence/metric causes; engine failures create no fabricated findings |
| Typed generated-claim grounding | Structural, reference, and grounding failures make reports unusable; exact typed references remain required |
| Safe missing-evidence behavior | Missing, partial, failed, and stale evidence stays explicit and never becomes favorable |
| Human decision ownership | Authorization is deterministic, but only an authorized human supplies the disposition and rationale |
| Retry integrity | Attempt identity, predecessor history, idempotent replay, and successor rules prevent silent duplication |
| Structured report validity | A report reaches human review only after all three deterministic validations pass |
| Audit-record completeness | Required audit failure blocks acknowledgement of the owning operation, including final completion |

Alignment was checked against [success_criteria.md](success_criteria.md),
[proposed_workflow.md](proposed_workflow.md), and the durable architecture and
patterns in [memory](../memory/ARCHITECTURE.md).

## Assumptions

* Deterministic components can distinguish transient transport conditions from
  invalid content using versioned classifications.
* Logical operation, attempt, submission, correlation, and causation identities
  can be implemented without changing the seven-entity model.
* A complete failed or unavailable evidence outcome can retain safe provenance
  without retaining credentials or protected payloads.
* Policy can explicitly state when review may continue with uncertainty.
* Human-facing explanations can be separated from protected diagnostic detail.
* Audit-aware recovery can determine whether an authoritative record or event
  already became durable before replay.

## Unresolved Operational Values and Questions

The following remain deferred until implementation and evaluation provide the
required evidence:

1. retry counts, retry budgets, delay, backoff, jitter, and timeout values;
2. source-specific rate-limit eligibility and escalation behavior;
3. operational ownership and escalation timing for blocked assessments;
4. the exact minimum evidence set and which evidence gaps policy may permit;
5. policy-owner and reviewer-authorization matrices;
6. approved freshness rules for each evidence kind;
7. diagnostic retention, access control, sanitization, and audit-retention
   policies;
8. identifier, integrity, logical atomicity, and persistence mechanisms;
9. criteria for terminating an assessment after repeated nonterminal failures;
   and
10. the governed process, if any, for correcting an erroneously recorded final
    decision.

These deferrals do not permit silent continuation or scope expansion.

## Explicitly Deferred and Out of Scope

This document does not add or design application code, Pydantic models,
FastAPI routes, API contracts, database schemas, migrations, queue
implementations, retry libraries, GitHub collectors, AI integrations, Docker,
CI, monitoring configuration, distributed services, automatic remediation, or
continuous monitoring.

Operational values are configuration to be selected later from source
constraints, evaluation evidence, and approved reliability requirements.
