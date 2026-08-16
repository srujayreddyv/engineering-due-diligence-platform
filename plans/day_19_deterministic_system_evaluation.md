# Day 19 Deterministic System Evaluation Plan

## Task

Add a reproducible, network-free system evaluation harness for ten frozen
repository-adoption scenarios without changing production behavior or policy.

## Objective

Demonstrate implementation conformance across the complete customer workflow:
real CLI parsing, GitHub-shaped collection, durable evidence, deterministic
evaluation, reopen-verified JSON and Markdown review, selected immutable human
decisions, replay behavior, and fail-closed error handling. A successful run
emits one deterministic versioned JSON summary and exits zero only when all ten
declared scenarios conform.

## Current State

The schema-v5 product implements `assess`, read-only reopen-verified `review`
in JSON and deterministic Markdown, and immutable `decide`. Existing unit and
integration tests cover the individual contracts. There is no system-level,
portfolio-readable evaluation that compares the complete workflow against a
small frozen scenario matrix. Production policy is provisional and must not be
tuned by this work.

## Proposed Solution

Keep evaluation code under `scripts/`. One module declares exactly ten frozen
scenarios and their expected evidence, metric, policy, decision, and terminal
behavior. A second module runs those scenarios through `cli.main`, patches only
the existing transport, identifier, and clock seams, uses fresh temporary
schema-v5 databases, checks reopened durable state and customer-visible output,
and emits `deterministic-system-evaluation-output.v1` JSON.

Successful scenarios enter through the real GitHub transport/collector path.
Each is repeated from a fresh database with the same frozen inputs so review
JSON and Markdown—and decision output when applicable—can be compared byte for
byte. E06 and E07 reuse byte-identical source responses and evaluation time but
change only risk tolerance. E09 verifies partial durable collection followed by
a rate-limit failure. E10 uses the existing narrow SQLite corruption technique
to prove review and decision fail closed.

## Files Affected

* `scripts/deterministic_evaluation_scenarios.py`: frozen scenario contracts,
  facts, contexts, expected results, and decision exercises.
* `scripts/run_deterministic_evaluation.py`: real-workflow executor,
  conformance checks, reproducibility checks, and deterministic summary.
* `tests/test_deterministic_evaluation_runner.py`: narrow trust tests for
  ordering, summary schema, aggregation, deterministic bytes, and exit status.
* `docs/deterministic_system_evaluation.md`: human-facing observed Day 19
  evaluation result and limitations, written only after the harness passes.
* `README.md`: execution instructions and the distinction between frozen
  conformance evaluation and later live-repository demonstrations.
* `memory/CODEBASE.md`, `memory/ARCHITECTURE.md`, and `memory/PATTERNS.md`:
  durable repository structure and evaluation-boundary guidance.
* `journal/day_19.md`: completed work and verification.

## Database Impact

None. The harness creates disposable temporary schema-v5 databases through the
existing production migrations. It adds no table, migration, seed data,
fixture persistence, or production data-access behavior.

## Testing Strategy

Add focused standard-library tests for the frozen scenario ordering, summary
contract, failed-scenario aggregation, byte-deterministic summary rendering,
and runner exit behavior. Run those tests, the harness itself, the complete
existing suite, compileall, and `git diff --check`.

The runner owns the ten system-level scenario assertions; the unit test module
will not duplicate them.

## Risks

* Reimplementing product logic in expectations could make the harness
  self-confirming; keep policy outcomes and reason codes declarative and call
  only production workflow functions for behavior.
* Hidden time, identifier, temporary-path, dictionary-order, or network inputs
  could break reproducibility; freeze only existing seams and serialize with
  sorted compact JSON.
* Failure scenarios could leak internal SQLite or transport details; assert the
  existing sanitized CLI contracts and exclude command stderr details from the
  summary.
* Engineered scenarios could be mistaken for policy validation; documentation
  must state that this is conformance evaluation, not statistical accuracy,
  commercial policy validation, or customer ROI evidence.

## Rollback Plan

Remove the two scripts, their narrow test module, and Day 19 documentation.
Production runtime and schema remain unchanged.

## Implementation Checklist

* Add the locked ten declarative scenarios.
* Execute the real CLI and collector path with frozen seams.
* Verify successful, context-sensitive, unavailable, failure, decision, and
  replay behavior.
* Add the deterministic summary and narrow runner tests.
* Run the harness and all repository verification.
* Publish only truthful observed results in docs and durable memory.
