# Day 10 Journal

## Work Completed

Implemented public GitHub latest-commit timestamp collection and concrete
SQLite persistence. The new contracts are:

```python
@dataclass(frozen=True)
class GitHubLatestCommitCollectionResult:
    ...

def collect_public_github_latest_commit(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLatestCommitCollectionResult:

def persist_github_latest_commit_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubLatestCommitCollectionResult,
) -> Optional[EvidenceRecord]:
```

The collector performs exactly one unauthenticated request through the
existing private transport seam:

```text
GET https://api.github.com/repos/<owner>/<repository>/commits?per_page=1
```

No shared transport headers, repository-archived behavior, or license-status
behavior changed.

## Collection and Empty Repository Behavior

HTTP 200 requires exact UTF-8 JSON containing an array with zero or one
element. More than one element fails closed. A commit element must contain a
40-character lowercase hexadecimal SHA, an exact API URL bound to the
requested repository and SHA, a commit object, a committer object, and a
timezone-aware `commit.committer.date`. Author date is never used as a
fallback. Unrelated response fields remain accepted and preserved.

One valid commit produces transient
`EvidenceKind.LATEST_COMMIT_TIMESTAMP` data. A valid empty array produces
unavailable evidence with HTTP 200 and the stable
`repository_has_no_commits` category; it never invents a timestamp. Repository
404 remains public unavailability, while HTTP 409 remains a nonretryable
request failure rather than proof that no commits exist. Other transport and
HTTP failures reuse the existing sanitized classifications and contain no
partial timestamp, SHA, response snapshot, digest, or ETag.

## Timestamp Normalization and Provenance

The collector preserves both the exact source committer timestamp string and a
parsed timezone-aware `datetime`. Those values may use different timezone
offset representations, but they must denote the same UTC instant. The source
representation remains in the complete response and explicit provenance; the
normalized representation becomes the typed evidence value and canonical
compact snapshot.

The commit SHA, exact successful response text, matching SHA256 digest,
sanitized ETag, source timestamp text, and normalized timestamp are all
preserved. An old latest-commit value remains current evidence at collection
time: its age is a later deterministic metric, not evidence freshness.

## SQLite Schema Version 3

Fresh databases now create exact schema version 3. The schema retains the
archived Boolean and license-status columns and adds the typed
`latest_commit_timestamp_value` column. Available evidence populates only the
column matching its evidence kind; unavailable evidence populates none.

An exact version 2 database migrates inside one `BEGIN IMMEDIATE` transaction.
The migration rebuilds only the affected linked tables, copies archived and
license rows in primary-key order, compares every preserved field, verifies
exact schema definitions and foreign keys, and advances `PRAGMA user_version`
only after verification. Any failure rolls back completely and leaves the
version 2 database intact and usable. Existing exact version 1 databases retain
their prior transactional path through version 2 before version 3.

## Persistence, Authority, and Replay

A matching durable request is required. An available outcome atomically writes
the collection attempt, exact complete GitHub commits response, and compact
latest-commit `EvidenceRecord`. Empty-array and repository-404 outcomes
atomically write the attempt and unavailable evidence. Other failures write
only the attempt.

After commit or replay, the database is closed and reopened. Verification
recomputes the full-response digest from reopened bytes, reparses the commit,
revalidates its SHA, repository binding, URL, committer timestamp, and source
instant, reconstructs the exact normalized timestamp from typed storage, and
reconstructs the unchanged existing `EvidenceRecord`. Compact digest,
provenance, relationships, versions, timestamp representations, and foreign
keys must all agree before evidence becomes authoritative.

Exact replay creates no duplicate rows. Changed source timestamp text is a
conflict even when it denotes the same instant. Conflicting replay changes no
durable history, incomplete writes roll back, and persistence errors remain
sanitized.

## Review Findings

Final review corrected one material reconstruction issue: reopen verification
originally derived the normalized timestamp only from the source timestamp.
It now reconstructs the exact normalized representation from durable typed
evidence storage and independently proves that it denotes the same UTC instant
as the exact source timestamp. Focused coverage proves that a `-05:00` source
timestamp can safely reconstruct a normalized `+00:00` value.

Review also confirmed that status-200 unavailable rows are allowed only for
latest-commit empty results, the new typed timestamp column requires nonempty
text, migration rollback leaves version 2 usable, and archived and license
persistence remain fully functional under schema version 3.

## Verification

Fourteen focused collector tests and seventeen focused persistence tests cover
strict response validation, empty repositories, failure classification, exact
source preservation, schema creation and migration, rollback, atomic writes,
reopen verification, replay, corruption, prior-kind regressions, and absence
of live network access.

The complete suite passes:

```text
Ran 177 tests
OK
```

Compilation and whitespace verification also pass.

## Risks and Explicit Exclusions

The collector deliberately accepts current 40-character lowercase GitHub
SHA-1 commit identifiers only. Successful responses have no explicit size
limit. SQLite corruption is detected but not repaired. Production concurrency,
backup, encryption, access control, retention, and deployment remain deferred.

Day 10 added no security-policy collection, workflow orchestration,
deterministic evaluator integration, metric or policy persistence, API, CLI,
retry execution, audit event, report, model integration, ORM, repository or
provider abstraction, or production infrastructure.

## Next Task

The next narrow slice is public GitHub security-policy presence collection and
SQLite persistence. Do not begin workflow orchestration or deterministic
evaluation integration until that fourth required evidence kind is durable.
