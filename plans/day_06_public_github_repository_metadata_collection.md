# Day 6 Public GitHub Repository Metadata Collection Plan

## Task

Implement one transient public GitHub repository-metadata collection boundary
for:

```text
GET https://api.github.com/repos/<owner>/<repository>
```

The boundary collects only `EvidenceKind.REPOSITORY_ARCHIVED`, preserves the
exact successful response text and its digest, and returns complete structured
collection outcomes without persistence, workflow, audit, or deterministic
assessment evaluation.

## Objective

Add the smallest real external-source boundary after Day 5 request validation.
Given a canonical post-validation repository identity and explicit collection
attempt metadata, the collector will make one unauthenticated public GitHub
request and return exactly one immutable available, unavailable, retryable
failure, or nonretryable failure result.

Success means:

* a valid HTTP 200 GitHub repository response containing correctly typed `id`,
  `full_name`, and `archived` fields produces one complete available capture;
* the available capture preserves the exact decoded response text, a matching
  SHA256 digest, the authoritative GitHub repository identifier, archived
  status, source identity, and safe response metadata;
* 404, rate limiting, other 4xx responses, 5xx responses, timeout, connectivity,
  malformed response, and semantic mismatch outcomes are classified into
  stable structured results;
* unavailable and failed outcomes contain no partial repository source ID,
  archived value, raw snapshot, digest, or ETag;
* transport exceptions and external response bodies never escape through
  structured error text;
* the thirteen focused tests pass without live network access; and
* all existing 75 tests continue to pass unchanged.

The result is a transient collection-operation value. It is not an
authoritative persisted `EvidenceRecord` and must not be supplied to metric or
policy evaluation before a later persistence boundary makes raw evidence
durable.

## Current State

Day 3 provides frozen `AssessmentContext`, `EvidenceRecord`, `MetricResult`,
and `PolicyFinding` values plus deterministic metric and policy evaluation over
four local fixture evidence kinds. `EvidenceKind.REPOSITORY_ARCHIVED` already
exists and its available value must be a strict Python boolean.

Day 4 provides a transient complete `DeterministicAssessmentResult` over an
already supplied evidence set. It does not collect or persist evidence.

Day 5 provides `validate_assessment_request`, which accepts a locked HTTPS
GitHub submitted-locator grammar and produces the canonical identity:

```text
github.com/<owner>/<repository>
```

Day 5 intentionally performs no network access, existence check, visibility
check, or source-ID resolution. It preserves owner and repository casing in
the canonical identity.

No HTTP client abstraction, GitHub collector, dependency manifest, persistence
layer, workflow engine, audit event, application API, or live-network test
exists. The package remains dependency-free and uses the standard library.

The durable boundaries require:

* authoritative source facts to be collected and normalized by deterministic
  collector software;
* raw responses or relevant snapshots and integrity digests to be preserved;
* unavailable and failure outcomes to remain explicit;
* errors to be sanitized and never contain credentials, authorization data, or
  unnecessary external payloads;
* raw evidence to be durable before metrics or conclusions use it; and
* external collectors to have mocked failure tests.

## Locked Assumptions

1. Day 6 supports only unauthenticated public GitHub repository metadata.
2. The only endpoint is
   `GET https://api.github.com/repos/<owner>/<repository>`.
3. The only evidence kind is `EvidenceKind.REPOSITORY_ARCHIVED`.
4. The input repository identity is the canonical output shape established by
   Day 5, not an arbitrary submitted URL.
5. The collector validates only the canonical identity boundary. It does not
   call `urlsplit`, accept schemes, normalize browser URLs, or reproduce Day 5
   submitted-locator validation.
6. Canonical owner and repository segments use the same ASCII segment grammar
   already accepted by Day 5: letters, digits, `.`, `_`, and `-`; `.` and `..`
   segments and a case-insensitive `.git` repository suffix remain invalid.
7. GitHub repository owner and name comparison is ASCII case-insensitive.
   The returned `full_name` must have exactly one owner segment and one
   repository segment in the locked ASCII grammar, and its `casefold()` value
   must equal the requested `owner/repository`. Casing differences alone are
   accepted. The requested canonical identity is not rewritten from the
   response.
