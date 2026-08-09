# Day 12 Durable Evidence Loading and Evaluation Plan

## Task

Add a read-only SQLite boundary that reconstructs one valid assessment request
and its complete authoritative evidence set, then pass that verified set to the
unchanged deterministic assessment evaluator.

## Objective

Given an assessment identifier and an existing exact schema-v4 database, load
and verify exactly one `EvidenceRecord` for each evaluator-required kind in
canonical order. Evaluation succeeds only after the complete set verifies and
returns the existing transient metrics and policy findings without persisting
derived conclusions.

## Current State

SQLite schema version 4 durably stores complete valid Day 5 requests and
terminal outcomes for repository archived status, license status, latest
commit timestamp, and effective security-policy presence. Each evidence-
producing write becomes authoritative only after close, reopen, source
reconstruction, digest and normalization checks, relationship verification,
and reconstruction through the unchanged `EvidenceRecord` contract.

The deterministic evaluator already requires those four evidence kinds in the
order repository archived, license status, latest commit timestamp, and
security policy present. An unavailable `EvidenceRecord` is a complete input;
it deterministically produces an unavailable metric and a `NOT_EVALUABLE`
finding. No current public read boundary can assemble durable evidence for the
evaluator.

## Proposed Solution

Add the frozen public `VerifiedAssessmentEvidenceSet` contract and
`load_verified_assessment_evidence(database_path, assessment_id)` to the
concrete persistence module. The loader will:

* reject invalid paths and identifiers through sanitized persistence errors;
* open an existing database with SQLite URI `mode=ro`, enable foreign keys and
  query-only mode, and require the exact schema-v4 definition without creating
  or migrating anything;
* perform schema, request, evidence, source, relationship, and foreign-key
  reads in one explicit read transaction;
* fail with `evidence_set_ambiguous` if any required kind has multiple rows,
  then fail with `evidence_set_incomplete` if any required kind is absent;
* reconstruct each selected collection attempt using the existing per-kind
  durable constructors and expected-value helpers;
* require every attempt and evidence row to belong to the requested assessment
  and canonical repository identity; and
* return the request validation result plus exactly four verified records in
  evaluator order, or return nothing.

Add `evaluate_persisted_assessment(database_path, assessment_id, evaluated_at)`
to the transient assessment module. It will call the loader exactly once and
then call the unchanged `evaluate_assessment` exactly once with the
reconstructed `AssessmentContext`, canonical evidence tuple, and exact caller-
supplied evaluation timestamp.

## Public Contracts

```python
@dataclass(frozen=True)
class VerifiedAssessmentEvidenceSet:
    validation_result: AssessmentRequestValidationResult
    evidence_records: tuple[EvidenceRecord, ...]

def load_verified_assessment_evidence(
    database_path,
    assessment_id,
) -> VerifiedAssessmentEvidenceSet:
    ...

def evaluate_persisted_assessment(
    database_path,
    assessment_id,
    evaluated_at,
) -> DeterministicAssessmentResult:
    ...
```

The frozen evidence-set contract requires a valid request result with one
usable context, exactly four `EvidenceRecord` values in canonical kind order,
matching assessment identifiers, and no duplicate evidence or attempt
identifiers.

## Files Affected

* `plans/day_12_durable_evidence_loading_and_evaluation.md` records this plan.
* `src/engineering_due_diligence/persistence.py` adds the frozen read result,
  strict read-only connection, aggregate verification, and public loader.
* `src/engineering_due_diligence/assessment.py` adds the narrow persisted-
  assessment evaluation function.
* `tests/test_durable_assessment_evaluation.py` proves loading, failure, and
  evaluator integration behavior with real on-disk SQLite files.

## Database Impact

There is no schema version 5 and no data mutation. The loader accepts only an
existing exact schema-v4 database, opens it read only, and never creates,
migrates, repairs, or writes rows, schema, metadata, metrics, or findings.

## Testing Strategy

Focused tests use real temporary on-disk SQLite databases and patched GitHub
transport during setup. They cover:

1. four available records;
2. a mixed available and unavailable evidence set;
3. canonical evidence ordering independent of insertion order;
4. unavailable evidence producing unavailable metrics and `NOT_EVALUABLE`;
5. a missing evidence kind;
6. duplicate evidence for one kind;
7. a missing assessment;
8. a nonexistent database path remaining nonexistent;
9. corrupted source content and cross-repository relationships;
10. equality between direct and persisted deterministic evaluation;
11. exactly one loader call and one evaluator call;
12. exact aware `evaluated_at` preservation;
13. unchanged database bytes, schema version, schema definitions, and row
    content after reads; and
14. no network calls during loading or evaluation.

Run the focused module, the complete suite, compilation, whitespace checks,
diff review, and Git status inspection.

## Acceptance Criteria

* The database is opened strictly read only and remains unchanged.
* All reads that determine the returned set occur in one consistent snapshot.
* Exactly one fully reconstructed record for each required kind is returned in
  canonical order; unavailable evidence satisfies completeness.
* Missing, ambiguous, corrupt, cross-assessment, or cross-repository data fails
  closed with stable sanitized persistence categories.
* The existing evaluator is unchanged and is called once only after successful
  durable verification.
* Metrics and policy findings remain transient.
* All focused and existing tests, compilation, and whitespace verification
  pass.

## Risks

The schema permits multiple evidence rows for a kind because it records
collection history but has no current-selection policy; Day 12 therefore fails
ambiguous rather than guessing. A long read transaction can temporarily retain
an older SQLite snapshot while a writer proceeds. SQLite corruption is
detected, not repaired. The concrete loader remains specific to exact schema
v4 and the four public GitHub evidence kinds.

## Rollback Plan

Remove the new loader, evidence-set contract, assessment integration function,
focused tests, and this plan. No database rollback or migration is required
because Day 12 does not mutate schema or durable content.

## Explicit Exclusions

No schema change, metric or finding persistence, workflow orchestration,
current-evidence selection policy, API, CLI, retry execution, audit event,
reporting, model behavior, collector, ORM, repository abstraction, provider
abstraction, production infrastructure, or network behavior is added.

## Implementation Checklist

* Confirm the exact v4 schema and existing per-kind reopen checks.
* Add the frozen aggregate read contract and strict read-only connection.
* Add complete one-snapshot verification in canonical evidence order.
* Add the single-load, single-evaluation integration function.
* Add the focused real-file SQLite tests.
* Run all verification and review the complete diff.
