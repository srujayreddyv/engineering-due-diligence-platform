# Day 18 Deterministic Review Report Plan

## Task

Add a deterministic Markdown format to the existing read-only `review` command
without changing its verified loading boundary or backward-compatible JSON
contract.

## Objective

A technical reviewer can request a readable `assessment-review-report.v1`
document representing the exact same reopen-verified request, evidence,
evaluation snapshot, and optional human decision as the existing JSON review.
The renderer is transient, deterministic, network-free, clock-free, write-free,
and contains no recommendation or new business interpretation.

## Current State

`review` accepts a database path and assessment ID, loads one verified review
tuple through a single read-only SQLite transaction, and emits
`assessment-review-cli-output.v1` JSON. That tuple contains the valid persisted
request and context, four canonical authoritative evidence records, the exact
durable `AssessmentEvaluationSnapshot`, and an optional verified immutable
`HumanDecision`. JSON serialization already exposes the complete machine-
readable review state while omitting raw GitHub response bodies.

## Proposed Solution

Add `--format {json,markdown}` to `review`, defaulting to `json`. Preserve the
existing JSON construction and byte serialization unchanged. For Markdown,
pass the one already-loaded verified review tuple to a small renderer in
`cli.py` and write its deterministic text directly to stdout.

The renderer will emit the locked sections in order, preserve canonical record
ordering, derive policy counts and required approval acknowledgments only from
the verified durable findings, and escape record text for safe Markdown
presentation. It will expose exact values, statuses, reasons, conditions, and
provenance without recalculation, current time, source-body content, scores,
recommendations, or inferred risk judgments. Known failures remain the existing
versioned sanitized JSON errors.

## Files Affected

* `src/engineering_due_diligence/cli.py`: review format parsing, deterministic
  Markdown rendering, and text output selection.
* `tests/test_deterministic_review_report.py`: focused Markdown, compatibility,
  authority-boundary, determinism, decision, unavailable-input, and
  sanitization tests.
* `README.md`: implemented Markdown review usage and exact limitations.
* `memory/CODEBASE.md`, `memory/ARCHITECTURE.md`, and `memory/PATTERNS.md`:
  durable current-state and deterministic presentation guidance.
* `journal/day_18.md`: completed work, verification, and exclusions.

## Database Impact

None. There is no schema, migration, durable report, write path, or additional
database read. Markdown is rendered transiently from the existing verified
review tuple after the one read-only transaction completes.

## Testing Strategy

Add focused tests for default and explicit JSON identity, complete ordered
Markdown sections, report version, canonical evidence/metric/finding order,
exact policy counts and required acknowledgments, no-decision and recorded-
decision rendering, conditional approval, needs-more-information finality,
unavailable evidence semantics and affected records, policy versus human
conditions, technical provenance, source-body omission, no network/write/clock
activity, corruption failure through existing verification, and byte-identical
repeated rendering. Run the focused module, complete suite, compileall, and
`git diff --check`.

## Risks

* Markdown metacharacters or line breaks in durable human text could distort
  structure; escape every dynamic value through one deterministic helper.
* Presentation filters could accidentally omit a supported domain outcome;
  count every `PolicyOutcome` and render all findings in stored order.
* A second load or recalculation could diverge from the reviewed artifact;
  render only the existing loaded records and snapshot.
* Format selection could change current clients; keep JSON as the default and
  leave its object and serializer unchanged.

## Rollback Plan

Before release, revert the additive format argument, renderer, focused tests,
and Day 18 documentation. Existing schema-v5 databases and all assessment,
evidence, evaluation, and decision records remain unchanged.

## Implementation Checklist

* Add the additive review format argument and deterministic renderer.
* Preserve one verified loading path and unchanged JSON behavior.
* Add focused Day 18 tests for the required presentation and invariants.
* Run focused and complete verification.
* Review the full diff for scope, determinism, safety, and documentation.
* Update the Day 18 journal and only durable current-state memory.
