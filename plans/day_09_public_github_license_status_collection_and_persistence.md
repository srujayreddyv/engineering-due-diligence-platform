# Day 9 Public GitHub License Status Collection and Persistence Plan

## Task

Add one transient public GitHub license-status collector and extend the concrete
SQLite store from schema version 1 to version 2 so terminal license collection
outcomes can become durable, verified `EvidenceKind.LICENSE_STATUS` evidence.

## Objective

Collect GitHub's detected-license fact from the existing repository endpoint,
preserve the complete successful response before normalization, and return an
authoritative `EvidenceRecord` only after atomic persistence, database close,
reopen, and complete integrity verification.

The slice remains limited to public GitHub repositories. It does not determine
license compatibility, legal sufficiency, dependency licensing, policy
compliance, or a final assessment conclusion.

## Current State

Day 5 validates a complete transient assessment request. Day 6 performs one
public GitHub repository metadata request and produces strict transient
repository-archived outcomes. Day 8 persists the request and every terminal
repository-archived collection attempt in on-disk SQLite schema version 1;
available and 404 outcomes become authoritative existing `EvidenceRecord`
values only after close-and-reopen verification.

The deterministic evaluator also requires license status, latest commit
timestamp, and security-policy presence. No collector or persistence boundary
exists yet for those three facts.

## Public Contracts

Reuse these frozen Day 6 contracts unchanged:

* `GitHubRepositoryMetadataCollectionInput`
* `GitHubCollectionOutcome`
* `GitHubRepositoryMetadataCollectionError`

Add one frozen result:

```python
@dataclass(frozen=True)
class GitHubLicenseStatusCollectionResult:
    request: GitHubRepositoryMetadataCollectionInput
    outcome: GitHubCollectionOutcome
    evidence_kind: EvidenceKind
    collector_version: str
    source_identity: str
    repository_source_id: Optional[str]
    license_status: Optional[LicenseStatus]
    raw_snapshot: Optional[str]
    integrity_digest: Optional[str]
    response_status: Optional[int]
    response_etag: Optional[str]
    error: Optional[GitHubRepositoryMetadataCollectionError]
```

Add one collector:

```python
def collect_public_github_license_status(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLicenseStatusCollectionResult:
```

Add one concrete persistence function:

```python
def persist_github_license_status_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubLicenseStatusCollectionResult,
) -> Optional[EvidenceRecord]:
```

Do not add package-root exports, transport protocols, repositories, units of
work, connection APIs, result wrappers, or migration APIs.

## Collection Design

Perform exactly one unauthenticated request through the existing private
`_get_public_github_repository` seam:

```text
GET https://api.github.com/repos/<owner>/<repository>
```

The existing Accept and User-Agent headers remain unchanged. Do not add an API
version or authorization header. The requested path preserves submitted owner
and repository casing. GitHub's returned `full_name` is compared using the
existing ASCII case-insensitive binding rule.

For HTTP 200, require response bytes, decode them as strict UTF-8, parse one
JSON object while rejecting `NaN`, `Infinity`, and `-Infinity`, then validate:

* `id`: exact positive non-Boolean JSON integer;
* `full_name`: exact string accepted by the existing repository-name grammar
  and case-insensitively equal to the requested owner/repository; and
* `license`: exactly JSON `null` or one JSON object.

A license object establishes only that GitHub returned detected license
metadata. Its minimum required fields are `key`, `name`, and `spdx_id`; each
must be an exact nonempty, printable, unpadded JSON string. Other fields in the
license object and all unrelated repository fields are accepted without
interpretation. Missing `license`, a non-object/non-null value, or any invalid
required object field is an invalid response.

Normalize an object to `LicenseStatus.PRESENT` and `null` to
`LicenseStatus.ABSENT`. Preserve the exact successful UTF-8 response text and
SHA256 digest of its exact bytes. Sanitize ETag with the existing rule.

