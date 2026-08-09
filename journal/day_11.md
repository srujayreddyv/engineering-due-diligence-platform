# Day 11 Journal

## Work Completed

Implemented GitHub-effective security-policy-presence collection and concrete
SQLite persistence. The new public contracts are:

```python
@dataclass(frozen=True)
class GitHubSecurityPolicySourceObservation:
    ...

@dataclass(frozen=True)
class GitHubSecurityPolicyPresenceCollectionResult:
    ...

def collect_public_github_security_policy_presence(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubSecurityPolicyPresenceCollectionResult:

def persist_github_security_policy_presence_collection(
    database_path: str | os.PathLike[str],
    collection_result: GitHubSecurityPolicyPresenceCollectionResult,
) -> Optional[EvidenceRecord]:
```

For this prototype, `SECURITY_POLICY_PRESENT` means that GitHub exposes an
effective `SECURITY.md` either in the assessed repository or through the
owner's public `.github` community-health repository. It records presence only;
it does not assess policy content, response capability, or repository security.

## Ordered Collection Behavior

The collector first verifies the assessed repository through
`GET /repos/<owner>/<repository>`. Only a strict positive non-Boolean `id` and
case-insensitively bound `full_name` permit policy probing.

It then checks these locations in order:

1. target `.github/SECURITY.md`;
2. target `SECURITY.md`;
3. target `docs/SECURITY.md`;
4. owner `.github` repository `.github/SECURITY.md`;
5. owner `.github` repository `SECURITY.md`; and
6. owner `.github` repository `docs/SECURITY.md`.

Duplicate probes are removed when the assessed repository is the owner's
`.github` repository. The first valid file produces available `True`. A
verified repository followed by 404 at every distinct candidate produces
available `False`. Assessed-repository 404 produces unavailable evidence;
candidate 404 responses remain ordered negative observations. Any rate limit,
authorization error, timeout, connectivity error, server failure, malformed
response, or unexpected status stops the search and produces no Boolean
evidence.

Policy-file payload validation is strict and noncoercing: the response must be
an object with `type == "file"`, exact `SECURITY.md` name and expected path, a
nonnegative non-Boolean size, a lowercase 40-character Git object SHA, and an
API URL bound to the expected repository and path. Owner and repository casing
compare ASCII case-insensitively; the content path remains exact.

## Source Preservation and Sanitization

Every HTTP 200 observation preserves the exact response bytes and matching
SHA256 digest. Exact UTF-8 text is retained when decoding succeeds; malformed
non-UTF-8 bytes are stored with a `binary` encoding marker and remain durable
for auditability. Malformed 200 responses never become evidence. Unrelated
valid response fields are retained without reserialization.

HTTP error bodies are never read or persisted. Only ordered safe observation
metadata, sanitized headers, stable classifications, and constant messages are
exposed. Transport exception text, credentials, SQL details, database paths,
and operating-system messages remain outside public errors.

## SQLite Schema Version 4

Fresh databases now use exact schema version 4. Version 4 adds:

* `security_policy_present_value` as the dedicated strict Boolean evidence
  column;
* `github_source_observations` for ordered probe roles, endpoints, statuses,
  sanitized ETags, failure categories, and source-snapshot links; and
* multiple source snapshots per collection attempt while retaining all prior
  relationships and integrity constraints.

An exact version 3 database migrates within one explicit transaction. Archived,
license, and latest-commit requests, attempts, snapshots, evidence, digests,
provenance, versions, and timestamp representations are copied and compared in
stable primary-key order. Schema definitions and foreign keys are verified
before `PRAGMA user_version` becomes 4. Any migration failure rolls back and
leaves the exact version 3 database intact and usable.

## Persistence, Authority, and Replay

Available `True` and `False` outcomes atomically persist the collection
attempt, complete ordered observations, every HTTP 200 source snapshot, and
compact `{"value":true}` or `{"value":false}` evidence. Assessed-repository
404 atomically persists the attempt, observation, and unavailable evidence.
Other terminal failures persist the attempt and all completed observations but
no evidence.

After commit or replay, SQLite is closed and reopened. Verification reconstructs
the exact observation order, recomputes every response digest, reparses every
decodable response, revalidates repository and path binding, checks the strict
Boolean normalization and compact digest, reconstructs provenance and the
unchanged `EvidenceRecord`, and verifies all relationships and versions. Only
this reopened result is authoritative. Exact replay creates no duplicate rows;
any material change conflicts without mutating durable history.

## Review Findings and Corrections

Final review corrected two material issues:

1. malformed non-UTF-8 HTTP 200 bodies were originally classified safely but
   discarded; the frozen observation and persistence path now retain exact
   bytes, digest, and an accurate `binary` encoding marker without creating
   evidence; and
2. Contents API URL binding originally required exact owner/repository casing
   and could raise on malformed URLs; it now accepts GitHub's canonical casing
   rules, keeps the content path exact, and converts malformed URLs into the
   sanitized invalid-response classification.

Review confirmed the approved probe order, local and inherited detection,
candidate-404 semantics, fail-closed incomplete searches, atomic writes,
transactional migration, close-and-reopen authority boundary, exact replay,
conflict behavior, and regression behavior for all three earlier evidence
kinds.

## Verification

Thirteen focused collector tests and fifteen focused persistence tests cover
the ordered search, strict validation, exact bytes, malformed responses,
failure behavior, schema creation and migration, rollback, atomic writes,
reopen verification, replay, corruption detection, prior-kind regressions, and
absence of live network calls.

The complete suite passes:

```text
Ran 205 tests
OK
```

Compilation and whitespace verification also pass.

## Risks and Explicit Exclusions

The bounded GitHub requests are not one atomic external snapshot, and complete
absence requires up to seven requests. Inherited policy can change independently
of the assessed repository. Response sizes are not explicitly bounded, current
policy blob validation accepts 40-character lowercase Git object identifiers,
and SQLite corruption is detected rather than repaired.

Day 11 added no workflow orchestration, durable evaluator integration, metric
or policy persistence, API, CLI, retry execution, audit event, reporting, model
behavior, ORM, repository or provider abstraction, production infrastructure,
or live-network test.

All four evidence kinds required by the deterministic evaluator are now
durable: repository archived, license status, latest commit timestamp, and
security policy presence.

## Next Task

The exact next task is a read-only Day 12 direction review for loading the
authoritative four-kind evidence set from SQLite and connecting it to the
existing deterministic evaluation boundary. Do not begin workflow orchestration
or Day 12 implementation before that review.