8. `id` is the authoritative GitHub repository identifier for this boundary.
   It must be a positive nonboolean JSON integer and is returned as a decimal
   string so the public result uses an opaque source identifier.
9. `archived` must be a JSON boolean. Numeric `0` and `1`, strings, null, and
   truthy values are invalid.
10. The successful payload must be a JSON object containing `id`, `full_name`,
    and `archived`. Unrelated fields are allowed with any valid JSON shape and
    remain untouched in the exact raw snapshot.
11. Only a valid HTTP 200 response can become available. Other successful or
    redirect statuses that reach the collector are unexpected-status failures.
12. The standard-library transport follows its normal redirect behavior. Day
    6 does not implement custom redirect policy or expose redirect history.
13. The private HTTP seam makes no authenticated request and adds no
    authorization or credential header.
14. `attempted_at` is supplied by the caller, must be timezone-aware, and is
    preserved exactly. Day 6 adds no clock abstraction.
15. Input-contract violations and contradictory direct result construction are
    programmer errors and raise `ValueError`. Ordinary GitHub and transport
    failures return structured collection results.
16. The collector performs one HTTP attempt. It classifies retryability but
    never sleeps, retries, backs off, schedules, or changes workflow state.
17. The collection result is not an `EvidenceRecord`, persisted record, or
    proof that persistence succeeded.

## Proposed Solution

### Module boundary

Add `engineering_due_diligence.github` containing exactly four immutable
public value contracts and one public collector function. Do not add package
root exports.

Private constants, validation helpers, response-normalization helpers, and the
single private HTTP seam may exist only to implement these contracts. Do not
add a public GitHub client, transport protocol, response wrapper, service
object, repository abstraction, retry policy, or exception hierarchy.

### Public contract 1: `GitHubCollectionOutcome`

```python
class GitHubCollectionOutcome(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NONRETRYABLE = "failed_nonretryable"
```

The enum is immutable and contains exactly these four values. `partial` is not
supported because this one-fact collector either has a complete valid archived
status or has no usable evidence.

### Public contract 2: `GitHubRepositoryMetadataCollectionInput`

```python
@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionInput:
    assessment_id: str
    repository_identity: str
    collection_attempt_id: str
    attempt_number: int
    attempted_at: datetime
```

The input constructor enforces:

* `assessment_id` and `collection_attempt_id` are exact strings, nonempty after
  stripping, and have no leading or trailing whitespace;
* `repository_identity` is an exact string in canonical
  `github.com/<owner>/<repository>` form with no scheme, port, query, fragment,
  trailing slash, whitespace, control character, Unicode, `.git` suffix, dot
  segment, or extra component;
* `attempt_number` has exact type `int`, is not `bool`, and is greater than
  zero; and
* `attempted_at` is a `datetime` whose timezone provides a usable UTC offset.

The constructor does not change any supplied value. In particular, it
preserves the repository owner and name casing and the exact aware datetime
object. Invalid input is caller misuse at this post-Day-5 internal boundary and
raises a stable `ValueError`; it is not classified as a GitHub collection
failure.

### Public contract 3: `GitHubRepositoryMetadataCollectionError`

```python
@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionError:
    category: str
    retryability: str
    message: str
    retry_after: Optional[str] = None
```

The error constructor enforces:

* `category` is exactly one category in the locked error-message table below;
* `message` equals that category's exact module-owned message;
* `retryability` equals that category's exact value in the locked failure
  classification table;
* `retry_after`, when present, is a nonempty safe response-header value; and
* `retry_after` is permitted only for `github_rate_limited` or
  `github_server_error`;
* no field is derived from an exception message or response body.

Error messages are stable, generic, and safe for a future human-facing layer.
They may identify the source category and consequence but never contain the
requested authorization header, credentials, external response body, raw
exception text, or protected diagnostic detail.

### Public contract 4: `GitHubRepositoryMetadataCollectionResult`

```python
@dataclass(frozen=True)
class GitHubRepositoryMetadataCollectionResult:
    request: GitHubRepositoryMetadataCollectionInput
    outcome: GitHubCollectionOutcome
    evidence_kind: EvidenceKind
    collector_version: str
    source_identity: str
    repository_source_id: Optional[str]
    archived: Optional[bool]
    raw_snapshot: Optional[str]
    integrity_digest: Optional[str]
    response_status: Optional[int]
    response_etag: Optional[str]
    error: Optional[GitHubRepositoryMetadataCollectionError]
```

