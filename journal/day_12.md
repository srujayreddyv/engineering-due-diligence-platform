# Day 12 Journal

## Work Completed

Implemented strict read-only loading of one complete authoritative assessment
evidence set and connected it to the unchanged deterministic evaluator. The new
public contracts are:

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

`VerifiedAssessmentEvidenceSet` contains one exact valid request-validation
result and four `EvidenceRecord` values in the evaluator's canonical order:

1. repository archived;
2. license status;
3. latest commit timestamp; and
4. security policy present.

The frozen contract rejects an invalid or contradictory request result,
noncanonical evidence ordering, cross-assessment records, and duplicate
evidence or collection-attempt identifiers.

## Read-Only SQLite Boundary

The loader accepts only a caller-supplied existing on-disk database and opens
it through SQLite URI `mode=ro`. It enables foreign-key enforcement and
`query_only`, starts one explicit read transaction, and requires the exact
schema-v4 version and definitions. It never invokes the write-capable
connection path and cannot create, initialize, migrate, repair, or update the
database.

Schema verification, foreign-key checks, request reconstruction, evidence-set
selection, collection-attempt reads, source snapshots, ordered security-policy
observations, and final relationship checks all occur within the same
transaction snapshot. Tests compare database bytes, schema version, schema
definitions, and complete row content before and after loading and evaluation.

## Completeness and Durable Verification

Unavailable `EvidenceRecord` values count as present evidence because they are
explicit authoritative outcomes understood by the existing evaluator. A
missing required kind fails with the stable sanitized category
`evidence_set_incomplete`. More than one evidence row for a required kind fails
with `evidence_set_ambiguous`; the loader does not infer a current record.

Each selected record is reconstructed from its durable request, collection
attempt, full source response, and ordered observations where applicable. The
loader recomputes source and compact digests, reparses source payloads,
revalidates repository binding and normalized values, verifies provenance,
relationships, timestamp representations, collector and normalization
versions, and reconstructs the unchanged `EvidenceRecord`. Cross-assessment,
cross-repository, corrupt, incomplete, or contradictory content fails as a
sanitized `verification_failed` result. Nothing is returned until all four
records verify.

## Deterministic Evaluation Integration

`evaluate_persisted_assessment` calls the durable loader exactly once, uses its
reconstructed `AssessmentContext`, and calls the unchanged
`evaluate_assessment` exactly once. It preserves the exact caller-supplied aware
`evaluated_at` representation. Failure during loading or deterministic
evaluation returns no partial `DeterministicAssessmentResult`, metrics, or
policy findings.

Metrics and policy findings remain transient. Day 12 introduced no schema
version 5 and does not persist derived evaluation output.

## Review Findings

The implementation and final diff were reviewed for read-only enforcement,
transaction consistency, evidence completeness, source-based reconstruction,
relationship isolation, error sanitization, evaluator call count, atomic
failure behavior, and scope. No material correctness issue remained and no
review-time source correction was required.

## Verification

Fourteen focused Day 12 tests cover four available records, mixed available and
unavailable records, canonical order, missing and ambiguous evidence,
nonexistent databases, corruption and repository mismatch, direct-versus-
persisted evaluation equivalence, exact call counts and timestamps, database
immutability, and absence of network calls.

The complete suite passes:

```text
Ran 219 tests
OK
```

Compilation and whitespace verification also pass.

## Risks and Explicit Exclusions

The schema can retain multiple attempts for one evidence kind, but no current-
evidence selection policy exists; the loader therefore fails ambiguity rather
than guessing. A long read transaction can retain an older consistent SQLite
snapshot. SQLite corruption is detected rather than repaired, and the loader
is deliberately specific to exact schema v4 and the four public GitHub evidence
kinds.

Day 12 added no schema migration, metric or finding persistence, workflow
orchestration, API, CLI, retry execution, audit event, reporting, model
behavior, collector, ORM, repository abstraction, provider abstraction,
production infrastructure, or live-network behavior.

## Next Task

The next task should begin with a read-only Day 13 direction review. Do not
begin Day 13 implementation before that review selects the narrowest next
workflow slice.
