# Day 6 Journal

## Work Completed

Implemented and reviewed one transient public GitHub repository metadata
collection boundary for:

```text
GET https://api.github.com/repos/<owner>/<repository>
```

The new public contracts in `engineering_due_diligence.github` are:

* immutable `GitHubCollectionOutcome` with `available`, `unavailable`,
  `failed_retryable`, and `failed_nonretryable` outcomes;
* frozen `GitHubRepositoryMetadataCollectionInput` containing the assessment,
  canonical repository identity, collection-attempt identity and number, and
  exact aware attempt timestamp;
* frozen `GitHubRepositoryMetadataCollectionError` containing a locked safe
  category, retryability, message, and optional sanitized retry guidance;
* frozen `GitHubRepositoryMetadataCollectionResult` containing one complete
  available, unavailable, or failed transient result; and
* `collect_public_github_repository_metadata`, which performs exactly one call
  through the private standard-library HTTP seam.

The module has one private `urllib` transport seam. It performs an
unauthenticated GET with no authorization header. All focused collector tests
patch this seam, and no test performs a live GitHub request.

## Successful Collection Behavior

The collector accepts only the canonical post-Day-5 identity:

```text
github.com/<owner>/<repository>
```

It does not reparse a submitted URL or duplicate Day 5 locator normalization.
Owner and repository casing are retained in the requested API source identity.

Only HTTP 200 can produce an available result. The response must be valid
strict JSON with:

* `id` as a positive nonboolean integer;
* `full_name` as one ASCII owner/repository pair matching the requested pair
  case-insensitively; and
* `archived` as a JSON Boolean.

Unrelated valid GitHub fields are accepted. The collector preserves the exact
successful UTF-8 response text rather than rebuilding a reduced payload. The
result also preserves its matching SHA256 digest, GitHub repository source ID,
archived status, source API identity, collector version, collection-attempt
metadata, HTTP 200 status, and a sanitized ETag when present.

The only collected evidence kind is
`EvidenceKind.REPOSITORY_ARCHIVED`. License, latest-commit, and security-policy
collection remain unimplemented.

## Failure Classifications

The collector returns these locked structured outcomes:

| External outcome | Collection result |
| --- | --- |
| HTTP 404 | `unavailable` with `repository_not_publicly_available`; it does not claim nonexistent versus private |
| Rate-limit-marked HTTP 403 or HTTP 429 | `failed_retryable` with `github_rate_limited` |
| HTTP 401 or non-rate-limit HTTP 403 | `failed_nonretryable` with conditionally retryable `github_authorization_failed` |
| Other HTTP 4xx | `failed_nonretryable` with `github_request_rejected` |
| HTTP 5xx | `failed_retryable` with `github_server_error` |
| Direct or wrapped timeout | `failed_retryable` with `github_timeout` |
| Recognized connectivity failure | `failed_retryable` with `github_connectivity_failure` |
| Invalid UTF-8, JSON, required field, or repository binding | `failed_nonretryable` with conditionally retryable `github_response_invalid` |
| Other delivered HTTP status | `failed_nonretryable` with conditionally retryable `github_unexpected_status` |

The collector classifies retryability but performs no automatic retry, delay,
backoff, scheduling, or workflow transition.

## Sanitization and Atomic Results

HTTP error bodies are never read by the private transport seam. The collector
never copies response bodies, reason phrases, authorization data, credentials,
or exception messages into an error. Error categories and messages are locked
module values. Only validated `Retry-After` guidance may appear on rate-limit
or server failures.

Available ETags and retry guidance are accepted only after printable ASCII and
line-break checks. Rate-limit detection requires a sanitized exact
`X-RateLimit-Remaining` value of `0`.

An available result requires the source ID, strict Boolean archived value,
exact snapshot, matching digest, HTTP 200 status, and no error. Its constructor
revalidates that the raw snapshot's required fields match the normalized result
and requested repository.

Every unavailable or failed result contains no repository source ID, archived
value, raw snapshot, digest, or ETag. Direct result construction rejects
contradictory status, category, retryability, source, version, evidence kind,
snapshot, digest, or partial-evidence combinations.

## Review Findings and Corrections

Review confirmed exactly one private transport call per collection, patched
transport use in every focused collector test, strict noncoercing payload
types, compatibility with unrelated response fields, exact snapshot/digest
agreement, complete result atomicity, safe classifications, and no public
transport abstraction.

Two material issues were found and corrected during Day 6:

1. Header trimming initially occurred before CR/LF validation. A malicious
   `Retry-After` prefix could therefore be stripped into apparently safe text.
   Header values are now rejected for nonprintable or line-break content before
   trimming.
2. HTTP 403 rate-limit detection initially stripped
   `X-RateLimit-Remaining` without applying the complete safe-header rules. It
   now requires a sanitized exact value of `0`; unsafe or other values follow
   the authorization-failure path.

Regression cases cover both corrections. Final review found no remaining
material correctness, security, compatibility, or scope issue.

## Transient Boundary

`GitHubRepositoryMetadataCollectionResult` is a transient collection-operation
value. It is not an authoritative `EvidenceRecord`, does not have an evidence
identifier, and makes no durability claim. It cannot enter the existing Day 3
metric or policy evaluation or Day 4 result assembly until a later persistence
boundary stores the raw evidence and creates a complete authoritative record.

No Day 5 request-validation behavior changed. The collector checks only the
canonical identity shape and never accepts or reparses a submitted locator.

## Verification

Thirteen focused Day 6 tests and all 88 repository tests pass:

```text
Ran 13 tests
OK

Ran 88 tests
OK
```

Python bytecode compilation and whitespace verification pass. The tests patch
the private transport seam, so verification uses no live network access.

## Explicit Exclusions

Day 6 did not implement:

* authoritative `EvidenceRecord` construction, evidence identifiers, or
  persistence;
* database schemas, migrations, repositories, transactions, filesystem or
  object storage, or durability receipts;
* workflow states, transitions, retries, backoff, scheduling, resumption, or
  interruption handling;
* audit events, audit persistence, observability, or telemetry;
* metric calculation, policy evaluation, Day 4 result assembly, or application
  service integration using the transient capture;
* license, latest-commit, security-policy, vulnerability, release, contributor,
  or other GitHub evidence collectors;
* authenticated or private repositories, GitHub Apps, OAuth, tokens,
  enterprise GitHub, GitLab, or provider abstractions;
* request-validation changes, APIs, CLI commands, reports, AI/model behavior,
  human review, or human decisions; or
* FastAPI, Pydantic, new dependencies, Docker, deployment, or infrastructure.

## Exact Next Task

Perform a read-only persistence direction review. Do not begin persistence
implementation as part of Day 6 finalization.
