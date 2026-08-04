# Day 7 Persistence Direction Review Plan

## Task

Record the approved persistence architecture connecting a valid Day 5 request
and terminal Day 6 repository-metadata collection outcome to durable storage
and, where applicable, one verified existing `EvidenceRecord`.

This is a read-only architecture outcome. Day 7 adds documentation only and
does not implement persistence.

## Objective

Define the smallest concrete durable boundary for the repository-archived
slice while preserving the existing Day 3 through Day 6 contracts and the
fail-closed rule that raw evidence must be durable before deterministic
evaluation may use it.

The approved direction uses Python's standard-library `sqlite3` module with a
caller-supplied on-disk database path. It keeps the complete successful GitHub
response separate from the compact canonical snapshot required by the current
`EvidenceRecord`, commits all linked collection records atomically, and
returns authoritative evidence only after closing, reopening, reading, and
verifying the database.

## Current State

Day 5 provides a pure transient request boundary:

```text
AssessmentRequestInput
    -> validate_assessment_request
    -> AssessmentRequestValidationResult
    -> AssessmentContext when valid
```

The validation result preserves the exact eleven-field submitted request and
produces the canonical repository identity
`github.com/<owner>/<repository>`. It does not persist an authoritative
assessment request.

Day 6 provides one transient collection boundary for:

```text
GET https://api.github.com/repos/<owner>/<repository>
```

An available result preserves the exact UTF-8 response text, its SHA256
digest, the GitHub repository ID, strict archived Boolean, source identity,
collector version, attempt metadata, status, and sanitized ETag. Unavailable
and failed outcomes contain no partial evidence. No result is durable.

Day 3 `EvidenceRecord` supports complete `available` and `unavailable`
outcomes. For available local evidence it requires a compact canonical JSON
snapshot shaped as exactly one `value` field and verifies that the normalized
value and compact-snapshot digest agree. Day 3 does not accept the full GitHub
repository response as this compact snapshot. Its outcome enum also does not
represent Day 6 retryable or nonretryable failures.

Day 3 metric and policy evaluation and Day 4 assessment assembly accept
caller-supplied `EvidenceRecord` values but have no way to prove that their raw
inputs were stored first. Therefore a Day 6 result must not enter evaluation
until a persistence boundary has committed and independently verified the
required durable records.

The repository currently has no schema, database module, migration, ORM,
repository abstraction, workflow engine, audit event implementation, or
durability test. All 88 existing tests pass at the Day 6 commit.

## Proposed Solution

### Storage decision

Use a concrete SQLite database through the Python standard library. The path
is supplied by the caller and must identify an on-disk database; `:memory:` and
URI memory databases are not durable and are not supported by the persistence
boundary.

Every connection enables foreign-key enforcement. The future implementation
will use explicit transactions for linked writes and a versioned SQLite schema.
The exact journal mode and concurrency tuning remain implementation details to
be justified by tests; Day 7 does not select WAL, pooling, or a long-lived
connection manager.

SQLite is the prototype durable store. This decision does not select a
production database or supersede future evaluation of PostgreSQL.

### Rejected file-based alternatives

* A single JSON document cannot provide safe linked-record updates,
  referential constraints, or reliable conflicting-replay detection without
  rebuilding database behavior.
* Separate request, snapshot, and evidence files can make one rename atomic
  but cannot atomically commit the complete linked collection outcome.
* Append-only JSON Lines preserves a log but makes uniqueness, current
  completeness, relationships, and exact replay reconciliation application
  responsibilities.
* `shelve` and `dbm` do not provide the required multi-record transaction and
  relational integrity guarantees.

SQLite is smaller and more reliable than implementing those controls over
files, while remaining dependency-free and local.

### Separation of source and normalized snapshots

An available Day 6 result has two distinct durable representations:

1. The **full source snapshot** is the exact successful GitHub UTF-8 response
   stored separately as bytes with the existing Day 6 SHA256 digest.
2. The **compact normalized evidence snapshot** is canonical JSON containing
   exactly `{"value":false}` or `{"value":true}`, using the formatting
   required by the existing Day 3 `EvidenceRecord`, with its own required
   `EvidenceRecord.integrity_digest`.

The compact snapshot is not described as the complete GitHub response. The
normalized evidence row links to the separate source-snapshot record, and its
`EvidenceRecord.provenance` identifies at least that snapshot record and its
Day 6 digest. The GitHub repository source ID and safe ETag remain source
metadata rather than replacing either snapshot.

This design preserves the complete response without changing or weakening
`EvidenceRecord._validate_snapshot_consistency` or the Day 6 payload-binding
checks.

### Minimum durable records

#### Valid assessment request

