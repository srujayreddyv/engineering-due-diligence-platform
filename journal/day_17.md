# Day 17 Journal

## Work Completed

Implemented the smallest noninteractive customer flow over the locked Day 15
and Day 16 human-decision boundary:

```text
assess -> review -> decide
```

The new `review` command accepts only a caller-supplied database path and
assessment ID. One read-only, query-only SQLite transaction reconstructs and
verifies the persisted request, complete four-kind authoritative evidence set,
exact `AssessmentEvaluationSnapshot`, and optional immutable `HumanDecision`.
The versioned `assessment-review-cli-output.v1` document exposes assessment
context, canonical evidence summaries and references, all four exact metrics,
all four exact policy findings, evaluation identity and integrity fields, the
ordered non-`PASS` acknowledgments required for approval, and the actual
verified decision when present.

Review performs no GitHub request, database write, clock read, new evaluation,
or durable artifact creation. Deterministic evaluation runs only through the
existing reopen-verification boundary at the stored `evaluated_at`. Complete
GitHub response bodies remain private to SQLite, and the CLI creates no overall
recommendation.

The new `decide` command maps its assessment, evaluation, asserted reviewer,
disposition, rationale, ordered conditions, ordered information requests, and
ordered acknowledgment arguments directly to the existing human-decision
persistence contract. It first reloads and verifies the durable evaluation and
requires exact assessment/evaluation identity binding. Persistence remains the
authority for reviewer equality, disposition shape, acknowledgments,
timestamps, immutability, and replay.

## Replay Result Adjustment

The existing `persist_human_decision` API remains backward compatible and
continues to return `HumanDecision`. Its implementation now delegates to one
private transaction helper that also knows whether it inserted the row or
resolved an exact replay. A sibling CLI-facing persistence call returns the
same authoritative decision plus `recorded` or `exact_replay` from that
transaction. No read-before-write inference and no new durable field were
added.

Exact replay returns the original decision ID and `recorded_at`, reads no new
decision clock, and changes no database content. Changed normalized business
content fails with exit code 6 and no mutation.

## Output and Failure Boundary

Decision success uses `human-decision-cli-output.v1` and includes every durable
decision field plus an explicit `caller_asserted_not_authenticated` identity
statement. Review and decision usage, validation, persistence, verification,
conflict, and unexpected failures use versioned deterministic JSON. They do not
expose database paths, SQL, SQLite details, tracebacks, source bodies,
transport exceptions, or internal exception text.

The existing `assess` command and `assessment-cli-output.v1` contract remain
unchanged. Review and decide add no interactive prompts, report, AI,
authentication, authorization, decision editing, decision history, condition
tracking, workflow state, retry, resume, reassessment, HTTP API, web UI, audit
events, schema migration, or new durable persistence concept.

## Verification

Thirteen focused Day 17 tests cover complete review output and canonical order,
no-decision and existing-decision states, no network/write/clock behavior,
missing evaluation content, corruption, all four dispositions, argument order,
acknowledgments, reviewer and evaluation binding, exact replay, conflict,
pre-write evaluation verification, and safe failures. The focused Day 17 plus
unchanged Day 14 and Day 16 CLI/decision tests pass together as 35 tests.

The complete suite passes 269 tests. Compilation of `src` and `tests` passes
with a workspace-safe bytecode cache, and `git diff --check` passes.
