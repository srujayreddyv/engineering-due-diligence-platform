# Day 9 Journal

## Work Completed

Implemented the public GitHub license-status collection and SQLite persistence
slice. The collector reuses the existing frozen
`GitHubRepositoryMetadataCollectionInput`, `GitHubCollectionOutcome`, and
`GitHubRepositoryMetadataCollectionError` contracts and adds:

```python
@dataclass(frozen=True)
class GitHubLicenseStatusCollectionResult:
    ...

def collect_public_github_license_status(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLicenseStatusCollectionResult:

def persist_github_license_status_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubLicenseStatusCollectionResult,
) -> Optional[EvidenceRecord]:
```

The collector performs exactly one unauthenticated request through the existing
private transport seam:

```text
GET https://api.github.com/repos/<owner>/<repository>
```

The shared Accept and User-Agent headers, lack of authorization, and existing
repository-archived collector behavior remain unchanged.

## Validation and Normalization

HTTP 200 requires exact UTF-8 bytes containing one JSON object. Nonstandard
JSON constants are rejected. Repository `id` must be a positive non-Boolean
integer, and `full_name` must bind to the requested canonical repository using
the existing ASCII case-insensitive comparison.

The `license` field must be present and exactly `null` or an object. A license
object must contain exact nonempty, printable, unpadded string values for
`key`, `name`, and `spdx_id`; unrelated repository and license fields remain
accepted and preserved. Normalization is deliberately narrow:

```text
license object -> LicenseStatus.PRESENT
license null   -> LicenseStatus.ABSENT
```

Missing, malformed, or incorrectly typed license data is an invalid response,
not evidence of absence. The complete successful response text and SHA256
digest are preserved exactly. License presence means only that GitHub returned
detected license metadata; it is not legal, compatibility, dependency-license,
or policy analysis. Failed and unavailable outcomes contain no partial license
value, repository source ID, source snapshot, digest, or ETag.

## SQLite Schema Version 2

Fresh databases now create exact schema version 2. The four existing tables
remain, while collection attempts and evidence records support exactly
`repository_archived` and `license_status`. Evidence records retain the strict
archived Boolean column and add a strict license-status column permitting only
`present` or `absent`. Available evidence must populate exactly the value
column matching its evidence kind; unavailable evidence populates neither.

An exact schema version 1 database migrates inside one `BEGIN IMMEDIATE`
transaction. The migration rebuilds the three collection-dependent tables,
copies every archived attempt, full response snapshot, and evidence field,
compares copied rows in primary-key order, verifies exact normalized schema
definitions and foreign keys, and advances `PRAGMA user_version` only after all
checks pass. Archived identifiers, response bytes, digests, compact snapshots,
provenance, normalized values, versions, and timestamp representations remain
unchanged. Unsupported versions, altered definitions, or extra user tables
fail without mutation. Any migration failure rolls back to the complete usable
version 1 database.

## Persistence, Authority, and Replay

A matching durable Day 5 request is required before license collection
persistence. Available present or absent outcomes atomically persist the
collection attempt, complete GitHub response snapshot, and compact existing
`EvidenceRecord`. The compact snapshot is exactly
`{"value":"present"}` or `{"value":"absent"}` and remains separate from
the complete source response. A repository 404 atomically persists the attempt
and unavailable evidence. Other terminal failures persist only the attempt and
return no evidence.

After a write or exact replay, the database is closed and reopened. The
persistence boundary recomputes the full-response digest from reopened bytes,
revalidates repository ID, binding, and license metadata, reconstructs the
transient collection result, reconstructs the unchanged `EvidenceRecord`, and
verifies compact digest, normalized enum, provenance, relationships,
timestamps, collector and schema versions, and foreign keys. Only reopened and
verified available or unavailable evidence is authoritative.

Exact replay creates no rows. Conflicting replay changes no durable content.
Incomplete linked writes roll back. Corrupted source content, digest, compact
snapshot, normalized value, provenance, relationship, or version fails closed.
Expected persistence errors expose only stable categories and constant safe
messages; unexpected programmer errors remain visible as programmer errors.

## Material Corrections

Implementation and review corrected these material issues:

1. Fresh creation and version 1 migration now verify exact schema definitions
   and foreign keys inside the transaction before schema version 2 is committed.
2. Existing archived replay corruption remains a verification failure rather
   than being misclassified as an ordinary conflicting replay.
3. Version 1 eligibility now rejects extra user tables instead of accepting a
   non-exact schema.
4. Migration preservation comparisons use stable primary-key ordering rather
   than `rowid` ordering.
5. The migration rollback test now injects failure during transactional v2
   verification and proves the original v1 database remains usable.
6. Focused coverage now explicitly proves contradictory license-result
   construction fails, relationship and version corruption is detected, and
   unexpected programmer errors are not converted to persistence outcomes.
7. The two existing Day 8 schema-version assertions were updated from 1 to 2;
   no other existing test behavior changed.

## Verification

Twenty focused license collector tests and twenty-three focused license
persistence and migration tests pass. The collector tests patch the private
transport seam, and persistence tests use real temporary on-disk SQLite
databases. No test performs a live network request.

The complete suite passes:

```text
Ran 146 tests
OK
```

Compilation and whitespace verification also pass.

## Risks and Explicit Exclusions

The collector trusts GitHub only for detected-license metadata and does not
establish legal suitability. Complete GitHub responses have no explicit size
limit. Corruption is detected but not repaired. Migration intentionally
accepts only the exact owned version 1 schema. SQLite remains a prototype
choice without production concurrency, backup, encryption, access-control,
retention, deployment, or disaster-recovery design.

Day 9 added no latest-commit or security-policy collector, workflow
orchestration, deterministic evaluator integration, retry execution, API, CLI,
ORM, repository or provider abstraction, audit behavior, report generation,
model integration, or human-decision behavior.

## Next Task

The next narrow slice is latest commit timestamp collection and persistence.
It must begin with planning and must not introduce workflow orchestration or
connect incomplete durable evidence to deterministic evaluation.