HTTP 404 is unavailable repository evidence. Rate limit, authorization,
request rejection, server, timeout, connectivity, invalid response, and
unexpected-status classifications reuse the existing safe Day 6 error
contracts. Nonavailable outcomes contain no repository source ID, license
status, raw snapshot, digest, or ETag. Error bodies, unsafe headers, transport
exception messages, credentials, and authorization data never enter results.

Collector version is `public-github-license-status.v1`. The transient result
is not an authoritative `EvidenceRecord`.

## SQLite Schema Version 2

Fresh databases create schema version 2 directly. Existing exact version 1
databases migrate to version 2 in one `BEGIN IMMEDIATE` transaction. The
migration renames the three collection-dependent version 1 tables, creates the
version 2 tables, copies all rows without transforming any stored archived
field, verifies copied row equality and foreign keys, drops the old tables,
and sets `PRAGMA user_version = 2` only after all validation succeeds. Any
failure rolls the transaction back, leaving the complete version 1 schema and
content unchanged. Other versions fail closed.

`assessment_requests` and `github_source_snapshots` retain their fields and
meaning. `collection_attempts.evidence_kind` is widened to exactly
`repository_archived` or `license_status`. `evidence_records` is widened the
same way and adds:

```text
license_status_value TEXT NULL CHECK (
    license_status_value IS NULL
    OR license_status_value IN ('present', 'absent')
)
```

Available archived evidence requires `archived_value` and forbids
`license_status_value`. Available license evidence requires
`license_status_value` and forbids `archived_value`. Unavailable evidence
requires both value columns, both snapshots, both digests, and its source
snapshot link to be null. Existing primary keys, foreign keys, unique attempt
numbers, one-to-one links, terminal-outcome checks, and exact normalized schema
verification remain enforced.

## License Persistence and Authority Boundary

The durable request must already exist and fully reconstruct as the exact Day
5 result. Its assessment ID and canonical repository identity must equal the
license collection input.

Use deterministic IDs derived from NUL-separated assessment ID, evidence kind,
and collection-attempt ID. License evidence uses namespace
`license-status-evidence.v1` and prefix `license-status-evidence-`. Full GitHub
snapshots continue to use namespace `github-source-snapshot.v1` and prefix
`github-source-snapshot-`, with the evidence kind included in the digest
material so archived and license attempts cannot collide.

Store collector name `public-github-license-status`, collector version from the
result, evidence schema version `evidence-record.v1`, and normalization version
`license-status-normalization.v1`.

Available present or absent results atomically write the attempt, exact full
response bytes, and compact evidence. Compact snapshots are exactly
`{"value":"present"}` or `{"value":"absent"}` with matching SHA256 digests.
Available evidence uses collection-time/current freshness and fixed ordered
provenance containing source-snapshot ID, full-response digest, and GitHub
repository source ID.

404 atomically writes the attempt and one unavailable license `EvidenceRecord`
with unknown freshness and safe repository-unavailable provenance. Other
terminal failures write only the attempt and return `None`.

After commit, close and reopen the database. Recompute the full-response digest
from reopened bytes; strictly revalidate `id`, `full_name`, and `license`;
reconstruct the transient result and unchanged `EvidenceRecord`; and compare
every request, attempt, timestamp representation, outcome, status, error,
retry, ETag, snapshot, digest, normalized value, evidence, provenance, link,
collector, schema, and normalization field. Run foreign-key verification.
Only the reopened reconstructed evidence may be returned.

An exact replay compares every material stored field and creates no duplicate
rows. Reuse of an assessment, attempt ID, attempt number, snapshot ID, or
evidence ID with different content fails as `conflicting_replay` without
changing history. Insert, constraint, commit, reopen, digest, normalization,
or verification failure returns no evidence. Existing stable sanitized
`SQLitePersistenceError` categories and messages remain unchanged.

## Focused Tests

### Collector

