# Day 4 In-Memory Assessment Result Plan

## Task

Add the smallest in-memory orchestration boundary that evaluates one complete
deterministic assessment and returns its fixed context, evidence, metrics, and
policy findings as one frozen transient result.

## Objective

Provide a public `evaluate_assessment` function that snapshots caller-owned
evidence immediately, presents the evidence in the canonical Day 3 order,
delegates deterministic work to `evaluate_slice`, and returns a complete
`DeterministicAssessmentResult` only after the entire evaluation succeeds.
Success means that every returned metric references evidence in the returned
input set, every returned finding references both a returned metric and its
returned evidence, and failures expose no partial aggregate.

## Current State

Day 3 defines frozen `AssessmentContext`, `EvidenceRecord`, `MetricResult`, and
`PolicyFinding` records in `models.py`. `evaluation.py` defines the canonical
`REQUIRED_EVIDENCE_KINDS`, `METRIC_TO_EVIDENCE_KIND`, and
`REQUIREMENT_TO_METRIC` mappings and exposes `evaluate_slice`, which validates
the complete evidence set, calculates four metrics, validates their exact
deterministic derivation, and creates four policy findings.

`evaluate_slice` already provides atomic metric-and-finding evaluation and
enforces assessment ownership, required and unique evidence, evidence
integrity, temporal ordering, deterministic metric identity, and reference
traceability. It returns metrics in Day 3 metric order and findings in Day 3
requirement order, but it does not retain the context or evidence in a single
result object. Callers also must currently supply an aware evaluation
timestamp.

Assumptions:

* This result is a transient in-process value, not an authoritative persisted
  assessment record and not a workflow-stage record.
* The public API is
  `evaluate_assessment(context, evidence_records, evaluated_at)` in
  `engineering_due_diligence.assessment`.
* `evaluated_at` is required and must be a caller-supplied aware timestamp. The
  function preserves it exactly, including its UTC offset, and never reads the
  current time.
* `EvidenceRecord` is already frozen, so copying the sequence into a tuple is
  sufficient to isolate the result from later sequence mutation.

## Proposed Solution

### Frozen transient result

Add this frozen standard-library dataclass to `assessment.py`:

```python
@dataclass(frozen=True)
class DeterministicAssessmentResult:
    context: AssessmentContext
    evidence_records: tuple[EvidenceRecord, ...]
    metric_results: tuple[MetricResult, ...]
    policy_findings: tuple[PolicyFinding, ...]
    evaluated_at: datetime
```

The type is a structural in-memory envelope. It receives no result identifier,
schema version, persistence state, serialization layer, mutable collections,
or workflow behavior. Do not add a second `__post_init__` validation engine:
the trustworthy construction path is `evaluate_assessment`, and Day 3 remains
the single authority for deterministic input and reference validation.

### Public orchestration function

Add this public function to `assessment.py`:

```python
def evaluate_assessment(
    context: AssessmentContext,
    evidence_records: Sequence[EvidenceRecord],
    evaluated_at: datetime,
) -> DeterministicAssessmentResult:
```

Implement it in this order:

1. Immediately execute `evidence_snapshot = tuple(evidence_records)` before
   invoking any evaluator. Never read the caller-owned sequence again.
2. Call `evaluate_slice(context, evidence_snapshot, evaluated_at)` exactly
   once. Let it validate timezone awareness and every Day 3 invariant, and let
   its existing exception types propagate unchanged. Pass the required
   caller-supplied timestamp through without reading the current time or
   normalizing its offset.
3. Only after successful evaluation, index the validated snapshot by evidence
   kind and build the returned evidence tuple in `REQUIRED_EVIDENCE_KINDS`
   order. Do not duplicate Day 3 required, duplicate, ownership, integrity, or
   temporal validation.
4. Only after evaluation and canonical ordering both succeed, construct and
   return `DeterministicAssessmentResult` with the exact context, canonical
   evidence tuple, returned metric tuple, returned finding tuple, and the same
   caller-supplied timestamp object.

Do not catch evaluation exceptions, publish an intermediate result, or retain
mutable accumulation state. If snapshotting, ordering, timestamp validation,
metric calculation, or policy evaluation fails, the call raises and no
`DeterministicAssessmentResult` exists.

### Reference closure and Day 3 ordering

The returned fixed report-input set is closed as follows:

* `evidence_records` contains the four exact input records ordered by
  `REQUIRED_EVIDENCE_KINDS`.
* `metric_results` is the complete tuple returned by `evaluate_slice`; Day 3
  already proves that each metric has the same assessment ID and references
  its exact required record from `METRIC_TO_EVIDENCE_KIND`.