The module owns one private collector-version constant with the exact locked
value `public-github-repository-metadata.v1`. The result exposes that value but
does not add another public version contract.

`source_identity` is always the exact requested API URL:

```text
https://api.github.com/repos/<owner>/<repository>
```

The result constructor enforces all common and outcome-specific invariants.

Common invariants:

* `request` has the exact input-contract type;
* `outcome` has the exact outcome-enum type;
* `evidence_kind` is exactly `EvidenceKind.REPOSITORY_ARCHIVED`;
* `collector_version` equals the locked module version;
* `source_identity` equals the deterministic API URL derived from the request;
* `response_status`, when present, is a nonboolean integer from 100 through
  599; and
* `response_etag`, when present, is a nonempty string and is allowed only for
  an available result; and
* every nonavailable result's outcome, status, error category, retryability,
  and retry-guidance allowance match exactly one row in the locked failure
  classification table.

Available-result invariants:

* `response_status == 200`;
* `repository_source_id` is a nonempty decimal string representing a positive
  integer in canonical decimal form: it contains ASCII digits only and equals
  `str(int(repository_source_id))`, with an integer value greater than zero;
* `archived` has exact type `bool`;
* `raw_snapshot` has exact type `str` and is the exact UTF-8 response text;
* `integrity_digest` equals the lowercase hexadecimal SHA256 digest of
  `raw_snapshot.encode("utf-8")`;
* the same private pure payload validator used by the collector confirms that
  the raw snapshot's `id`, `full_name`, and `archived` fields match the result's
  repository source ID, requested repository identity, and archived value;
* `response_etag` may be present when the source supplied it; and
* `error is None`.

Unavailable-result invariants:

* `response_status == 404`;
* `error` is present with category `repository_not_publicly_available` and
  retryability `conditionally_retryable`; and
* `repository_source_id`, `archived`, `raw_snapshot`, `integrity_digest`, and
  `response_etag` are all `None`.

Failed-result invariants:

* `error` is present;
* `FAILED_RETRYABLE` requires `error.retryability == "retryable"`;
* `FAILED_NONRETRYABLE` requires `error.retryability` to equal either
  `"nonretryable"` or `"conditionally_retryable"` according to the locked
  category table;
* a status-bearing HTTP failure preserves only the numeric response status and
  selected safe retry guidance;
* timeout and connectivity failures have `response_status is None`; and
* `repository_source_id`, `archived`, `raw_snapshot`, `integrity_digest`, and
  `response_etag` are all `None`.

Contradictory direct construction raises `ValueError`. There is no result shape
that contains partial evidence.

### Collector function

```python
def collect_public_github_repository_metadata(
    request: GitHubRepositoryMetadataCollectionInput,
) -> GitHubRepositoryMetadataCollectionResult:
```

The collector:

1. requires the exact input-contract type;
2. derives the owner, repository, and exact API URL from the already canonical
   identity without parsing or normalizing a submitted URL;
3. calls the private HTTP seam exactly once;
4. classifies known HTTP and transport outcomes;
5. for HTTP 200, decodes the body as UTF-8, parses JSON, validates only the
   three required fields and their binding to the request, and preserves all
   unrelated JSON fields in the untouched raw text;
6. computes the digest from the exact successful decoded text;
7. returns one complete invariant-valid result; and
8. does not catch or translate unexpected internal programming or invariant
   exceptions merely to make them appear like ordinary external failures.

No available result is constructed until UTF-8 decoding, JSON parsing, all
three required field checks, casing-aware repository binding, and digest
calculation have succeeded.

### Canonical identity and casing rules

The collector accepts only:

```text
github.com/<owner>/<repository>
```

It applies a direct anchored canonical-identity pattern. It does not use
`urlsplit` and does not accept `https://`, a submitted locator, a trailing
slash, or any alternate host form. This is a post-validation precondition,
not a second request validator.

The requested comparison name is the canonical identity without the
`github.com/` prefix:

```text
<owner>/<repository>
```

For a successful response, `full_name` must:

1. have exact JSON/Python type `str`;
2. contain exactly one `/` separating nonempty owner and repository segments;
3. use only the locked ASCII segment characters;
4. contain neither `.` nor `..` as a complete segment;
5. not end in `.git` case-insensitively; and
6. satisfy
   `returned_full_name.casefold() == requested_full_name.casefold()`.

Thus `github.com/Example/Repository` accepts a response `full_name` of
`example/repository`, but `example/another-repository`, an extra path
component, Unicode lookalike, or punctuation outside the grammar fails closed.
The collection input and source identity retain the requested casing. The raw
snapshot retains the response casing. Day 6 does not recanonicalize or mutate
the Day 5 identity.

### Successful payload rules

The exact HTTP 200 body must be valid UTF-8 and parse as one strict JSON object.
The JSON parser must reject nonstandard `NaN`, `Infinity`, and `-Infinity`
constants rather than accepting Python's permissive defaults. Only these
fields are required:

| Field | Locked rule | Normalized output |
| --- | --- | --- |
| `id` | Exact nonboolean integer greater than zero | Decimal `repository_source_id` string |
| `full_name` | Exact string matching the requested owner/repository under the locked ASCII case-insensitive rule | Binding check only; response value stays in raw snapshot |
| `archived` | Exact JSON boolean | Exact Boolean `archived` value |

Missing fields, a non-object top level, invalid UTF-8, malformed or nonstandard
JSON, null, Boolean or numeric coercion, string coercion, nonpositive IDs,
malformed `full_name`, repository mismatch, or nonboolean `archived` are
F07-style invalid external responses. They return a complete
failed-nonretryable collection outcome with
`retryability="conditionally_retryable"`, because a fresh source response or
corrected collector version is required before another attempt can be useful.

Extra GitHub fields must not be rejected, selected into a reduced snapshot, or
reserialized. The available result retains the exact response text, including
unrelated fields, field order, and insignificant JSON whitespace. The digest
is computed over that exact text encoded as UTF-8.

### Private standard-library HTTP seam

Implement exactly one patchable private transport function:

```python
def _get_public_github_repository(
    source_identity: str,
) -> tuple[int, Optional[bytes], tuple[tuple[str, str], ...]]:
```

The seam uses only `urllib.request`, `urllib.error`, and standard-library
network exception types. It:

* creates one unauthenticated GET request;
* uses a private fixed timeout;
* supplies only stable nonsecret headers needed for a public GitHub JSON
  request, including a `User-Agent` and JSON `Accept` value;
* never adds an `Authorization` header;
* on a normal response, returns the numeric status, exact response bytes, and
  only selected safe headers needed by the result (`ETag`, `Retry-After`, and
  `X-RateLimit-Remaining`);
* catches `urllib.error.HTTPError` only to return its status and selected safe
  headers, closes the response, and never reads or returns the error body; and
* lets timeout and connectivity exceptions reach the collector, where their
  types—not their messages—are mapped to sanitized structured outcomes.

The collector treats direct `socket.timeout` and `TimeoutError` values, plus a
`URLError` whose `reason` is one of those timeout types, as timeout. Other
`URLError` and `ConnectionError` values are connectivity failures. It does not
catch arbitrary `OSError` or `Exception` values as ordinary network failures.

Unit tests patch
`engineering_due_diligence.github._get_public_github_repository`. Do not add a
public transport protocol, HTTP client class, response class, dependency
injection container, or callable parameter to the collector.

### Failure classifications

Failure categories and messages are locked constants. The error message never
contains `str(exception)`, an HTTP reason phrase supplied by the server, a
response body, request headers, or credentials.

| Error category | Exact message |
| --- | --- |
| `repository_not_publicly_available` | `The repository is not available through the public GitHub endpoint.` |
| `github_rate_limited` | `GitHub rate limited the repository metadata request.` |
| `github_authorization_failed` | `GitHub did not authorize the public repository metadata request.` |
| `github_request_rejected` | `GitHub rejected the repository metadata request.` |
| `github_server_error` | `GitHub could not complete the repository metadata request.` |
| `github_timeout` | `The GitHub repository metadata request timed out.` |
| `github_connectivity_failure` | `The GitHub repository metadata request could not connect.` |
| `github_response_invalid` | `GitHub returned an invalid repository metadata response.` |
| `github_unexpected_status` | `GitHub returned an unexpected repository metadata status.` |

