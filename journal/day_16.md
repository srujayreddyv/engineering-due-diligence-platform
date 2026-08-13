# Day 16 Journal

## Work Completed

Implemented the locked Day 15 durable human-review boundary without adding CLI
behavior or expanding the product workflow.

Added frozen `AssessmentEvaluationSnapshot`, `HumanDecisionDisposition`, and
`HumanDecision` contracts. The evaluation serializer preserves the complete
ordered assessment-level deterministic result in canonical UTF-8 JSON. Its
generated evaluation ID and integrity digest are envelope values and never
occur in their own payload. Human-decision identity uses the first internally
captured UTC recording time and excludes its generated ID.

SQLite now uses exact schema version 5. The v4-to-v5 migration adds only
`assessment_evaluation_snapshots` and `human_decisions`, compares every existing
v4 row, validates exact schema and foreign keys, and changes `user_version` only
after the transaction verifies. Existing v4 assessments receive no fabricated
evaluation or decision rows.

Assessment evaluation persistence verifies the request and complete four-kind
evidence set, deterministically recalculates all four metrics and findings,
writes the exact canonical payload, and closes and reopens before returning the
snapshot as authoritative. Reads recalculate from durable evidence at the
stored exact time and compare the payload bytes, digest, identifier, versions,
order, references, and same-assessment closure.

The one-shot workflow now checks for an existing verified snapshot after exact
evidence replay and before reading its evaluation clock. A first evaluation
captures time once, evaluates, persists, and reopen-verifies. Exact replay uses
the original stored evaluation time and returns the original snapshot without
reading a later clock. Invalid requests and collection failures create no
snapshot.

The human-decision library validates all four dispositions, exact responsible-
reviewer actor-ID equality, nonempty rationale, ordered condition or information
request content, complete ordered non-`PASS` acknowledgments for approvals,
empty acknowledgments for rejection and needs-more-information, same-assessment
evaluation binding, and aware UTC recording time not before evaluation. At most
one immutable decision exists per assessment. Replay compares only the eight
normalized caller-supplied business fields and returns the original generated
ID and recording time; changed content conflicts without mutation.

## Verification

Focused snapshot, migration, workflow, and decision tests pass. The full suite
passes 256 tests. Source and test compilation passes with a workspace-safe
Python bytecode cache. `git diff --check` passes.

## Scope Review

No decide CLI, report generation, AI, authentication, authorization, decision
history, correction, condition tracking, workflow state, retry, resume,
reassessment, HTTP API, ORM, PostgreSQL, audit-event, or observability behavior
was added. README remains unchanged.

## Risks and Follow-Up Boundary

Canonical JSON and timestamp spelling are now durable byte contracts. Stored
snapshots and decisions remain authoritative only while their exact schema and
definition versions are supported and deterministic reconstruction succeeds.
The next customer-facing slice may expose the already verified decision library
through the separately designed `decide` CLI, but Day 16 does not begin that
work.