Persist one immutable request row before collection begins. It contains:

* all eleven exact `AssessmentRequestInput` fields;
* the exact canonical repository identity from the valid result; and
* the existing `request_definition_version`.

The persistence operation accepts only an internally consistent valid
`AssessmentRequestValidationResult` and compares a reopened row field by field
with that result. It does not add a persisted `workflow_state`, a separate
persisted `validation_status`, or a request-content digest. The valid input
contract and exact field comparison are sufficient for this slice.

The caller-owned `assessment_id` is the durable request key. Replaying the same
identifier and exact fields resolves to the existing request. Reusing it with
different submitted or normalized content is a conflict and never overwrites
the stored request.

#### Collection attempt

Persist one row for every complete terminal Day 6 result, including available,
404 unavailable, retryable failure, and nonretryable failure. It contains:

* `collection_attempt_id`, assessment reference, evidence kind, and attempt
  number;
* exact aware `attempted_at` representation;
* canonical requested repository identity and source API identity;
* collector version and outcome;
* numeric response status when present;
* sanitized ETag or retry guidance only where the Day 6 contract permits it;
  and
* sanitized error category, retryability, and constant message when present.

No collection-result digest is added. Exact comparison of every stored field,
plus the existing source-snapshot digest for available content, is the replay
and integrity contract.

`collection_attempt_id` identifies one real source call. A new call requires a
new attempt ID and attempt number. Exact redelivery of one completed result is
an idempotent replay; different content under the same attempt identity is a
conflict.

#### Full GitHub source snapshot

An available collection stores exactly one full-response row linked one-to-one
with the collection attempt. It contains:

* a deterministic source-snapshot ID based on the collection attempt;
* exact UTF-8 response bytes;
* encoding and media type;
* the existing Day 6 SHA256 digest;
* GitHub repository source ID; and
* sanitized ETag when present.

No response body is stored for a 404 or failure because Day 6 intentionally
does not make those bodies part of its result.

#### Normalized evidence row

Available and 404 unavailable outcomes may create one normalized evidence row
linked one-to-one with the collection attempt.

An available row contains every field required to reconstruct the existing
`EvidenceRecord`, including its deterministic evidence ID, strict Boolean,
compact snapshot and digest, source-snapshot provenance, collector version,
attempt metadata, freshness information, and evidence schema version.

A 404 row reconstructs an `EvidenceOutcome.UNAVAILABLE` record with the safe
`repository_not_publicly_available` reason and category and with no value,
source snapshot, compact snapshot, or digest. It does not claim whether the
repository is nonexistent, private, renamed, or access-restricted.

Retryable and nonretryable failures persist only their collection-attempt row.
They create no source snapshot and no `EvidenceRecord` because the current Day
3 evidence outcome contract cannot represent them. Expanding that contract is
deferred.

### Request boundary

The valid request must become durable before the caller begins GitHub
collection:

```text
valid Day 5 result
    -> begin request transaction
    -> insert or accept exact replay
    -> commit
    -> close connection
    -> reopen database
    -> read and compare every stored request field
    -> caller may begin collection
```

The persistence module does not call the collector and does not hold a
database transaction open during network access.

A commit exception fails closed. The operation returns no durability success.
Day 7 defines no special commit-uncertainty recovery protocol. A later call
using the same exact request may inspect and accept already durable content as
an exact replay; conflicting or incomplete content remains an error.

### Evidence boundary

Evidence persistence first loads and verifies the owning request. The
collection assessment ID and exact canonical repository identity must match
that request.

For an available result, one transaction writes:

1. the collection-attempt row;
2. the full source-snapshot row; and
3. the normalized evidence row.

All three commit or all three roll back. For 404, the attempt and unavailable
evidence row commit atomically. For retryable and nonretryable failures, the
complete attempt row is the only write.

After a successful commit, the implementation closes the database connection,
opens a new connection, enables foreign keys, and reads the persisted outcome.
No `EvidenceRecord` is returned until verification succeeds.

### Read-after-write verification

Request verification requires:

* exactly one row for the assessment ID;
* exact equality for every submitted field, enum value, timestamp
  representation, normalized identity, and request-definition version; and
* reconstruction and successful validation of the Day 5 contracts.

Available evidence verification requires:

* exactly one attempt, source snapshot, and evidence row with correct foreign
  keys;
* exact stored attempt and source metadata;
* full stored bytes decoding strictly as UTF-8;
* SHA256 of those bytes equaling the stored and original Day 6 digest;
* reconstruction of the Day 6 available result so its existing strict payload,
  repository-binding, Boolean, source-ID, ETag, and digest invariants rerun;
