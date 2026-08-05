# Day 8 SQLite Repository Archived Persistence Plan

## Task

Implement the smallest concrete SQLite persistence boundary that makes one
valid Day 5 request durable before collection and persists every terminal Day
6 repository-metadata collection result.

Available and 404 outcomes may produce one authoritative existing
`EvidenceRecord` only after the database is closed, reopened, and completely
verified. Other terminal failures persist only their collection-attempt facts.

## Objective

Create a dependency-free, on-disk durability boundary for
`EvidenceKind.REPOSITORY_ARCHIVED` using Python's standard-library `sqlite3`
module and a caller-supplied path.

Success means that complete linked writes are atomic, full GitHub response
bytes remain separate from the compact normalized evidence snapshot, exact
replays create no duplicates, conflicting replays never overwrite history,
and any write, commit, reopen, digest, normalization, relationship, or
verification failure returns no evidence and exposes only a sanitized
module-owned error.

## Current State

Day 5 returns a frozen transient `AssessmentRequestValidationResult`. A valid
result retains the exact eleven-field `AssessmentRequestInput`, canonical
`github.com/<owner>/<repository>` identity, and one `AssessmentContext`.
Nothing is durable.

Day 6 returns a frozen terminal collection result for one call to
`GET https://api.github.com/repos/<owner>/<repository>`. Available results
retain the exact UTF-8 response text, its SHA256 digest, repository source ID,
strict archived Boolean, response status, sanitized ETag, and collection
metadata. Nonavailable results contain no partial evidence. Nothing is
durable.

The existing Day 3 `EvidenceRecord` accepts available and unavailable outcomes.
For available repository-archived evidence it requires a strict Boolean and a
compact canonical JSON snapshot shaped exactly as `{"value":false}` or
`{"value":true}` with a matching SHA256 digest. It cannot use the complete
GitHub response as that compact snapshot, and it cannot represent Day 6
retryable or nonretryable failures.

The repository has no database module or schema. The approved Day 7 ADR selects
on-disk SQLite for this prototype and requires request-before-collection
ordering, atomic linked collection writes, and close-and-reopen verification.
The unchanged baseline contains 88 passing tests.

## Proposed Solution

### Public persistence contracts

Add exactly one public exception and two public functions in
`engineering_due_diligence.persistence`. Do not add package-root exports.

```python
class SQLitePersistenceError(Exception):
    category: str
```

The exception accepts only a locked category and always renders that
category's constant safe message. It never includes a SQLite message, database
path, stored payload, or caught exception text.

```python
def persist_valid_assessment_request(
    database_path: str | os.PathLike[str],
    validation_result: AssessmentRequestValidationResult,
) -> AssessmentRequestValidationResult:
```

The function requires an exact, internally consistent valid Day 5 result,
revalidates its submitted input through `validate_assessment_request`, stores
or accepts the request as an exact replay, commits, closes, reopens, verifies
every field, and returns the supplied result only after verification.

```python
def persist_github_repository_metadata_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Optional[EvidenceRecord]:
```

The function requires an existing verified request and one exact terminal Day
6 result. It returns a reconstructed, reopened, verified `EvidenceRecord` for
available and 404 outcomes. It returns `None` after durably verifying a
retryable or nonretryable failure attempt. Persistence failures raise the
sanitized exception and never return evidence.

No public database connection, schema object, storage protocol, repository,
unit of work, result wrapper, persistence receipt, or migration API is added.

### Sanitized error categories

The public exception categories and messages are fixed:

| Category | Safe message |
| --- | --- |
| `invalid_input` | `The persistence input is invalid.` |
| `invalid_database_path` | `The database path must identify an on-disk SQLite database.` |
| `database_unavailable` | `The SQLite database is unavailable.` |
| `schema_incompatible` | `The SQLite persistence schema is incompatible.` |
| `request_not_found` | `The persisted assessment request was not found.` |
| `conflicting_replay` | `The persistence identity is already bound to different content.` |
| `write_failed` | `The SQLite persistence transaction failed.` |
| `verification_failed` | `The persisted content could not be verified.` |

All caught `sqlite3.Error`, decoding, reconstruction, and storage-integrity
failures are translated without exception chaining. Caller input values are
not interpolated into public messages.

### Database path and connections

Accept `str` and `os.PathLike[str]` filesystem paths only. Reject empty paths,
NUL-containing paths, `:memory:`, every `file:` URI, and other memory-database
forms before connecting. After opening, require `PRAGMA database_list` to
identify a nonempty main database filename.