| Source outcome | Result outcome | Error category | Retryability | Preserved safe metadata |
| --- | --- | --- | --- | --- |
| HTTP 404 | `UNAVAILABLE` | `repository_not_publicly_available` | `conditionally_retryable` | Status only |
| HTTP 403 with `X-RateLimit-Remaining: 0` | `FAILED_RETRYABLE` | `github_rate_limited` | `retryable` | Status and sanitized `Retry-After` when present |
| HTTP 429 | `FAILED_RETRYABLE` | `github_rate_limited` | `retryable` | Status and sanitized `Retry-After` when present |
| HTTP 401 or non-rate-limit HTTP 403 | `FAILED_NONRETRYABLE` | `github_authorization_failed` | `conditionally_retryable` | Status only |
| Other HTTP 400–499 | `FAILED_NONRETRYABLE` | `github_request_rejected` | `nonretryable` | Status only |
| HTTP 500–599 | `FAILED_RETRYABLE` | `github_server_error` | `retryable` | Status and sanitized `Retry-After` when present |
| Socket timeout or `TimeoutError` | `FAILED_RETRYABLE` | `github_timeout` | `retryable` | No status or external detail |
| `URLError`, connection failure, or equivalent recognized connectivity error | `FAILED_RETRYABLE` | `github_connectivity_failure` | `retryable` | No status or external detail |
| Invalid UTF-8, malformed JSON, invalid required payload field, or requested-repository mismatch | `FAILED_NONRETRYABLE` | `github_response_invalid` | `conditionally_retryable` | HTTP 200 status only; no raw body |
| Any other status delivered by the seam | `FAILED_NONRETRYABLE` | `github_unexpected_status` | `conditionally_retryable` | Numeric status only |

HTTP 404 means only that the repository is not available through this
unauthenticated public collector. The result must not assert whether the
repository is nonexistent, private, renamed, access-restricted, or temporarily
hidden.

`Retry-After` is retained only when it is a stripped, nonempty printable ASCII
value without whitespace other than internal spaces. Invalid or unsafe header
content is discarded rather than copied. No other external header becomes
error text.

An available-response `ETag` is retained only when it is a stripped, nonempty
printable ASCII value containing no carriage return or newline. An invalid
ETag is discarded; it does not invalidate an otherwise valid evidence payload.

### Determinism and exception behavior

Network retrieval itself is external and nondeterministic. Normalization and
classification are deterministic: equal collection inputs and equal patched
HTTP seam outputs or recognized exception types produce equal result values.

The collector catches ordinary expected external conditions only:

* recognized HTTP statuses returned by the seam;
* UTF-8 decoding and JSON parsing failures;
* recognized timeout exceptions; and
* recognized connectivity exceptions.

It never parses exception messages. Unexpected exceptions indicating a bug,
broken invariant, or unsupported programming condition remain visible to the
caller and are not mislabeled as GitHub evidence.

## Files Affected

This planning task creates only:

* `plans/day_06_public_github_repository_metadata_collection.md` — this plan.

The later implementation is expected to create only:

* `src/engineering_due_diligence/github.py` — the four public contracts, one
  collector function, private validators and classifiers, and one private
  standard-library HTTP seam; and
* `tests/test_github_repository_metadata_collection.py` — exactly thirteen
  focused mocked-transport tests.

Do not modify existing Day 3, Day 4, or Day 5 source or tests during
implementation. README and journal updates belong to finalization after
implementation review, not the implementation step.

## Database Impact

None. Day 6 creates no schema, migration, repository, transaction, database
dependency, stored record, seed data, persistence receipt, or durability
claim.

The collection result is transient. It must not be called an authoritative
`EvidenceRecord`, and no existing or future evaluator may consume it until a
separate persistence boundary has stored the required evidence content and
created a complete durable record.

## Testing Strategy

Create exactly thirteen test methods in
`tests/test_github_repository_metadata_collection.py`. Every HTTP behavior is
tested by patching the one private seam; no test performs live network access.

1. `test_collection_contracts_are_frozen_and_input_invariants_are_enforced`
   verifies the outcome members, dataclass immutability, required text,
   canonical identity grammar, positive nonboolean attempt number, aware
   timestamp requirement, exact casing preservation, and exact timestamp
   preservation.