* exact compact canonical JSON for the archived Boolean;
* SHA256 of the compact snapshot equaling the evidence integrity digest;
* reconstruction of the existing `EvidenceRecord`; and
* exact expected identifiers, versions, assessment ownership, attempt
  metadata, provenance, freshness fields, and normalized value.

Unavailable verification reconstructs both the Day 6 unavailable result and
the Day 3 unavailable `EvidenceRecord` and confirms that neither contains
partial evidence. Failure verification reconstructs the terminal Day 6
failure result and confirms that no snapshot or evidence row exists.

If reopening, reading, decoding, digest verification, reconstruction,
relationship validation, or exact comparison fails, no evidence is returned.
Already committed rows are not deleted or silently repaired. A later exact
replay may accept them only after complete verification succeeds.

### Failure and rollback behavior

* Input contract violations are caller or programmer errors and fail before a
  transaction begins.
* A database open, schema, request persistence, or request verification failure
  prevents collection from being authorized by this boundary.
* An attempt, snapshot, or evidence write failure rolls back its complete
  transaction and returns no evidence.
* A commit exception fails closed. No successful result is returned, even when
  the external durability outcome is unknown.
* A connection-reopening or read-after-write failure returns no evidence.
* A full-source or compact-snapshot digest mismatch is an F11-style evidence
  persistence integrity failure, not source unavailability.
* A stored normalization or repository binding mismatch fails closed and is
  never repaired by coercion or resnapshotting.
* Exact replay returns the existing fully verified result without duplicate
  rows.
* A reused request ID, attempt ID, or per-assessment attempt number with
  conflicting content fails closed and never overwrites history.
* Persistence exceptions expose only stable module-owned categories and safe
  messages. Raw SQLite messages, stored payloads, and paths are not copied into
  public errors.
* Failure to persist a GitHub failure remains a persistence failure; it is not
  relabeled as another GitHub outcome.

### Identifier decisions

* `assessment_id` remains caller supplied, stable, and unique. Persistence does
  not regenerate it.
* `collection_attempt_id` remains caller supplied and unique for each actual
  source call. Exact replay reuses it; a retry that performs another source call
  receives a new one.
* `attempt_number` remains positive and must not identify two different
  attempts for the same assessment and evidence kind.
* The source-snapshot ID is deterministically derived from assessment,
  evidence kind, and collection-attempt identity. It is not the content hash.
* `evidence_id` is deterministically derived from assessment, evidence kind,
  and collection-attempt identity. Therefore a new attempt receives a new
  evidence ID even when its bytes equal an earlier attempt.
* GitHub repository ID remains an external source identifier, not a platform
  record identifier.
* SQLite row IDs, if present, are private storage details and never domain
  identities.
* SHA256 values remain integrity digests rather than record identifiers.

### Versioning decisions

The minimum stored versions are:

* the Day 5 `request_definition_version`;
* the Day 6 `collector_version`;
* the normalized evidence schema version used by `EvidenceRecord`;
* one repository-archived normalization version controlling compact-snapshot
  construction and provenance; and
* the SQLite schema version, represented by `PRAGMA user_version`.

The exact source-response interpretation is already bound to the collector
version. A separate request digest, collection-result digest, generic provider
version, workflow version, audit version, or persistence implementation
version is not required for this slice.

### Narrow Day 8 implementation scope

Day 8 implementation creates only:

1. one concrete `engineering_due_diligence.persistence` SQLite module; and
2. one focused SQLite persistence test module.

The source module will provide the smallest explicit operations needed to:

* persist and reopen-verify one complete valid Day 5 request before collection;
* persist every terminal Day 6 result;
* store the complete successful response separately;
* create the existing compact available or unavailable `EvidenceRecord` only
  for outcomes its current contract supports;
* close and reopen the database before returning evidence;
* accept exact request and collection replays idempotently; and
* reject conflicting replays without mutation.

The implementation remains specific to `EvidenceKind.REPOSITORY_ARCHIVED` and
uses direct parameterized `sqlite3` statements. It adds no public storage
protocol, repository object, unit-of-work abstraction, ORM model, migration
framework, or generic provider persistence layer.

### Day 8 acceptance direction

Focused tests must cover at least:

* a real caller-supplied on-disk path and successful close/reopen;
* complete request round-trip and exact replay;
* rejection of invalid request results and conflicting request replay;
* prevention of collection persistence when the request is missing or does
  not match;
* atomic available attempt, full snapshot, and evidence persistence;
* strict archived `False` and `True` preservation;
* exact full response bytes, existing digest, unrelated fields, GitHub source
  ID, and safe ETag after reopening;
