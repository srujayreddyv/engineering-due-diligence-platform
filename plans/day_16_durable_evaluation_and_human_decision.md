# Day 16 Durable Evaluation and Human Decision Plan

## Task

Implement the locked Day 15 assessment-evaluation snapshot and immutable human-
decision boundary as a library-only SQLite schema-v5 slice.

## Objective

A completed deterministic assessment becomes authoritative only after its exact
canonical evaluation payload is persisted and verified after close and reopen.
The library can then record and reopen-verify at most one human decision for the
same assessment and reviewed evaluation, with exact replay and nonmutating
conflict behavior.

## Current State

The one-shot workflow persists a validated request and four authoritative
evidence records in schema version 4, captures one evaluation time, and returns
a transient deterministic result. Exact workflow replay currently captures a
later evaluation time. Metrics, policy findings, assessment-level evaluation
identity, and human decisions are not durable.

## Proposed Solution

Add the three frozen Day 15 contracts to the existing model and assessment
modules. Canonical evaluation and decision identity functions will serialize
only their documented payload fields using sorted-key compact UTF-8 JSON.

Extend the concrete SQLite module from exact schema v4 to exact schema v5 by
adding only `assessment_evaluation_snapshots` and `human_decisions`. The v4-to-
v5 migration creates empty tables in one transaction, compares all preexisting
rows, verifies exact schema and foreign keys, and advances `user_version` only
after validation.

Snapshot persistence will verify the complete request and evidence set,
recalculate the supplied deterministic result, write or replay one canonical
payload, and close/reopen before returning authority. Human-decision
persistence will load that verified evaluation, validate reviewer identity,
disposition-specific content, acknowledgments, and time, then apply the same
immutable replay and reopen-verification pattern.

After the four collectors complete, the workflow first looks for an existing
verified evaluation. Exact replay returns a deterministic result evaluated at
the stored original time without reading the clock. A first execution captures
the clock once, evaluates, persists, and reopen-verifies the snapshot before
returning complete.

## Files Affected

* `src/engineering_due_diligence/models.py`: human-decision contracts.
* `src/engineering_due_diligence/assessment.py`: evaluation-snapshot contract,
  canonical payload construction, and deterministic identities.
* `src/engineering_due_diligence/persistence.py`: schema v5, migration,
  snapshot persistence/loading, and human-decision persistence/loading.
* `src/engineering_due_diligence/workflow.py`: durable snapshot authority and
  original-time replay sequencing.
* Focused persistence and workflow tests plus existing schema assertions.
* Durable memory and `journal/day_16.md` after verification.

No CLI, README, report, AI, authentication, authorization, workflow-state, or
condition-lifecycle code will change.

## Database Impact

Exact schema version 5 adds two tables only. Existing schema-v4 rows are
preserved byte-for-byte at the SQL value level and no legacy evaluation rows
are fabricated. Unsupported or altered schemas continue to fail closed.

## Testing Strategy

Add focused real-file SQLite tests for exact migration and rollback, canonical
identity bytes, snapshot creation/reopen/corruption/replay/conflict, all four
decision shapes and invalid variants, same-assessment and reviewer binding,
temporal validation, decision reopen/corruption/replay/conflict, and workflow
creation/replay/failure sequencing. Update prior schema-version expectations,
then run the focused modules, full unittest suite, compileall, and
`git diff --check`.

## Risks

Canonical JSON is a permanent byte contract. Timestamp spelling and tuple order
must remain exact. Workflow replay must not read a new clock after an existing
snapshot is authoritative. JSON references are verified through deterministic
reconstruction rather than independent relational rows, so every read must
remain fail closed.

## Rollback Plan

Before deployment, revert the Day 16 source, tests, and documentation. Any
created schema-v5 database contains new durable business records and must not be
destructively downgraded; a separate data-preserving rollback decision would be
required.

## Implementation Checklist

* Add exact frozen contracts and serializers.
* Add and test strict schema-v5 creation and v4 migration.
* Add snapshot persistence, loading, reconstruction, and replay.
* Integrate first-evaluation and original-time workflow replay.
* Add decision validation, persistence, loading, and replay.
* Run focused and complete verification.
* Review scope, update durable memory, and record the Day 16 journal.