2. `test_valid_unarchived_response_returns_complete_available_capture`
   verifies one seam call, exact API URL, HTTP 200, source ID normalization,
   `archived=False`, archived evidence kind, collector version, no error, and
   the complete available result shape.
3. `test_valid_archived_response_returns_true_archived_capture` verifies that
   a strict JSON `true` becomes exact Python `True` without coercion.
4. `test_full_name_comparison_is_ascii_case_insensitive_and_source_identity_preserves_requested_casing`
   verifies that casing-only differences in `full_name` are accepted, that a
   requested mixed-case identity produces the same mixed-case API path, and
   that neither the input nor source identity is rewritten from the response.
5. `test_success_preserves_exact_raw_text_digest_etag_and_unrelated_fields`
   supplies a successful payload with realistic unrelated scalar, object, and
   array fields plus deliberate whitespace and field order; verifies the exact
   text is retained, the digest matches that exact text, the safe ETag is
   preserved, and no unrelated field causes rejection.
6. `test_invalid_success_payload_types_return_sanitized_failure_without_partial_evidence`
   table-tests invalid UTF-8, malformed JSON, non-object JSON, each missing
   required field, nonstandard JSON constants, Boolean/zero/negative/string
   IDs, nonstring or malformed `full_name`, and numeric/string/null `archived`;
   every case returns the locked F07-style result without source ID, archived
   value, snapshot, digest, ETag, raw body, or exception text.
7. `test_mismatched_full_name_fails_closed_without_partial_evidence` verifies
   that another repository, extra component, Unicode lookalike, dot segment,
   or `.git` response name is rejected even when `id` and `archived` are valid.
8. `test_404_is_unavailable_without_claiming_nonexistence_or_private_visibility`
   verifies the exact unavailable classification, safe generic message,
   absence of partial evidence, and discarded response body.
9. `test_rate_limit_403_and_429_are_retryable_with_only_safe_retry_guidance`
   verifies case-insensitive rate-limit header lookup, the locked F04-style
   classification, safe `Retry-After` retention, unsafe guidance rejection,
   and no response body or partial evidence.
10. `test_500_and_503_are_retryable_server_failures_without_partial_evidence`
    verifies stable F06-style server classification, status preservation, no
    body leakage, and no partial evidence.
11. `test_timeout_and_connectivity_failures_return_sanitized_retryable_results`
    table-tests socket timeout, `TimeoutError`, timeout-wrapped `URLError`,
    other `URLError`, and `ConnectionError`; verifies the timeout/connectivity
    split, that no exception escapes or message appears, and that no HTTP
    status or partial evidence is invented.
12. `test_authorization_and_other_4xx_responses_are_safely_classified`
    table-tests 401, non-rate-limit 403, and representative other 4xx values;
    verifies the locked category and retryability split, numeric status only,
    discarded bodies and headers, and no partial evidence.
13. `test_result_invariants_reject_contradictions_and_repeated_normalization_is_deterministic`
    directly attempts available results missing required content, unavailable
    or failed results containing partial content, wrong evidence kind, wrong
    source URL or collector version, mismatched digest, unsafe ETag placement,
    error/outcome retryability conflicts, and invalid response-status shapes;
    it also verifies that equal requests and equal patched successful or
    failure responses produce equal results.

Run focused verification:

```text
PYTHONPATH=src python3 -m unittest tests.test_github_repository_metadata_collection -v
```

Expected focused total:

```text
Ran 13 tests
OK
```

Run complete verification:

```text
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
git diff --check
```

Expected complete total:

```text
Ran 88 tests
OK
```

No test may depend on GitHub availability, current time, current repository
state, credentials, network access, response-field ordering imposed by Python,
or a persistence service.

## Acceptance Criteria

* `engineering_due_diligence.github` exposes exactly
  `GitHubCollectionOutcome`, `GitHubRepositoryMetadataCollectionInput`,
  `GitHubRepositoryMetadataCollectionError`,
  `GitHubRepositoryMetadataCollectionResult`, and
  `collect_public_github_repository_metadata` as its public contracts.
* The four value contracts are immutable and dependency-free.
* The public collector has exactly the planned input and return annotations and
  no public transport parameter.
* The implementation has exactly one patchable private standard-library HTTP
  seam and no public transport abstraction.
