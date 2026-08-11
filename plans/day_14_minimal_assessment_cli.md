# Day 14 Minimal Assessment CLI Plan

## Task

Add one dependency-free command-line boundary over the corrected one-shot
assessment workflow. The command accepts one public GitHub assessment request
and returns one versioned machine-readable terminal result.

## Objective

Allow a local user or script to run exactly one assessment and distinguish
usage errors, request validation, collection failure, persistence failure, and
a complete deterministic result through stable JSON and exit codes. Complete
output includes the validated context, four authoritative evidence summaries,
four metrics, four policy findings, and an explicit statement that no human
decision exists.

## Current State

The repository provides strict request validation, four public GitHub
collectors, schema-v4 SQLite persistence, read-only durable evidence loading,
deterministic evaluation, and one-shot execution. The uncommitted Day 14
timestamp correction removes caller-owned `evaluated_at`; the workflow now
captures that timestamp after all four evidence kinds are durable. There is no
customer-facing process boundary, package metadata, or third-party runtime
dependency.

## Proposed Solution

Create `engineering_due_diligence.cli` with an `assess` command implemented
using `argparse`. The CLI accepts only submitted business context and a
caller-supplied on-disk database path. Private patchable seams generate an
`assessment-<lowercase UUID4>` identifier plus separate aware UTC
`submitted_at` and `collection_attempted_at` values. The corrected workflow
remains the sole owner of `evaluated_at`.

Construct the existing request and execution inputs, call
`execute_assessment` once, and explicitly serialize the returned contracts.
The versioned `assessment-cli-output.v1` envelope has stable nullable fields
and arrays for every terminal shape. Evidence serialization includes typed
values, identity, collection metadata, freshness, versions, digests, and
ordered provenance key/value entries, but never includes compact raw snapshots
or complete GitHub source responses. Metrics and findings are serialized
without aggregation, and `human_decision.status` is always
`not_implemented`.

Known domain and persistence outcomes produce JSON on standard output.
Usage/syntax and unexpected internal failures produce one sanitized JSON
document on standard error. Exit codes are 0 complete, 1 internal failure, 2
usage error, 3 invalid request, 4 collection failure, and 5 persistence or
verification failure.

## Files Affected

* `plans/day_14_minimal_assessment_cli.md` locks the interface and verification
  scope.
* `src/engineering_due_diligence/cli.py` adds the command parser, private
  generated-value seams, explicit serializers, safe failure mapping, and module
  entry point.
* `tests/test_assessment_cli.py` proves the process-facing contract with real
  temporary SQLite files and patched GitHub transport.
* `src/engineering_due_diligence/workflow.py` and
  `tests/test_one_shot_assessment_execution.py` retain the already reviewed
  uncommitted timestamp correction without additional scope.

No other production, test, documentation, memory, journal, or ADR file changes
are planned.

## Database Impact

There is no schema, migration, or persistence behavior change. The CLI supplies
the caller's path to the existing boundary. SQLite remains exact schema version
4, and complete source responses remain durable only in SQLite.

## Testing Strategy

Focused tests cover command parsing, generated UUID and timestamps, one call to
the workflow, complete canonical evidence/metric/finding output, explicit
absence of a human decision and aggregate recommendation, source-body
exclusion, ordered provenance, invalid-request short circuiting, collection
failure without partial results, sanitized persistence failure, safe usage and
unexpected-failure JSON, stable exit codes, schema version 4, standard streams,
and patched-only GitHub access.

Run the focused CLI and workflow tests, the complete suite, compilation,
`git diff --check`, diff-stat inspection, complete Day 14 diff review, and Git
status inspection.

## Acceptance Criteria

* One `assess` invocation submits exactly one existing request contract.
* IDs and pre-workflow timestamps are generated privately and cannot be
  overridden through command flags.
* `execute_assessment` is called exactly once.
* Complete JSON contains four canonical evidence records, four metrics, four
  findings, and the exact workflow-captured evaluation timestamp.
* No overall approve or reject recommendation is created.
* Full GitHub source responses and unsafe exception content are never emitted.
* Expected outcomes and exit codes are stable and machine-readable.
* SQLite remains schema version 4 and all tests pass.

## Risks

The command is synchronous and may wait for bounded GitHub requests. Actor IDs
are submitted labels rather than authenticated identities. A failure after
earlier collectors succeed can leave verified partial durable history, but the
CLI intentionally adds no retry or resume. Metrics and findings remain
transient, so reproduction requires the emitted evaluation timestamp. The
caller is responsible for protecting and operating the SQLite file.

## Rollback Plan

Remove the CLI module, focused tests, and this plan. The timestamp correction
can be reviewed or reverted independently. No database or stored-data rollback
is required.

## Explicit Exclusions

No retry, resume, reassessment, report generation, LLM behavior, human decision
recording, audit history, web server, authentication, packaging metadata,
deployment infrastructure, new persistence behavior, schema change, workflow
state, or overall adoption recommendation is added.

## Implementation Checklist

* Lock the exact command, output envelope, and exit codes.
* Add private UUID and UTC clock seams.
* Construct only the existing request and corrected workflow inputs.
* Serialize every terminal shape explicitly and safely.
* Add focused real-file and patched-transport tests.
* Run complete verification and review the full Day 14 diff.