* exact compact snapshot, compact digest, source-snapshot provenance, and
  reconstructed existing `EvidenceRecord`;
* atomic 404 attempt and unavailable evidence persistence;
* attempt-only persistence for retryable and nonretryable failures;
* rollback on each linked-write failure with no returned evidence;
* fail-closed commit, reopen, read, digest, normalization, and relationship
  failures;
* exact collection replay without duplicates and conflicting replay rejection;
* no live network access; and
* all existing 88 tests continuing to pass unchanged.

## Files Affected

Day 7 documentation changes are limited to:

* `plans/day_07_persistence_direction_review.md` — this approved direction;
* `docs/adr/0001_use_sqlite_for_prototype_persistence.md` — durable SQLite
  prototype decision;
* `journal/day_07.md` — chronological review record;
* `memory/DECISIONS.md` — concise durable decision; and
* `README.md` — Day 7 status and links.

No source, test, dependency, schema, data, or infrastructure file changes on
Day 7.

The later Day 8 implementation code scope is exactly:

* `src/engineering_due_diligence/persistence.py`; and
* `tests/test_sqlite_repository_archived_persistence.py`.

Day 8 planning and final documentation are separate process artifacts; they do
not expand the implementation code scope.

## Database Impact

Day 7 has no database impact. It creates no database file, schema, migration,
seed data, stored record, or persistence code.

The documented Day 8 direction will create a versioned SQLite schema inside
the one concrete persistence module and will exercise only temporary on-disk
databases in tests. Production migrations and deployment remain deferred.

## Testing Strategy

Day 7 changes documentation only. Verify that all 88 existing tests still pass,
Python sources and tests compile, whitespace checks pass, and the diff contains
only the approved documentation files.

Run:

```text
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
git diff --check
git diff --stat
git status --short
```

No live network request or database operation is part of Day 7 verification.

## Risks

* SQLite with normal durable settings substantially improves local prototype
  durability but cannot guarantee survival of every storage-device, operating
  system, or filesystem failure.
* SQLite is not a production database commitment. Treating it as one would
  overclaim deployment, concurrency, backup, encryption, and operational
  readiness.
* The existing `EvidenceRecord.raw_snapshot` name can be misunderstood as the
  full source response. Documentation and provenance must keep the compact
  normalized snapshot distinct from the separately stored full response.
* Day 6 has no response-size limit. The public repository metadata endpoint is
  bounded in normal use, but size enforcement remains unresolved.
* Retryable and nonretryable attempts cannot become current Day 3 evidence
  without expanding `EvidenceOutcome`. Day 8 must persist their attempt facts
  and stop there.
* Day 8 will store validated request and terminal attempt facts without a
  workflow engine or audit history. It must not claim complete workflow or
  audit capability.
* File permissions, retention, backup, encryption, access control, concurrency
  tuning, and PostgreSQL migration remain unresolved before production use.

## Rollback Plan

Revert the Day 7 documentation commit. No database, code, data, dependency,
schema, or external state exists to migrate or remove.

The future Day 8 implementation can be rolled back by removing its one source
module and one focused test module before any production or shared durable data
exists.

## Explicitly Deferred

Day 7 and the documented Day 8 slice do not implement or design:

* workflow engines, transition history, retries, backoff, scheduling,
  resumability, interruption recovery, or current-evidence selection;
* audit events, audit persistence, observability, telemetry, or logging
  infrastructure;
* FastAPI, Pydantic, APIs, CLIs, user interfaces, or serialization contracts;
* ORMs, repository patterns, storage ports, provider abstractions, dependency
  injection, or migration frameworks;
* license, latest-commit, security-policy, or other collectors;
* evaluator or Day 4 application-service integration;
* metric, policy-finding, report, human-decision, or final-assessment
  persistence;
* automated retries or recollection;
* PostgreSQL implementation, production deployment, connection pooling,
  concurrency optimization, backup, encryption, or access control;
* report generation, model integration, grounding validation, or human review;
  or
* private GitHub, authentication, GitLab, or other providers.

## Implementation Checklist

* Confirm the Day 6 commit and clean working tree.
* Read the domain, failure, request, collector, evidence, evaluation, and test
  contracts.
* Compare SQLite with file-backed alternatives.
* Resolve request-before-collection ordering and transaction boundaries.
* Resolve full-source versus compact-evidence snapshot storage.
* Define read-after-reopen authority and fail-closed behavior.
* Apply the approved corrections concerning status fields, extra digests, and
  commit exceptions.
* Record the decision in the plan, ADR, journal, memory, and README only.
* Run the complete verification suite and review every changed file.
* Commit and push only the approved Day 7 documentation.
* Do not begin Day 8 implementation.