* Only canonical `github.com/<owner>/<repository>` input is accepted, without
  reproducing submitted-URL parsing.
* Only the public GitHub repository metadata endpoint is called.
* Only `EvidenceKind.REPOSITORY_ARCHIVED` is collected.
* A successful payload requires exact valid forms of `id`, `full_name`, and
  `archived` under the locked rules.
* Owner and repository response casing is compared ASCII case-insensitively;
  requested identity casing and response snapshot casing are preserved.
* Unrelated valid GitHub fields are accepted and preserved in the exact raw
  snapshot.
* Available results preserve the exact successful text and a matching SHA256
  digest.
* 404, rate limits, other 4xx responses, 5xx responses, timeout, connectivity,
  invalid payload, and unexpected status behavior match the table exactly.
* Structured errors contain only locked safe messages and selected sanitized
  retry guidance; no response body, authorization data, credential, or raw
  transport exception is exposed.
* Unavailable and failed outcomes contain no partial source identifier,
  archived value, raw snapshot, digest, or ETag.
* Direct result construction cannot violate available, unavailable, or failed
  invariants.
* Repeated normalization is deterministic for equal inputs and mocked source
  outcomes.
* No collector result is described or used as a persisted authoritative
  `EvidenceRecord`.
* Exactly thirteen focused tests pass, all 88 repository tests pass,
  compilation succeeds, and `git diff --check` reports no issue.
* No existing Day 3, Day 4, or Day 5 behavior changes.

## Risks

### Permissive payload typing

Python treats `bool` as an `int`, and truthiness could silently accept strings,
numbers, or null. Mitigation: use exact type checks for all required fields,
including `type(id_value) is int`, `id_value > 0`,
`type(full_name_value) is str`, and `type(archived_value) is bool`.

### Rejection of legitimate unrelated fields

GitHub responses contain many fields and evolve over time. Requiring an exact
key set or rebuilding a reduced JSON object would reject compatible responses
or lose evidence. Mitigation: validate only the three locked fields, accept all
other valid JSON fields, and preserve the exact successful response text.

### Ambiguous repository casing

Day 5 preserves owner and repository casing, while GitHub may return different
casing for the same repository. Exact string equality would reject a valid
response; unrestricted normalization could bind another resource. Mitigation:
require the locked ASCII `owner/repository` shape and compare only with
`casefold()`, while retaining requested and response representations in their
separate locations.

### Error or secret leakage

`HTTPError`, `URLError`, socket exceptions, reason phrases, headers, and bodies
may contain source-controlled or sensitive content. Mitigation: never use raw
exception strings or error bodies, whitelist only needed safe headers, use
module-owned messages, and test hostile body and exception content.

### Partial successful results

Constructing repository ID or archived status before every payload rule passes
could return misleading evidence. Mitigation: validate and normalize into
local variables first, construct the available result once only after all
checks pass, and enforce atomic shapes in result `__post_init__`.

### Duplicated Day 5 validation

Reparsing the original submitted locator would create divergent URL rules.
Mitigation: accept only the canonical post-Day-5 identity, use an anchored
identity-shape check, and never import or copy `urlsplit` submission logic.

### Premature persistence or workflow semantics

Calling the transient capture an `EvidenceRecord`, automatically retrying it,
or advancing an assessment would violate the collection/persistence boundary.
Mitigation: use collection-specific names, omit evidence IDs and durability
claims, perform one attempt, and explicitly prohibit evaluator integration.

### Unnecessary transport abstraction

A public client or protocol would expand API surface before a second collector
needs it. Mitigation: keep one private tuple-returning standard-library seam
that tests patch and expose no transport object.

### Exact snapshot size

Preserving a complete repository response is bounded for this endpoint but
still source-controlled. Day 6 has no configured response-size limit.
Mitigation: keep the scope to one metadata endpoint and record response-size
limits as an operational value for later collector hardening; do not add
streaming, blob storage, or truncation that would violate exact preservation in
this task.

### GitHub behavior changes

HTTP or response semantics may evolve. Mitigation: version the collector,
require only stable locked fields, classify incompatible responses explicitly,
and avoid claiming a final provider abstraction.

## Rollback Plan

Before persistence or workflow integration exists, rollback is limited to
removing:

* `src/engineering_due_diligence/github.py`; and
* `tests/test_github_repository_metadata_collection.py`.

