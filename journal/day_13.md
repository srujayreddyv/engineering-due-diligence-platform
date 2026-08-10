# Day 13 Journal

## Work Completed

Implemented one narrow application boundary for a complete one-shot public
GitHub assessment. The new public contracts are:

```python
class AssessmentExecutionStatus(str, Enum):
    INVALID_REQUEST = "invalid_request"
    COLLECTION_FAILED = "collection_failed"
    COMPLETE = "complete"

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

def execute_assessment(
    database_path,
    execution_input: AssessmentExecutionInput,
) -> AssessmentExecutionResult:
    ...
```

The frozen result invariants permit exactly three shapes: invalid request with
validation data only, durably recorded collection failure with no assessment
result, or one complete deterministic assessment with no failure.

## One-Shot Workflow Sequence

`execute_assessment` performs the following sequence:

1. validate the submitted request;
2. return immediately on invalid input without touching SQLite or GitHub;
3. persist and reopen-verify the valid request;
4. collect and persist repository archived status;
5. collect and persist license status;
6. collect and persist latest commit timestamp;
7. collect and persist effective security-policy presence; and
8. load the authoritative four-kind evidence set and evaluate it once through
   `evaluate_persisted_assessment`.

Every collector result passes through its existing atomic persistence and
close-and-reopen verification boundary before the next collector begins.
Available and unavailable evidence are both authoritative terminal records and
continue the workflow. Metrics and policy findings are calculated only after
all four records exist and remain transient.

## Deterministic Attempt Identities

Each evidence kind uses attempt number 1 and the exact caller-supplied aware
collection timestamp. Its collection attempt identifier is the prefix
`collection-attempt-` plus the SHA256 digest of canonical UTF-8 JSON containing
the assessment ID, evidence kind, attempt number, and
`assessment-execution.v1` namespace. The identifiers are stable across exact
reruns and distinct across the four kinds.

## Failure and Replay Behavior

The first retryable or nonretryable collection failure is persisted and
reopen-verified, then execution returns `COLLECTION_FAILED`. Later collectors
and evaluation do not run. Earlier authoritative evidence remains durable.
Persistence failures retain their existing sanitized `SQLitePersistenceError`
categories, and unexpected programmer errors are not converted into ordinary
workflow failures.

An exact request and collection replay resolves through the existing
persistence checks without adding duplicate attempts, snapshots,
observations, or evidence. Changed request fields, timestamps, source content,
outcomes, provenance, or other material collection content under the same
deterministic identity raises `conflicting_replay`, changes no durable rows,
and does not evaluate.

## Review Findings

Implementation and final review confirmed request-before-network ordering,
canonical collector order, deterministic identities, per-kind authority
boundaries, fail-fast behavior, complete-set evaluation, error propagation,
result invariants, replay behavior, and scope. No material correctness issue
remained and no review-time source correction was required.

## Verification

Eleven focused Day 13 tests cover complete execution, unavailable evidence,
invalid requests, ordering, deterministic attempt identities, persistence
before subsequent collection, retryable and nonretryable mid-sequence
failures, error propagation, exact and conflicting replay, evaluator call
count, schema stability, transient derived results, and patched network access.

The complete suite passes:

```text
Ran 230 tests
OK
```

Compilation and whitespace verification also pass.

## Schema, Risks, and Explicit Exclusions

Day 13 introduces no schema change; SQLite remains exact version 4. The
complete assessment is not one cross-collector transaction. A later collector
failure leaves earlier valid evidence durable, but the one-shot boundary does
not retry or resume. A changed remote fact is a new collection outcome rather
than an exact replay and requires future attempt-number and current-evidence
selection rules.

Day 13 adds no retry, resume, reassessment, current-evidence selection, durable
workflow state, audit history, metric or finding persistence, API, CLI,
reporting, model behavior, new collector, ORM, repository or provider
abstraction, or production infrastructure.

## Next Task

Day 14 should begin with a read-only direction review for the smallest
customer-facing interaction boundary over the completed one-shot execution.
The next slice should expose existing validation, failure, evidence, metric,
and finding results without beginning another internal foundation layer or
silently adding retry, reporting, model, or human-decision behavior.