* `policy_findings` is the complete tuple returned by `evaluate_slice`; Day 3
  creates each finding from `REQUIREMENT_TO_METRIC`, with its metric identifier
  and that metric's evidence identifiers.
* The wrapper does not sort, rebuild, copy with `replace`, or revalidate metrics
  or findings. Their identity, equality, ordering, version fields, timestamps,
  and reference tuples remain exactly as Day 3 produced them.

The focused closure test described below verifies the aggregate-level property
without moving deterministic checks out of `evaluate_slice`.

## Files Affected

The implementation is limited to:

* `src/engineering_due_diligence/assessment.py` — add the frozen transient
  result and public orchestration function.
* `tests/test_assessment_result.py` — add only the focused tests listed below
  with local Day 3-compatible fixtures.
* `README.md` and `journal/day_04.md` — record verified current state, review
  findings, exclusions, and the next task after implementation review.

This planning task changes only
`plans/day_04_in_memory_assessment_result.md`.

## Database Impact

None. The result is explicitly transient and in memory. There is no schema,
migration, repository, data-access layer, fixture format, seed data, durable
identifier, or stored record.

## Testing Strategy

Add exactly these focused test cases to `tests/test_assessment_result.py`:

1. `test_evaluate_assessment_returns_frozen_complete_result` — call the public
   function with valid strict-context evidence; assert the context is the exact
   input object, the four evidence/metric/finding tuples are present, the
   timestamp is the supplied timestamp, and assigning to a result field raises
   `FrozenInstanceError`.
2. `test_evaluate_assessment_snapshots_sequence_once_before_delegation` — pass a
   test-local one-shot evidence sequence that raises if iterated twice; assert
   evaluation succeeds and the original sequence was consumed exactly once.
   This proves subsequent work uses the tuple snapshot rather than the caller's
   sequence.
3. `test_evaluate_assessment_canonicalizes_reversed_evidence_order` — pass the
   four valid records in reverse order; assert returned evidence kinds equal
   `REQUIRED_EVIDENCE_KINDS`, each kind appears exactly once, and the metric and
   finding tuples equal direct `evaluate_slice` output for the same reversed
   input and timestamp.
4. `test_evaluate_assessment_preserves_supplied_aware_offset_timestamp` — use a
   non-UTC aware timestamp representing the evaluation instant; assert the
   result retains that exact object and representation and every metric
   `calculated_at` and finding `evaluated_at` equals it.
5. `test_evaluate_assessment_equivalent_timezone_instants_preserve_supplied_representations`
   — evaluate the same context and evidence with two required aware timestamps
   that represent the same instant using different UTC offsets; assert the two
   results have equivalent deterministic metric and finding tuples while each
   result retains its exact supplied timestamp object, `tzinfo`, and ISO 8601
   representation.
6. `test_evaluate_assessment_rejects_naive_timestamp_without_result` — initialize
   `result = None`, call with a naive timestamp, assert the existing
   `SliceEvaluationError` type without coupling to its message, and assert
   `result` remains `None`.
7. `test_evaluate_assessment_returns_complete_reference_closure` — index the
   returned evidence and metrics by ID; assert every metric evidence reference,
   finding evidence reference, and finding metric reference resolves inside the
   returned result, with no outside identifiers, and assert every contained
   record belongs to the result assessment.
8. `test_evaluate_assessment_missing_evidence_fails_atomically` — initialize
   `result = None`, omit one required record, assert the existing
   `MissingEvidenceRecordError`, and assert no result was assigned. Do not
   introduce a wrapper-specific exception or partial-result sentinel.
9. `test_evaluate_assessment_is_input_order_independent` — evaluate several
   deterministic permutations of the same fixed evidence records at the same
   supplied timestamp; assert the complete `DeterministicAssessmentResult`
   values are equal.

Run focused and broad verification:

```text
PYTHONPATH=src python3 -m unittest tests.test_assessment_result -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

No test should patch Day 3 private helpers or duplicate their validation
matrix. No test should patch a clock because the function does not read one.

## Acceptance Criteria

* `DeterministicAssessmentResult` is a frozen dataclass containing only the
  context, canonical evidence, metrics, findings, and aware evaluation time.
* `evaluate_assessment` is publicly importable from
  `engineering_due_diligence.assessment` and returns the frozen result for a
  valid complete input set.
* The input evidence sequence is converted to a tuple before any later work and
  is never read again.
* Returned evidence follows `REQUIRED_EVIDENCE_KINDS`; no duplicate ordering
  constant is introduced.
* The wrapper calls `evaluate_slice` once and preserves its metric and finding
  tuples without recomputation or transformation.
* `evaluated_at` is required, is never generated internally, and is passed
  through unchanged; supplied aware timestamps and their offsets are
  preserved, while naive timestamps fail through the existing Day 3 error
  contract.
* Every result returned by `evaluate_assessment` contains complete evidence to
  metric to finding reference closure for one assessment.
* Any failure raises before result construction and exposes no partial result.
* All nine focused tests and the full existing test suite pass.
* No persistence, external integration, workflow, report generation, or human
  decision boundary is changed.

## Risks

* A caller can instantiate the structural dataclass directly without Day 3
  evaluation. The API contract must identify `evaluate_assessment` as the
  trustworthy construction path; duplicating the full evaluator in
  `__post_init__` would create a more serious consistency risk.
* Callers own selection of the evaluation instant. Supplying unintended but
  valid aware timestamps changes time-dependent metrics and deterministic IDs;
  the wrapper must not guess or correct caller intent.
* Tuple snapshotting isolates later sequence mutation but is a shallow copy.
  This is sufficient because all current domain records are frozen; changing
  that model assumption would require review.
* Concurrent mutation while Python is iterating a caller-owned mutable
  sequence is outside the guarantee. The snapshot prevents mutation after the
  initial iteration from affecting evaluation.
* A second validation implementation in the wrapper could drift from Day 3.
  The plan mitigates this by delegating all semantic validation and asserting
  only returned aggregate closure in tests.
* Canonical ordering after Day 3 validation must use only the validated
  evidence snapshot and existing required-kind constant. It must not introduce
  a second evidence validation contract.

## Rollback Plan

Revert `assessment.py`, `test_assessment_result.py`, and the Day 4 documentation
updates. No migration, persisted result, external state, or compatibility shim
needs reversal. Existing callers can continue using `evaluate_slice`
unchanged.

## Explicit Exclusions

* Database persistence, repositories, schemas, migrations, and durable
  assessment-result identity.
* Workflow state, retries, resumability, audit events, or stage orchestration.
* Evidence collection, source normalization, or new evidence kinds.
* New metric definitions, policy requirements, thresholds, versions, or Day 3
  exception types.
* AI report generation, reference validation for generated prose, prompt/model
  integration, or human decisions.
* API routes, FastAPI/Pydantic models, CLI commands, serialization contracts,
  memory changes, and ADRs.
* New clock, ordering, validation, aggregate-builder, or persistence
  abstractions.
* Package-root re-exports; the public function is exposed from its defining
  `engineering_due_diligence.assessment` module only.

## Plan Review

* **Scope violations:** None found. The plan stays inside the existing modular
  deterministic slice and adds no collector, persistence, API, workflow, AI,
  or human-decision capability.
* **Unnecessary abstractions:** None found. The only new type is the requested
  frozen result and the only new behavior is the requested public function. A
  clock interface, result builder, ordering helper, and new exception hierarchy
  are explicitly excluded.
* **Duplicated validation:** None planned. Evidence and timestamp validity,
  exact metrics, and finding references remain owned by `evaluate_slice`. The
  wrapper only snapshots, delegates, orders the validated evidence, and
  packages; tests verify closure without creating a second runtime validator.
* **Day 3 consistency:** The plan reuses `REQUIRED_EVIDENCE_KINDS`, passes one
  required caller-supplied timestamp unchanged to `evaluate_slice`, preserves
  Day 3 output tuples and exceptions, and does not change versions, identity
  derivation, policy behavior, or unavailable-evidence semantics.
* **Issue retained as an explicit tradeoff:** Direct construction of the
  structural dataclass cannot prove semantic closure. Adding full validation to
  it would duplicate Day 3, so the plan makes `evaluate_assessment` the
  trustworthy boundary and tests every result returned through that boundary.

## Implementation Checklist

* Confirm the API signature, transient fields, and timestamp assumptions.
* Add the frozen result dataclass without persistence semantics or duplicated
  validation.
* Snapshot evidence once and delegate that tuple exactly once to
  `evaluate_slice` with the required aware timestamp unchanged.
* Canonically order validated evidence using the existing Day 3 constant.
* Construct the result only after complete successful evaluation.
* Add exactly the nine focused tests above.
* Run the focused test module and complete test discovery suite.
* Review correctness, temporal behavior, reference closure, atomic failure,
  backward compatibility, and scope.
* Update README and the Day 4 journal after verification; do not update memory,
  ADRs, or unrelated files.