Every connection executes `PRAGMA foreign_keys = ON` and
`PRAGMA synchronous = FULL` and verifies that both settings are active. Schema
initialization or verification also proves `PRAGMA user_version = 1` before a
connection is returned. The module uses short-lived connections only. It does
not create parent directories, configure a pool, select WAL, or expose a
connection to callers.

### Schema version 1

Use `PRAGMA user_version = 1`. A new empty database creates all four tables in
one schema transaction. An existing database must already report version 1
and contain the expected schema. A different version or incompatible schema
fails closed.

#### `assessment_requests`

One immutable row keyed by `assessment_id`, containing:

* all eleven exact Day 5 submitted fields;
* enum values as their locked string values;
* `submitted_at` as its exact `datetime.isoformat()` representation; and
* `normalized_repository_identity`.

There is no persisted validation status, workflow state, or request digest.

#### `collection_attempts`

One row for every terminal Day 6 result, keyed by
`collection_attempt_id`, containing:

* owning assessment foreign key;
* evidence kind and unique per-assessment/evidence-kind attempt number;
* exact attempted timestamp representation;
* canonical requested repository identity and API source identity;
* collector version and terminal outcome;
* response status and sanitized ETag where allowed; and
* sanitized error category, retryability, constant message, and retry guidance
  where present.

No collection-result digest is introduced.

#### `github_source_snapshots`

Exactly one row for an available attempt, linked one-to-one to that attempt,
containing:

* deterministic source-snapshot ID;
* exact UTF-8 GitHub response bytes as a SQLite BLOB;
* encoding `utf-8` and media type `application/json`;
* the existing Day 6 SHA256 digest;
* GitHub repository source ID; and
* sanitized ETag when present.

No row exists for 404 or failed outcomes.

#### `evidence_records`

Exactly one row for an available or 404 attempt, linked one-to-one to the
attempt and owning request. It stores every field needed to reconstruct the
existing `EvidenceRecord`, the persisted provenance tuple, and the locked
normalization version.

Available rows contain a strict SQLite integer `0` or `1`, compact canonical
snapshot, compact SHA256 digest, and a composite foreign-key link to the full
source snapshot for the same attempt. Unavailable rows contain no value,
snapshot, digest, or source-snapshot link and retain the safe
`repository_not_publicly_available` reason and category.

Primary keys, unique constraints, check constraints, and composite foreign
keys enforce one-to-one links, positive attempt numbers, legal outcomes, legal
Boolean storage, and request/attempt/snapshot ownership. SQLite row IDs are
private and are not domain identities.

### Deterministic identifiers and versions

Derive source-snapshot and evidence identifiers with lowercase SHA256 over
length-independent, NUL-separated identity material, not content:

```text
<namespace>\0<assessment_id>\0repository_archived\0<collection_attempt_id>
```

Use namespace `github-source-snapshot.v1` for source snapshots and
`repository-archived-evidence.v1` for evidence. Prefix the hexadecimal value
with `github-source-snapshot-` or `repository-archived-evidence-`.

Store these exact versions:

* SQLite schema version `1`;
* Day 5 `request_definition_version` from the request;
* Day 6 `collector_version` from the result;
* evidence schema version `evidence-record.v1`; and
* normalization version `repository-archived-normalization.v1`.

The evidence collector name is
`public-github-repository-metadata`. Available evidence uses freshness basis
`collection_time` and `FreshnessStatus.CURRENT`; unavailable evidence uses
freshness basis `unknown` and `FreshnessStatus.UNKNOWN`.

Available provenance is the fixed ordered tuple of source-snapshot ID,
source-snapshot digest, and GitHub repository source ID. Unavailable provenance
contains the safe collection error category. Provenance is stored as canonical
JSON and reconstructed without coercion.

### Request transaction and verification

Before opening a transaction:

1. require the exact validation-result type and `validation_status == "valid"`;
2. rerun `validate_assessment_request` on the exact request; and
3. require exact equality with the supplied result.

In one explicit request transaction, insert the immutable request or compare
an existing row. An exact existing row is replay; any field difference is a
conflict. Commit and close the connection.

Open a new connection, verify schema and foreign keys, read exactly one row,
parse enums and timestamp without coercion, rebuild the Day 5 input, rerun the
Day 5 validator, and compare every stored representation and rebuilt value to
the intended result. Only then return the original supplied valid result.

### Collection transaction and verification

Before writing, reconstruct the supplied Day 6 result from all its fields so
its existing `__post_init__` invariants rerun. Load and fully verify the owning
request. Its assessment and canonical repository identity must exactly match
the collection input.

For a new available result, one explicit transaction inserts:

1. collection attempt;
2. full GitHub source snapshot; and
3. compact normalized evidence row.

For 404, one transaction inserts the attempt and unavailable evidence row. For
retryable and nonretryable failures, one transaction inserts only the attempt.
Any exception rolls back the entire transaction. A commit exception fails
closed and is not treated as success.

An existing attempt identity is first independently reopened and verified. If
the durable result is valid and exactly equals the supplied result, it is an
idempotent replay. If valid durable content differs, it is a conflict. If the
durable content is internally inconsistent, it is a verification failure.
A different attempt ID reusing the same assessment/evidence-kind attempt
number is a conflict.

After commit or replay detection, close the connection and open a new one.
Verification requires:

* exact attempt, request, and foreign-key relationships;
* exactly the allowed snapshot and evidence row counts for the outcome;
* exact timestamp, enum, version, source, status, safe metadata, and error
  fields;
* strict UTF-8 decoding of full response bytes;
* SHA256 equality among stored bytes, stored source digest, and rebuilt Day 6
  result;
* successful Day 6 result reconstruction, including GitHub payload binding,
  strict archived typing, source ID, identity casing rule, and ETag;
* exact compact JSON and compact digest;
* exact normalization and provenance version/content;
* successful existing `EvidenceRecord` reconstruction; and
* exact equality with the evidence deterministically expected from the Day 6
  result.

No pre-commit evidence object is returned. The authoritative available or
unavailable value is the `EvidenceRecord` reconstructed from the reopened
database. A failure attempt returns `None` only after reopening proves that it
has an attempt row and no source snapshot or evidence row.

### Failure and rollback behavior

* Invalid contracts and memory paths fail before domain writes.
* A missing or mismatched request blocks collection persistence.
* SQLite open, schema, write, and commit failures expose sanitized categories.
* Linked-write failures roll back attempts, snapshots, and evidence together.
* Digest, normalized value, payload binding, version, relationship, decoding,
  or reconstruction failures return no evidence and do not repair data.
* Exact replay never adds rows; conflicting replay never overwrites rows.
* A commit exception receives no special uncertainty protocol. A later exact
  replay may verify and accept complete durable content.
* A GitHub collection failure remains its original Day 6 outcome; a database
  failure is never relabeled as a source failure.

## Files Affected

Create only:

* `plans/day_08_sqlite_repository_archived_persistence.md` — this locked plan;
* `src/engineering_due_diligence/persistence.py` — concrete schema,
  transactions, reconstruction, and verification; and
* `tests/test_sqlite_repository_archived_persistence.py` — focused real SQLite
  tests.

Do not modify existing source, tests, README, journal, memory, ADR, package
exports, or dependency files.

## Database Impact

The source module creates schema version 1 in each caller-supplied on-disk
SQLite file when it is initially empty. Tests create databases only inside
`TemporaryDirectory` locations and remove them after each test.

There is no migration framework, seed data, repository layer, shared database,
production configuration, or committed database artifact.

## Testing Strategy

Add these fifteen focused tests using real temporary on-disk SQLite databases:

1. `test_request_is_durable_after_close_and_reopen_with_schema_and_foreign_keys`
   — persist all eleven request fields, inspect schema version, foreign-key and
   full-synchronous settings on a reopened persistence connection, and verify
   exact timestamp representation.
2. `test_invalid_request_and_memory_database_paths_are_safely_rejected` — reject
   an invalid Day 5 result, `:memory:`, a memory URI, an unavailable disk path,
   and an unsupported existing schema version with only locked
   categories/messages and no path or SQLite text.
3. `test_collection_requires_matching_persisted_request` — reject a missing
   request and a collection identity that does not match the durable request.
4. `test_available_archived_result_returns_verified_evidence` — persist and
   reopen an archived result and assert the complete available
   `EvidenceRecord` and deterministic links.
5. `test_available_unarchived_result_returns_strict_false` — prove `False`
   remains exact Boolean `False` and SQLite `0` without coercion.
6. `test_available_result_preserves_exact_full_response_separately` — assert
   exact UTF-8 bytes, source digest, source ID, ETag, encoding, and media type
   in the separate snapshot table.
7. `test_available_result_preserves_compact_snapshot_integrity` — assert exact
   compact JSON, its distinct digest, normalization version, provenance, and
   source-snapshot link.
8. `test_unrelated_github_fields_survive_full_snapshot_round_trip` — preserve
   unrelated arrays, objects, ordering, and whitespace in exact source bytes.
9. `test_404_persists_unavailable_evidence_without_source_snapshot` — assert
   atomic attempt plus unavailable evidence and no source snapshot or partial
   value.