No schema, stored record, external state, package export, migration, workflow
state, audit history, or compatibility shim requires reversal. The existing
Day 3 through Day 5 behavior remains unchanged.

If one failure classification is incorrect but the boundary remains sound,
correct the locked mapping and its focused regression test before any later
component depends on it. Do not weaken atomic result invariants to preserve an
incorrect shape.

## Explicit Exclusions

Day 6 does not implement:

* `EvidenceRecord` construction, evidence identifiers, or authoritative
  evidence durability;
* database schemas, migrations, repositories, transactions, filesystem
  storage, object storage, or persistence receipts;
* metric calculation, policy evaluation, Day 4 result assembly, or any call to
  `evaluate_assessment`;
* workflow state, transitions, automatic retry, retry budgets, backoff,
  scheduling, resumability, interruption handling, or idempotent delivery;
* audit events, audit persistence, telemetry, tracing, logging configuration,
  dashboards, or alerts;
* request submission, Day 5 locator normalization changes, repository-identity
  recanonicalization, or source-driven mutation of assessment context;
* authenticated GitHub access, private repositories, GitHub Apps, OAuth,
  tokens, credentials, authorization logic, or enterprise GitHub;
* GitLab, additional providers, provider interfaces, generic collector
  frameworks, plugins, agents, or distributed services;
* license, latest-commit, security-policy, release, contributor, issue,
  vulnerability, dependency, or community-profile evidence;
* redirects as evidence, rename history, repository transfer handling,
  alternate API versions, GraphQL, pagination, caching, conditional requests,
  ETag reuse, freshness calculation, or recollection;
* public HTTP clients, transport protocols, service objects, exception
  hierarchies, dependency injection, or test-only production APIs;
* FastAPI, Pydantic, CLI commands, serialization frameworks, new dependencies,
  Docker, deployment, or infrastructure; or
* live GitHub integration tests, contract tests against the internet, or
  credentials in tests.

## Plan Review

Review of this plan confirms:

1. **Payload typing is strict.** Positive IDs use exact nonboolean integer
   checks, `full_name` is an exact validated string, and `archived` is an exact
   Boolean. No coercion or truthiness is permitted.
2. **Unrelated fields remain compatible.** Only three fields are required;
   extra valid JSON fields are accepted and remain in the exact raw snapshot.
3. **Casing behavior is explicit.** Requested and returned names must have the
   locked ASCII shape and compare with `casefold()`; neither representation is
   silently rewritten.
4. **External details do not leak.** Error bodies are never read into results,
   recognized exception types map to constant messages, and only selected safe
   headers may survive.
5. **Results are atomic.** Available requires every evidence field and a
   matching digest; unavailable and failed results prohibit every partial
   evidence field.
6. **Day 5 URL parsing is not duplicated.** The collector checks only canonical
   identity syntax and never accepts or parses a submitted locator.
7. **No durability or workflow is claimed.** The result is explicitly
   transient, performs one attempt, and is prohibited from evaluation until a
   later persistence boundary exists.
8. **Transport remains private.** Tests patch one private standard-library seam
   and no public transport API, protocol, client, or callable parameter is
   added.

No material ambiguity, unnecessary abstraction, or scope expansion remains in
the planned boundary.

## Implementation Checklist

* Confirm the repository remains at the approved Day 5 commit before coding.
* Create only `src/engineering_due_diligence/github.py` and
  `tests/test_github_repository_metadata_collection.py` during implementation.
* Implement exactly four immutable public value contracts and one public
  collector function.
* Implement one private standard-library HTTP seam with no authorization.
* Enforce canonical identity and explicit response casing rules.
* Validate exact required payload types while accepting unrelated fields.
* Preserve exact successful response text, digest, source identity, version,
  and safe ETag.
* Implement the locked failure-classification table with sanitized errors and
  no partial evidence.
* Add exactly the thirteen focused test methods.
* Run the focused 13-test command.
* Run the complete expected 88-test suite.
* Run bytecode compilation and `git diff --check`.
* Review correctness, security, compatibility, maintainability, and scope.
* Confirm existing Day 3 through Day 5 source and tests are unchanged.
* Do not update README, journal, memory, or any other file until a later
  finalization task explicitly requests it.
