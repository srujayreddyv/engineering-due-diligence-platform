# Day 10 Public GitHub Latest Commit Collection and Persistence Plan

## Task

Implement one public GitHub latest-commit collection boundary and the concrete
SQLite persistence slice that makes its terminal outcomes durable.

## Objective

Collect exactly one page containing at most one repository commit from
`GET https://api.github.com/repos/<owner>/<repository>/commits?per_page=1`,
normalize a valid committer timestamp into the existing
`EvidenceKind.LATEST_COMMIT_TIMESTAMP`, and return authoritative evidence only
after atomic persistence, database close, reopen, and complete verification.

## Locked Collector Contract

Reuse `GitHubRepositoryMetadataCollectionInput`, `GitHubCollectionOutcome`,
`GitHubRepositoryMetadataCollectionError`, and the private standard-library
transport seam. Add one frozen `GitHubLatestCommitCollectionResult` and:

```python
def collect_public_github_latest_commit(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubLatestCommitCollectionResult:
```

The collector version is `public-github-latest-commit.v1`. Its source identity
is the exact commits endpoint including `?per_page=1`, and it performs exactly
one unauthenticated transport call.

A 200 response must be exact UTF-8 JSON with a top-level array of zero or one
element. One element must be an object containing:

* `sha`: exactly 40 lowercase ASCII hexadecimal characters;
* `url`: exactly an HTTPS `api.github.com` commit URL whose owner and repository
  compare ASCII case-insensitively with the requested canonical identity and
  whose final segment exactly equals `sha`;
* `commit`: an object;
* `commit.committer`: an object; and
* `commit.committer.date`: a nonempty, unpadded ISO 8601 string parsed by
  `datetime.fromisoformat` into an aware datetime.

No author-date fallback or type coercion is permitted. Unrelated JSON fields
are accepted and preserved. An available result retains the exact response
text, matching SHA256 digest, exact source timestamp spelling, parsed aware
instant, commit SHA, sanitized ETag, and HTTP 200 status.

An empty array is unavailable evidence with status 200 and the stable category
`repository_has_no_commits`; it contains no invented value, source snapshot,
digest, SHA, source timestamp, or ETag. A 404 is unavailable with the existing
`repository_not_publicly_available` category. A 409 is a nonretryable
`github_request_rejected` failure. Rate limiting, authorization, other 4xx,
5xx, timeout, connectivity, invalid response, and unexpected status use the
existing safe classifications. All nonavailable results are atomic and expose
no partial evidence or external error content.

Old commit dates remain current evidence at collection time. Commit age is a
later deterministic metric and is not evidence freshness.

## SQLite Schema Version 3

Fresh databases are created directly at exact schema version 3. Version 1 may
continue through the existing exact v1-to-v2 migration, but the new v3
migration itself accepts only the exact supported version 2 schema. The v2 to
v3 migration runs in one `BEGIN IMMEDIATE` transaction, rebuilds only the
tables whose constraints change, copies rows in primary-key order, verifies
every copied archived and license value, verifies exact table definitions and
foreign keys, and sets `PRAGMA user_version = 3` last. Any failure rolls back
to the complete usable version 2 database.

Version 3 adds `latest_commit_timestamp_value TEXT` to `evidence_records`.
Available evidence must populate exactly the typed column matching its kind;
unavailable evidence populates no typed value column. The existing source
snapshot `repository_source_id` slot stores the concrete source object ID for
this collector: the commit SHA. Its meaning is also made explicit in
provenance, together with the exact source committer-date representation.
No generic evidence table, repository layer, ORM, or migration framework is
introduced.

## Persistence Contract

Add:

```python
def persist_github_latest_commit_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubLatestCommitCollectionResult,
) -> Optional[EvidenceRecord]:
```

The operation requires the matching durable request and persists every
terminal attempt. Available results atomically store the attempt, exact full
response bytes, and compact evidence. Empty-array and repository-404 results
atomically store the attempt and unavailable evidence. Other failures store
only the attempt.

Available compact evidence is canonical JSON shaped as
`{"value":"<datetime.isoformat()>"}`. Provenance contains the deterministic
source snapshot ID, source digest, commit SHA, and exact source committer-date
text. The evidence freshness basis is collection time and status is current.
Empty-array unavailable evidence uses reason and category
`repository_has_no_commits`; repository 404 retains its existing category.

After commit or exact replay, close and reopen the database. Recompute the full
response digest from reopened bytes, reparse the response, revalidate its
shape, SHA, URL binding, and committer date, reconstruct the transient result,
reconstruct the unchanged `EvidenceRecord`, and compare all attempt, source,
snapshot, value, timestamp, provenance, relationship, and version fields.
Only this reopened record is returned. Equivalent instants with different raw
timestamp representations are different material source content and therefore
conflict under the established exact replay rules.

## Tests

`tests/test_github_latest_commit_collection.py` will cover exactly one patched
request, the valid timestamp and committer-date precedence, exact source
timestamp spelling, empty arrays, overfull arrays, invalid JSON shapes and
fields, SHA and URL binding, invalid or naive dates, unrelated fields, exact
bytes and digest, 404, 409, rate limit, authorization, server, timeout,
connectivity, malformed responses, contradictory construction, and atomic
failure fields without live network access.

`tests/test_sqlite_latest_commit_persistence.py` will use real temporary
on-disk databases to cover fresh v3 creation, exact v2 migration, archived and
license row preservation, rollback, unsupported and altered schemas, required
request, available and both unavailable outcomes, failure-only attempts, exact
full and compact snapshots, SHA provenance, exact timestamp representation,
atomic rollback, replay and conflict behavior, source/value/snapshot/
provenance/relationship/version corruption, archived and license regressions,
and absence of network access.

## Acceptance Criteria

* Collector validation is strict and noncoercing and uses exactly one patched
  transport call.
* Complete source responses remain separate from compact evidence.
* Schema v3 is exact; v2 migration is atomic and preserves all prior rows.
* Every terminal outcome is durable with the required atomic shape.
* Evidence is returned only after close, reopen, reconstruction, and complete
  verification.
* Exact replay is idempotent; conflicting replay changes no durable content.
* All prior tests, compilation, and whitespace checks pass.

## Risks and Rollback

The GitHub commits endpoint has no response-size limit in this prototype, and
the 40-character SHA rule deliberately supports current public GitHub SHA-1
commit identifiers only. If GitHub introduces another canonical commit-ID
shape, a versioned collector change is required. SQLite corruption is detected
but not repaired. The v3 migration rolls back transactionally; code rollback
requires using a database that has not already been migrated or forward code
that understands v3.

## Explicit Exclusions

No security-policy collector, workflow orchestration, evaluator integration,
metric or policy persistence, API, CLI, retry execution, audit event,
reporting, model integration, ORM, repository or provider abstraction, generic
evidence storage, production database design, or live-network test is added.
