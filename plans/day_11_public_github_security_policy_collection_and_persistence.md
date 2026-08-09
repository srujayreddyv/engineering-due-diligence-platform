# Day 11 Public GitHub Security Policy Collection and Persistence Plan

## Task

Implement GitHub-effective security-policy presence collection and the concrete
SQLite persistence slice that makes every terminal outcome durable.

## Objective

Verify the assessed public repository, probe GitHub's supported `SECURITY.md`
locations in documented precedence order, include the owner's public `.github`
repository defaults, and normalize the complete observation sequence into the
existing `EvidenceKind.SECURITY_POLICY_PRESENT` Boolean contract.

## Collector Contract

Reuse `GitHubRepositoryMetadataCollectionInput`, `GitHubCollectionOutcome`, the
existing sanitized error contract, and the private standard-library transport
seam. Add frozen security-policy source-observation and result contracts plus:

```python
def collect_public_github_security_policy_presence(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubSecurityPolicyPresenceCollectionResult:
```

The collector first calls `GET /repos/<owner>/<repository>` and strictly
validates a positive non-Boolean integer `id` plus a case-insensitively bound
`full_name`. It then probes, in order:

1. target `.github/SECURITY.md`;
2. target `SECURITY.md`;
3. target `docs/SECURITY.md`;
4. owner `.github` repository `.github/SECURITY.md`;
5. owner `.github` repository `SECURITY.md`;
6. owner `.github` repository `docs/SECURITY.md`.

Duplicate source identities are removed when the assessed repository is the
owner's `.github` repository. The first strict policy-file response stops the
search. A valid file is an exact JSON object with `type == "file"`, exact name
and path, a nonnegative non-Boolean integer size, a lowercase 40-character Git
object SHA, and an exact API URL bound to the probed repository and path.
Unrelated fields are accepted.

Each request produces one ordered frozen observation. HTTP 200 observations
preserve exact response bytes and their SHA256 digest, plus exact UTF-8 text
when decoding succeeds, a sanitized ETag for valid payloads, and the validated
repository or blob source ID. Malformed HTTP 200 bytes remain auditable but
never become evidence. Expected candidate 404 observations preserve only safe
request identity, role, sequence, and status. Error bodies are never read or
exposed. GitHub-returned owner and repository casing compare ASCII
case-insensitively while the expected content path remains exact.

A valid policy is available `True`; a verified target followed by 404 for every
distinct candidate is available `False`. Target repository 404 is unavailable.
Rate limits, timeouts, connectivity failures, and server errors are retryable.
Authorization failures, other rejected requests, malformed responses, and
unexpected statuses are nonretryable. An incomplete search never becomes
`False` and never contains a partial Boolean value.

## SQLite Schema Version 4

Fresh databases create exact schema version 4. Only an exact version 3 schema
migrates directly to version 4, in one explicit transaction. Existing version
1 and 2 paths may advance through their already supported migrations first.

Version 4:

* permits `security_policy_present` in attempts and evidence;
* adds strict `security_policy_present_value INTEGER` typed storage;
* removes the one-snapshot-per-attempt uniqueness restriction while retaining
  snapshot and attempt relationships; and
* adds `github_source_observations` for ordered source roles, identities,
  statuses, sanitized ETags, safe error categories, and optional links to full
  source snapshots.

Available evidence populates only the typed column matching its kind.
Unavailable evidence populates none. Existing archived, license, and latest
commit rows retain every prior field exactly. Schema definitions, copied rows,
and foreign keys are verified before `PRAGMA user_version = 4` is set. Any
failure rolls back completely and leaves version 3 usable.

## Persistence Contract

Add:

```python
def persist_github_security_policy_presence_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubSecurityPolicyPresenceCollectionResult,
) -> Optional[EvidenceRecord]:
```

A matching durable request is required. Available `True` and `False` outcomes
atomically store the attempt, every observation, every complete HTTP 200 source
snapshot, and compact evidence. Target repository 404 atomically stores the
attempt, observation, and unavailable evidence. Other failures atomically
store the attempt and completed observations but no evidence.

The compact snapshot is exactly `{"value":true}` or `{"value":false}`.
Provenance records the ordered observation identifiers and digests, policy
scope and path when present, and the policy blob SHA. The decisive full source
snapshot is the policy response for `True` and the verified repository response
for `False`.

After commit or replay, close and reopen SQLite. Recompute every full response
digest, reparse every stored response, replay the exact ordered search,
revalidate source binding and normalization, reconstruct the transient result,
and reconstruct the unchanged `EvidenceRecord`. Only completely verified
available or unavailable evidence is returned. Exact replay adds no rows; any
changed request, observation order, role, identity, status, body, digest, ETag,
error, value, provenance, relationship, timestamp, or version conflicts without
mutation.

## Tests

Collector tests cover repository verification, all local and inherited paths,
precedence and short-circuiting, `.github` deduplication, complete absence,
target 404, candidate 404 behavior, strict payload typing and binding, exact
response preservation, failure classification, no partial Boolean value,
contract invariants, ordered observations, and no live network calls.

Persistence tests use real temporary on-disk databases and cover fresh v4,
exact v3 migration, preservation and regression of all three prior evidence
kinds, migration rollback, matching requests, durable local and inherited
presence, durable absence and unavailability, failure-only persistence,
multiple snapshots and ordered 404 observations, atomic rollback, close/reopen
verification, exact replay, conflicting replay, and corruption of source,
digest, order, value, provenance, relationship, and version fields.

## Acceptance Criteria

* Collection is strict, noncoercing, bounded, ordered, and fail closed.
* Every completed request is represented without reading HTTP error bodies.
* Full successful responses remain separate from compact evidence.
* Schema v4 migration is atomic and preserves all version 3 content.
* Evidence becomes authoritative only after close, reopen, reconstruction, and
  complete verification.
* Exact replay is idempotent and conflicting replay changes no history.
* All existing tests, compilation, and whitespace verification pass.

## Risks and Rollback

The bounded requests are not a single atomic GitHub view, and a negative result
uses up to seven public API calls. Inherited policy can change independently of
the assessed repository. The collector deliberately accepts regular file
objects and current 40-character Git object identifiers only. SQLite corruption
is detected but not repaired. Migration failure rolls back to version 3; code
rollback requires an unmigrated database or forward code that understands v4.

## Explicit Exclusions

No workflow orchestration, evaluator integration, metric or policy
persistence, API, CLI, retry execution, audit events, reporting, model
behavior, ORM, repository or provider abstraction, generic source framework,
production infrastructure, or live-network test is added.
