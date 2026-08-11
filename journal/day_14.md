# Day 14 Journal

## Work Completed

Implemented one dependency-free customer-facing command over the existing
one-shot workflow:

```text
PYTHONPATH=src python3 -m engineering_due_diligence.cli assess \
  --database <path> \
  --repository <github-url> \
  --intended-use <text> \
  --environment <value> \
  --criticality <value> \
  --expected-lifetime-days <integer> \
  --risk-tolerance <value> \
  --submitted-by-actor-id <id> \
  --responsible-reviewer-actor-id <id>
```

All nine inputs are required and exactly one assessment runs per invocation.
The CLI creates the existing `AssessmentRequestInput` and corrected
`AssessmentExecutionInput`, calls `execute_assessment` once, and serializes the
returned contracts without reimplementing request validation, collection,
persistence, deterministic evaluation, or policy behavior.

## Timestamp Ownership

The CLI privately generates an `assessment-<lowercase UUID4>` identifier plus
separate aware UTC `submitted_at` and `collection_attempted_at` values through
patchable UUID and clock seams. These generated values cannot be overridden by
command options.

`AssessmentExecutionInput` no longer accepts caller-owned `evaluated_at`. The
workflow calls its private evaluation clock exactly once after all four
authoritative evidence records have been persisted and reopen-verified. It
passes that exact aware value unchanged to durable assessment evaluation. No
evaluation time is captured for invalid requests, collection failures,
persistence failures before evaluation, or conflicting replay.

This corrects the race where a commit created during collection could be later
than a caller-selected evaluation time. A naive or backward clock still fails
closed through existing temporal validation. Exact durable evidence replay
remains idempotent, while identical evidence may be reevaluated later without
changing SQLite and may yield different transient metric or finding identities.

## Output Contract

Every structured response uses the version
`assessment-cli-output.v1`. A complete response contains the assessment and
validated context, the exact generated and workflow-captured timestamps, four
evidence summaries in canonical evaluator order, four deterministic metric
results, and four policy findings.

Evidence summaries preserve provenance order as arrays of key/value entries.
They do not include compact raw snapshots or complete GitHub source response
bodies. The CLI does not invent an aggregate approve or reject recommendation,
and every output explicitly reports:

```json
{"human_decision":{"status":"not_implemented"}}
```

## Exit Codes and Failure Safety

The stable exit-code contract is:

```text
0 complete assessment
1 unexpected internal failure
2 CLI usage or syntax error
3 assessment validation failure
4 collection failure
5 persistence or durable verification failure
```

Invalid requests return structured validation data without database or network
activity. Collection failure returns its sanitized terminal failure and no
partial evidence, metrics, or findings. Persistence failures expose only the
existing stable category and constant safe message. Unexpected failures,
including output serialization failures, return only the constant internal
error document. No traceback, exception text, SQL, database path, credentials,
authorization data, transport detail, HTTP error body, or complete successful
GitHub response is emitted.

## Review Findings

The complete Day 14 review confirmed the command surface, required inputs,
generated-value ownership, workflow evaluation-time ownership, canonical
output ordering, source-body exclusion, provenance ordering, exit codes,
failure sanitization, exact replay, later transient reevaluation, and unchanged
schema. The implementation review corrected one material output-boundary issue:
JSON serialization is completed before one stream write and serialization
failures are converted to the same constant sanitized internal-error response.
No further material issue was found during final review.

## Verification

Eight focused CLI tests cover complete output, canonical evidence and derived
results, generated values, raw-source exclusion, invalid input, collection and
persistence failures, usage errors, unexpected execution and serialization
failures, schema stability, and patched-only GitHub access. The corrected
workflow tests cover post-collection evaluation-time capture, temporal failure,
exact replay, later reevaluation, and changed-source conflict behavior.

The complete suite passes:

```text
Ran 242 tests
OK
```

The 234 pre-CLI tests also pass independently. Compilation, whitespace checks,
and a manual usage-error invocation pass. The manual invocation exits with code
2, emits safe versioned JSON, contains no traceback, and creates no database.

## Schema, Risks, and Explicit Exclusions

SQLite remains exact schema version 4. The command is synchronous and one shot.
A mid-sequence collection failure can leave earlier verified evidence durable,
but there is no retry, resume, reassessment, or current-evidence selection.
Metrics and policy findings remain transient. Actor IDs are caller-supplied
labels rather than authenticated identities, and the caller remains responsible
for protecting the SQLite file.

Day 14 adds no HTTP API, web interface, authentication, packaging metadata,
deployment infrastructure, report generation, LLM behavior, human-decision
persistence, audit history, new collector, persistence behavior, schema change,
ORM, repository abstraction, or provider abstraction.

## Next Task

Day 15 should begin with a read-only direction review for the smallest human
review and decision workflow. It should build on the existing assessment JSON
and durable evidence without returning to collection or persistence foundation
work, and it must preserve the rule that the platform does not automatically
approve or reject technology adoption.