10. `test_retryable_and_nonretryable_failures_persist_attempt_only` — cover a
    retryable server result and a nonretryable rejected result, returning no
    evidence and storing no snapshot/evidence row.
11. `test_linked_write_failure_rolls_back_complete_collection_transaction` —
    use a test-only SQLite trigger to fail evidence insertion after earlier
    statements; assert attempt, snapshot, and evidence rows all roll back and
    the sanitized exception contains neither trigger nor SQLite text.
12. `test_exact_request_and_collection_replay_adds_no_rows` — replay both
    operations and assert equal results with unchanged row counts.
13. `test_conflicting_request_attempt_and_collection_replays_are_rejected` —
    cover changed request content, reused attempt number, and changed valid
    collection content without mutation.
14. `test_full_source_digest_corruption_fails_closed` — corrupt the stored
    source digest and assert exact replay returns no evidence with a sanitized
    verification failure.
15. `test_normalized_value_corruption_fails_closed` — corrupt the stored
    archived value while leaving compact content unchanged and assert existing
    `EvidenceRecord` invariants prevent evidence return.

No test invokes the Day 6 collector or performs network access. Run:

```text
PYTHONPATH=src python3 -m unittest tests.test_sqlite_repository_archived_persistence -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
git diff --check
git diff --stat
git status --short
```

Expected complete total after fifteen focused tests:

```text
Ran 103 tests
OK
```

## Acceptance Criteria

* Only the three approved files are created.
* SQLite is on disk, caller supplied, standard-library only, schema version 1,
  and foreign keys are enabled on every connection.
* Complete valid Day 5 requests are committed and reopened before collection
  can be persisted.
* Every terminal Day 6 result creates exactly one attempt row.
* Available attempt, complete source response, and normalized evidence commit
  atomically; 404 attempt and unavailable evidence commit atomically; other
  failures create only their attempt.
* Full response bytes and compact canonical evidence snapshots remain separate
  with independent existing digests.
* Only reopened and fully verified available/unavailable evidence is returned.
* Exact replay is idempotent and conflicting replay is nonmutating.
* Incomplete writes roll back and all persistence/integrity failures fail
  closed without leaking paths, SQLite details, or payloads.
* Existing Day 3 through Day 6 behavior and 88 tests remain unchanged.
* All 103 tests, compilation, and whitespace verification pass.

## Risks

* SQLite durability still depends on the host filesystem and device; this is a
  prototype boundary, not production operational readiness.
* The schema is deliberately specific to one evidence kind. Generalizing it
  before another proven collector would add premature abstraction.
* Complete GitHub responses have no explicit size limit in Day 6 and are stored
  as one BLOB.
* Close-and-reopen verification detects corruption but does not repair it.
* Direct SQL access can mutate internally valid rows. Verification must treat
  all stored content as untrusted and rerun Day 5, Day 6, and Day 3 invariants.
* Concurrent writers, busy handling, backup, encryption, permissions, and
  retention remain unresolved and must not be inferred from passing local
  tests.

## Rollback Plan

Remove the new persistence module, focused tests, and this plan. No committed
database, production data, migration, external service, API, or workflow
integration exists. Existing Day 3 through Day 6 callers remain unchanged.

## Explicit Exclusions

* Changes to request validation, GitHub collection, domain models,
  deterministic evaluation, or assessment assembly.
* Workflow state, transition history, orchestration, retries, scheduling,
  current-evidence selection, or resumability.
* APIs, CLIs, FastAPI, Pydantic, serialization endpoints, or user interfaces.
* ORMs, repository patterns, generic storage interfaces, provider abstractions,
  unit-of-work APIs, migration frameworks, or dependency injection.
* Remaining collectors, authenticated GitHub access, private repositories, or
  live network tests.
* Evaluator integration, metrics, policy findings, reports, audit events, model
  integration, or human decisions.
* PostgreSQL, deployment, pooling, concurrency optimization, backup, restore,
  encryption, access control, retention, telemetry, or production operations.
* README, journal, memory, ADR, package-root export, or dependency updates.

## Implementation Checklist

* Confirm the clean 88-test baseline.
* Create and review this plan before source changes.
* Implement the locked public contracts and schema version 1.
* Reuse existing Day 5, Day 6, and Day 3 invariant constructors during
  verification.
* Add all fifteen focused real-SQLite tests without network access.
* Run focused and complete verification plus compilation and whitespace checks.
* Review the complete diff for atomicity, fail-closed behavior, error leakage,
  replay conflicts, duplicated validation, and scope expansion.
* Do not stage, commit, push, or begin broader workflow work.
