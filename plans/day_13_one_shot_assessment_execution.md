# Day 13 One-Shot Assessment Execution Plan

## Task

Add one narrow application workflow that validates and persists an assessment
request, collects and persists the four required public GitHub evidence kinds,
then evaluates the complete reopened durable evidence set.

## Objective

Given one submitted request, an on-disk SQLite path, an aware collection time,
and an aware evaluation time, return either explicit request-validation data,
one durably recorded collection failure, or one complete transient deterministic
assessment result. No calculation may run before all four authoritative
evidence records exist.

## Current State

Day 5 validates a transient `AssessmentRequestInput`. The four public GitHub
collectors return strict terminal results for repository archived status,
license status, latest commit timestamp, and effective security-policy
presence. SQLite schema version 4 persists valid requests and every terminal
collector outcome, and returns evidence only after close-and-reopen
verification. Day 12 loads exactly one verified record for each required kind
and calls the unchanged deterministic evaluator. These boundaries are not yet
connected by one application operation.

## Proposed Solution

Create `workflow.py` with five public contracts:

```python
class AssessmentExecutionStatus(str, Enum): ...

@dataclass(frozen=True)
class AssessmentExecutionInput:
    request: AssessmentRequestInput
    collection_attempted_at: datetime
    evaluated_at: datetime

@dataclass(frozen=True)
class AssessmentExecutionFailure:
    evidence_kind: EvidenceKind
    collection_attempt_id: str
    outcome: GitHubCollectionOutcome
    error: GitHubRepositoryMetadataCollectionError

@dataclass(frozen=True)
class AssessmentExecutionResult:
    execution_input: AssessmentExecutionInput
    validation_result: AssessmentRequestValidationResult
    status: AssessmentExecutionStatus
    failure: Optional[AssessmentExecutionFailure]
    assessment_result: Optional[DeterministicAssessmentResult]

def execute_assessment(database_path, execution_input): ...
```

Validation failure returns before database or network activity. A valid request
is persisted and verified before collection. Collection and persistence run in
the evaluator's canonical order. Available and unavailable outcomes must
produce verified evidence before the next collector starts. A retryable or
nonretryable failure is persisted as an attempt, then returned as a sanitized
execution failure without later collection or evaluation. After four evidence
records exist, the workflow calls `evaluate_persisted_assessment` exactly once.

Each kind uses attempt number 1 and the same exact caller-supplied collection
timestamp. Its attempt identifier is:

```text
collection-attempt-<sha256>
```

The digest input is UTF-8 canonical JSON with sorted keys and compact
separators containing exactly:

```json
{
  "assessment_id": "<assessment ID>",
  "attempt_number": 1,
  "evidence_kind": "<evidence kind>",
  "namespace": "assessment-execution.v1"
}
```

The identifier is independent of remote content and wall-clock time. An exact
rerun therefore reaches the existing idempotent persistence checks. Changed
request, timestamp, collector result, response content, or provenance under the
same attempt identity conflicts without mutation. Real retry, recollection,
and reassessment require a new attempt and remain deferred.

## Files Affected

* `plans/day_13_one_shot_assessment_execution.md` records the locked slice.
* `src/engineering_due_diligence/workflow.py` adds the contracts and one-shot
  application operation.
* `tests/test_one_shot_assessment_execution.py` proves the full boundary with
  patched GitHub transport and real temporary SQLite files.

No existing source, test, documentation, memory, journal, or ADR file changes.

## Database Impact

There is no schema change. The workflow uses exact schema version 4 through the
existing public persistence functions. Each request or collection operation
retains its existing transaction and reopen-verification boundary. Metrics and
policy findings remain transient and are not written to SQLite.

## Testing Strategy

Focused tests cover frozen contracts and result invariants, one complete
execution, mixed available and unavailable evidence, invalid request short
circuiting, canonical collector order, stable distinct attempt identifiers,
request persistence before collection, evidence persistence before the next
collector, mid-sequence failure, persistence-error propagation, programmer-
error propagation, exact replay without duplicate rows, changed remote content
conflicting without mutation or evaluation, exactly one evaluation call,
schema version 4, absence of derived-result tables, and no live network calls.

Run the focused module, the complete suite, compilation, `git diff --check`,
diff-stat inspection, complete diff review, and Git status inspection.

## Acceptance Criteria

* Invalid submissions cause no database or network activity.
* A valid request is durable before the first collector starts.
* The four kinds execute in canonical order with stable attempt identities.
* Every terminal outcome is durable and verified before another collector
  starts.
* Available and unavailable records proceed; the first failed outcome stops.
* Evaluation runs exactly once only after four authoritative records exist.
* No partial deterministic result is returned on collection or persistence
  failure.
* Exact replay adds no rows; conflicting replay changes no rows and does not
  evaluate.
* Existing persistence and evaluation errors retain their established
  behavior.
* SQLite remains exact schema version 4 and all tests pass.

## Risks

The operation is intentionally one shot. Earlier authoritative evidence and a
failed attempt remain durable after a later collection failure, but Day 13 does
not resume or retry that assessment. The complete assessment is not one global
transaction. A real remote change is not an exact replay and cannot be selected
as current evidence without future retry and selection rules. Metrics and
findings can be reproduced but remain transient.

## Rollback Plan

Remove the workflow module, focused tests, and this plan. No schema or stored-
data rollback is required.

## Explicit Exclusions

No retry, resume, reassessment, current-evidence selection, persisted workflow
state, audit history, metric or finding persistence, API, CLI, reporting,
model behavior, new collector, ORM, repository abstraction, provider
abstraction, generic workflow engine, or production infrastructure is added.

## Implementation Checklist

* Confirm the exact upstream public contracts and canonical evidence order.
* Add the frozen execution contracts and deterministic attempt identity rule.
* Implement validation, persistence, collection, and evaluation sequencing.
* Add focused real-file and patched-transport tests.
* Run focused and complete verification.
* Review correctness, failure behavior, replay, scope, and the complete diff.
