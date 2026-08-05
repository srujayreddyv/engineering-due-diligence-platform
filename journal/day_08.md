# Day 8 Journal

## Work Completed

Implemented the concrete SQLite persistence slice approved by the Day 7
direction review and ADR 0001. The new public contracts are:

```python
class SQLitePersistenceError(Exception):
    category: str

def persist_valid_assessment_request(
    database_path: str | os.PathLike[str],
    validation_result: AssessmentRequestValidationResult,
) -> AssessmentRequestValidationResult:

def persist_github_repository_metadata_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubRepositoryMetadataCollectionResult,
) -> Optional[EvidenceRecord]:
```

The module uses only Python `sqlite3`, requires a caller-supplied on-disk path,
rejects memory and SQLite URI databases, enables foreign keys and full
synchronous writes on every connection, and uses schema version 1.

## Durable Records and Relationships

The schema contains four tables:

1. `assessment_requests` stores the exact eleven Day 5 submitted fields,
   canonical repository identity, enum values, versions, and timestamp
   representation.
2. `collection_attempts` stores every terminal Day 6 outcome and links it to
   its required assessment request.
3. `github_source_snapshots` stores the exact successful UTF-8 GitHub response
   bytes, response digest, repository source ID, and sanitized ETag separately
   from normalized evidence.
4. `evidence_records` stores the compact existing repository-archived
   `EvidenceRecord` representation and links it to its request, attempt, and,
   for available evidence, full source snapshot.

Available outcomes atomically write the collection attempt, full source
snapshot, and compact evidence. A 404 atomically writes the attempt and an
unavailable evidence row without a source snapshot. Retryable and nonretryable
failures write only their complete collection attempt and return no evidence.
Any incomplete linked write rolls back.

## Authority, Verification, and Replay

No evidence constructed before commit is authoritative. After a successful
write or exact replay, the connection is closed and the database is reopened.
The boundary then verifies schema and connection settings, stored fields and
links, exact timestamp representations, response bytes and recomputed digest,
GitHub payload binding, strict archived Boolean normalization, compact snapshot
and digest, provenance, versions, and the unchanged Day 5, Day 6, and Day 3
constructors. Only the `EvidenceRecord` reconstructed from reopened durable
content may be returned.

Exact request and collection replays add no rows. Reusing assessment, attempt,
attempt-number, source-snapshot, or evidence identities with different
material content is rejected without changing durable history. Reopen,
digest, normalization, reconstruction, or verification failure returns no
authoritative evidence and exposes only a stable sanitized persistence error.

## Review Corrections

The first implementation review corrected three hardening issues:

1. Persistence now explicitly reconstructs the supplied Day 6 input so its
   constructor invariants run before writing.
2. Reopened collection attempts explicitly prove that their repository
   identity matches the owning durable request.
3. Connection and rollback cleanup cannot leak raw SQLite cleanup details.

The final review corrected four additional material issues:

1. Existing schema verification now compares exact normalized table
   definitions, so a version-1 database missing required foreign-key, unique,
   or check constraints fails closed.
2. Pre-write exception handling catches only expected input failures instead
   of converting unexpected programmer errors into ordinary persistence
   outcomes.
3. Focused tests now prove `PRAGMA synchronous = FULL` and rejection of an
   unsupported existing schema version.
4. Replay tests now prove offset-sensitive timestamp representation and
   failure metadata, including retry guidance, are material conflict fields.

## Verification

Fifteen focused Day 8 tests use real temporary on-disk SQLite databases. They
cover request durability, invalid and missing requests, archived and unarchived
available evidence, exact full-response preservation, compact snapshot
integrity, unrelated GitHub fields, 404 unavailable evidence, failure-only
attempts, rollback, exact and conflicting replay, and corruption detection.
They make no live network calls.

The complete suite passes:

```text
Ran 103 tests
OK
```

Compilation and whitespace verification also pass.

## Risks and Explicit Exclusions

This schema is deliberately limited to repository archived status. Complete
GitHub responses have no explicit size limit, corruption is detected but not
repaired, and concurrent writers, busy handling, backup, encryption,
permissions, retention, migration, deployment, and production operations
remain unresolved.

Day 8 did not add or change request validation, collection, domain,
deterministic evaluation, or assessment behavior. It added no workflow engine,
retry executor, API, CLI, ORM, repository or provider abstraction, remaining
collector, evaluator integration, audit history, report, model integration, or
human decision behavior.

## Next Task

The exact next task is to plan the next narrow vertical slice after persistence.
It should begin with a read-only direction review and must not assume that the
repository-archived evidence alone is sufficient for the existing four-kind
deterministic evaluation boundary.