1. Frozen result and reused input invariants.
2. Exactly one patched transport call; no live network path.
3. License object becomes `LicenseStatus.PRESENT`.
4. License null becomes `LicenseStatus.ABSENT`.
5. Missing license fails.
6. Non-null/non-object license types fail without coercion.
7. Missing, empty, padded, or non-string `key`, `name`, or `spdx_id` fails.
8. Boolean, zero, negative, string, and fractional repository IDs fail.
9. Malformed or mismatched repository `full_name` fails.
10. Unrelated repository and license fields remain in exact raw text.
11. Exact successful text and SHA256 digest are preserved.
12. Safe ETag is trimmed; unsafe ETag is omitted.
13. Repository 404 is unavailable.
14. 403/429 rate limit is retryable.
15. Authorization failure is nonretryable.
16. Server failure is retryable.
17. Direct and wrapped timeouts are retryable.
18. Connectivity failures are retryable.
19. Invalid UTF-8, malformed/non-object/nonstandard JSON fails safely.
20. Every unsuccessful result has no partial evidence fields.

### Persistence

1. Fresh schema creation reports version 2 and exact constraints.
2. Exact version 1 schema migrates transactionally to version 2.
3. Existing archived request, attempt, snapshot, and evidence rows are
   byte-for-byte/field-for-field preserved by migration.
4. Forced migration failure rolls back schema, rows, and version to 1.
5. Unsupported schema version is rejected.
6. Missing, conflicting, or invalid durable request rejects license writes.
7. Present license survives close/reopen and returns authoritative evidence.
8. Absent license survives close/reopen and returns authoritative evidence.
9. Full source bytes and digest are exact after reopen.
10. Compact snapshot and digest are canonical and exact.
11. Unrelated response and license fields survive unchanged.
12. 404 writes unavailable evidence without a source snapshot.
13. Retryable and nonretryable failures write attempts only.
14. A forced linked-write failure leaves no partial attempt, snapshot, or
    evidence rows.
15. Exact replay creates no duplicates and returns equal reopened evidence.
16. Conflicting attempt ID or attempt number replay preserves history.
17. Equivalent instants with different timestamp text conflict.
18. Full source byte or digest corruption is detected after reopen.
19. Compact snapshot or digest corruption is detected after reopen.
20. License value corruption is detected after reopen.
21. Provenance corruption is detected after reopen.
22. Persistence tests use real temporary on-disk databases and no network.
23. Existing archived persistence remains fully functional after migration.

## Acceptance Criteria

* All collector and persistence rules above are implemented with the standard
  library and strict noncoercing validation.
* Existing Day 3 through Day 8 behavior remains unchanged.
* Schema version 1 migrates atomically and archived rows remain exact.
* Authoritative license evidence is returned only after close/reopen and full
  verification.
* Exact replay succeeds; conflicting replay and corruption fail closed.
* The complete test suite, compile check, and `git diff --check` pass.

## Risks and Rollback

The primary risks are a destructive table-rebuild migration, accidental
weakening of archived constraints, accepting ambiguous license shapes, or
returning evidence based on unverified stored content. Exact schema checks,
transactional copying, row-preservation tests, strict payload reconstruction,
and archived regression coverage mitigate them.

Rollback before commit is deletion of the three new Day 9 files and reversal
of only the Day 9 hunks in `github.py` and `persistence.py`. A failed runtime
migration rolls back to the complete version 1 database.

## Explicit Exclusions

Latest-commit and security-policy collectors, workflow orchestration,
evaluator integration, metric or policy persistence, retries, APIs, CLI,
audit, reporting, model integration, legal analysis, provider abstractions,
generic evidence-value storage, ORM, repository pattern, service container,
migration framework, production database selection, and live-network tests are
excluded.

## Verification

```text
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/engineering_due_diligence_pycache python3 -m compileall -q src tests
git diff --check
git diff --stat
git status --short
```
