# Day 3 Deterministic Vertical Slice Plan

## Task

Implement the smallest local Python slice that carries assessment context
through stored evidence, deterministic metrics, and context-specific policy
findings.

## Objective

Prove the `AssessmentContext` → `EvidenceRecord` → `MetricResult` →
`PolicyFinding` boundary with four local evidence kinds, explicit unavailable
outcomes, versioned deterministic logic, and complete traceability.

## Current State

Day 1 engagement documentation and the reviewed Day 2 domain and failure
models are committed. The Python package and test package contain only empty
package markers. No runtime dependencies, application code, or infrastructure
exist.

## Proposed Solution

Add immutable standard-library models and pure calculation and policy
functions. Validate the complete evidence set before calculating, return
explicit unavailable results for complete unavailable evidence records, and
evaluate prototype and critical-production contexts with versioned
requirements. Use local test fixtures and no external calls.

## Files Affected

* `src/engineering_due_diligence/models.py` — typed immutable records.
* `src/engineering_due_diligence/evaluation.py` — deterministic metric and
  policy evaluation.
* `tests/test_deterministic_slice.py` — local fixtures and focused behavior
  tests.
* `README.md` — brief current-state summary after verification.
* `journal/day_03.md` — factual work record after verification.

## Database Impact

None. The slice is pure in-memory logic and defines no schema, migration, data
access layer, or stored-record implementation.

## Testing Strategy

Use the standard-library `unittest` runner, with tests that are also
pytest-discoverable, to verify deterministic metrics, absent and unavailable
evidence, archived repositories, context-sensitive security policy, differing
prototype and critical-production outcomes, traceability, and repeatability.

## Risks

* The slice could accidentally imply durability; documentation and names must
  keep persistence outside this task.
* Generated identifiers could vary across runs; all identifiers must derive
  from canonical inputs and caller-supplied evaluation time.
* Missing facts could be treated as favorable defaults; unavailable inputs
  must produce unavailable metrics and non-passing findings.
* Initial rules are demonstration policy, not validated customer policy.

## Rollback Plan

Remove the new slice modules, tests, Day 3 plan and journal, and revert the
small README status update. No data or infrastructure migration is involved.

## Implementation Checklist

* Confirm the four evidence kinds and two assessment contexts.
* Add immutable typed records with outcome-specific validation.
* Add deterministic metric calculations and version identifiers.
* Add versioned context-specific policy requirements and traceability.
* Add and run focused tests.
* Review the implementation for boundary violations and unnecessary
  complexity.
* Update README and Day 3 journal only after verification succeeds.
