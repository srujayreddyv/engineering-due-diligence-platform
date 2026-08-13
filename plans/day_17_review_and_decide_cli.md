# Day 17 Review and Decide CLI Plan

## Task

Expose the existing durable assessment-evaluation snapshot and immutable human-
decision capabilities through a narrow noninteractive `review` and `decide`
command-line flow.

## Objective

A responsible reviewer can load one existing assessment by identifier, inspect
the complete reopen-verified deterministic evaluation without network or write
activity, and record or exactly replay one immutable human decision. Success is
recognized by versioned machine-readable output, preserved Day 15 and Day 16
invariants, stable sanitized failures, and passing focused and complete tests.

## Current State

The `assess` command creates a validated request, authoritative four-kind
evidence set, deterministic result, and one durable
`AssessmentEvaluationSnapshot`. SQLite schema version 5 can also persist and
reopen-verify at most one immutable `HumanDecision`, but no customer-facing
read or decision command exposes those library capabilities.

The persistence module already owns strict schema, request, evidence, snapshot,
decision, integrity, binding, deterministic reconstruction, and replay
verification. The CLI must compose those authority boundaries rather than
reimplement their rules. The current human-decision persistence call returns
the authoritative decision but does not expose whether the same transaction
inserted it or resolved an exact replay.

## Proposed Solution

Add a `review` parser branch that accepts only a database path and assessment
ID. A narrow read-only persistence composition will use one SQLite read
transaction to reconstruct the valid request, exact four authoritative evidence
records, verified evaluation snapshot, and optional verified decision. The CLI
will serialize those existing contracts in canonical order, include the ordered
non-`PASS` finding IDs required for approval, omit raw source bodies, and make
no recommendation.

Add a `decide` parser branch whose arguments map directly to the existing human-
decision business fields. It will first load and reopen-verify the referenced
assessment evaluation, require exact assessment/evaluation binding, and then
invoke the existing persistence validation and write boundary. Invalid decision
content remains owned by persistence.

Preserve `persist_human_decision` as a backward-compatible decision-returning
API. Refactor its implementation behind a private helper that also returns the
transaction's replay fact, and expose one sibling call returning the decision
plus stable `recorded` or `exact_replay` status. No status is persisted.

Review and decision commands will use separate versioned output envelopes and
the existing stable exit-code meanings, adding code 6 only for a conflicting
immutable decision. Known persistence failures remain sanitized; unexpected
failures return constant command-specific JSON without exception detail.

## Files Affected

* `src/engineering_due_diligence/persistence.py`: one-transaction verified
  review loading and authoritative decision replay-status return.
* `src/engineering_due_diligence/cli.py`: `review` and `decide` parsing,
  serialization, dispatch, and sanitized output.
* `tests/test_review_and_decide_cli.py`: focused Day 17 customer-boundary tests.
* `README.md`: implemented `assess -> review -> decide` usage and limitations.
* `memory/CODEBASE.md`, `memory/ARCHITECTURE.md`, and `memory/PATTERNS.md`:
  durable current-state and CLI-pattern updates.
* `journal/day_17.md`: completed work, verification, and exclusions.

## Database Impact

There is no schema, migration, or new durable-record change. Review opens the
existing exact schema-v5 database read-only and query-only. Decision recording
uses the existing `human_decisions` row and preserves its immutable exact replay
behavior. Replay status is transient operation output only.

## Testing Strategy

Add focused real-file SQLite CLI tests for complete review output and ordering,
no-decision and existing-decision states, absence of network/write/clock
activity, missing and incomplete assessments, evaluation and decision
corruption, all four dispositions, repeated argument order, acknowledgments,
reviewer and evaluation binding, exact replay identity/time preservation,
conflicting replay, pre-write evaluation verification, and sanitized errors.

Run the existing Day 14 and Day 16 tests, the complete unittest suite,
`compileall` using a workspace-safe bytecode cache, and `git diff --check`.
Review the final diff for unchanged schema, direct use of authority boundaries,
source-body exclusion, compatibility, and scope exclusions.

## Risks

* A review assembled through separate database reads could mix durable states;
  the new persistence read composition therefore uses one transaction.
* Automatically deriving approval acknowledgments would weaken explicit human
  acknowledgment; the review displays required IDs, while the caller must pass
  them to `decide` in exact order.
* A CLI read-before-write cannot safely infer replay status; the persistence
  transaction must return that fact.
* Error output must never include paths, SQL, source bodies, or exception text.
* Existing `assess` output remains compatible and continues to perform only the
  assessment operation.

## Rollback Plan

Before release, revert the Day 17 CLI, read composition, replay-status wrapper,
tests, and documentation. Existing schema-v5 databases and all Day 16 durable
records remain valid because Day 17 adds no schema or stored fields.

## Implementation Checklist

* Add one-transaction read-only review loading.
* Add authoritative transient decision replay status without breaking the
  existing persistence API.
* Add versioned `review` and `decide` JSON commands and stable failures.
* Add focused tests for the complete requested behavior.
* Run focused and complete verification.
* Review scope and update only implemented-state documentation.
