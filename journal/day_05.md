# Day 5 Journal

## Work Completed

Implemented and reviewed the pure transient assessment-request validation
boundary that precedes evidence collection and the existing deterministic
assessment slice.

The new public contracts in `engineering_due_diligence.request` are:

* frozen `AssessmentRequestInput` with the eleven planned submitted fields;
* frozen `AssessmentRequestValidationError` with stable field, code, and
  message values;
* frozen `AssessmentRequestValidationResult` with the exact input request,
  validation status, optional canonical repository identity, optional existing
  `AssessmentContext`, and an immutable error tuple;
* `REQUEST_DEFINITION_VERSION = "assessment-request.v1"`; and
* `validate_assessment_request(request)`, which returns a complete valid or
  invalid transient result.

`AssessmentRequestInput` intentionally performs no constructor validation.
Ordinary invalid submitted values can therefore reach the validator and become
structured validation data rather than constructor exceptions.

## Locator Rules

The validator accepts only HTTPS GitHub web locators with:

* authority exactly `github.com`, compared case-insensitively;
* exactly one owner segment and one repository segment matching the locked
  ASCII character grammar;
* at most one optional trailing slash; and
* no credentials, port, query, fragment, percent encoding, Unicode, whitespace,
  control characters, dot segments, extra path components, or `.git` suffix.

A supported locator becomes:

```text
github.com/<owner>/<repository>
```

GitHub host casing is canonicalized while owner and repository casing is
preserved exactly. Validation performs no network lookup and does not claim
that the repository exists, is public, or resolves to an authoritative GitHub
source identifier.

## Verified Validation Behavior

Validation processes fields only in this locked order:

1. `assessment_id`;
2. `submitted_repository_locator`;
3. `intended_use`;
4. `environment`;
5. `criticality`;
6. `expected_lifetime_days`;
7. `risk_tolerance`;
8. `submitted_by_actor_id`;
9. `responsible_reviewer_actor_id`;
10. `submitted_at`; and
11. `request_definition_version`.

Each field emits at most one first-precedence error. Every applicable field
error is returned in the locked order without sorting an unordered collection.
Repeated validation of equal input returns equal results.

A valid result contains the exact original request object, one canonical
repository identity, one existing `AssessmentContext`, and no errors. The aware
`submitted_at` object, timezone, and offset representation remain unchanged.

An invalid result contains the exact original request, at least one structured
error, no normalized identity, and no context. Missing or malformed text,
unsupported locators or versions, invalid enum values, invalid lifetime, naive
timestamps, and timezone objects that cannot provide an offset return invalid
data rather than escaping as ordinary validation exceptions.

`AssessmentContext` is constructed exactly once and only after every submission
field passes. Its existing internal invariant remains unchanged, and the
request validator does not parse, catch, or translate its exception messages.
`AssessmentRequestValidationResult.__post_init__` rejects contradictory direct
valid or invalid result construction.

## Focused Tests

Fourteen focused Day 5 tests cover:

1. immutability of all three request-validation values and permissive input
   construction;
2. complete valid result construction and exact context mapping;
3. exact preservation of a non-UTC aware submission timestamp;
4. supported locator variants and casing behavior;
5. every locked unsupported locator shape;
6. required-text error ordering;
7. invalid context types and lifetime values;
8. non-datetime, naive, missing-offset, and raising-offset submission times;
9. unsupported request-definition versions;
10. one first-precedence error per field;
11. the exact complete eleven-field error order;
12. atomic invalid results for representative F01-style and F02-style input;
13. deterministic repeated validation; and
14. rejection of contradictory direct result construction.

The complete repository suite passes 75 tests: 14 focused Day 5 tests and the
61 existing Day 3 and Day 4 tests.

## Review Findings and Corrections

Review confirmed stable explicit validation order, one first-precedence error
per field, atomic invalid results, exact request and timestamp preservation,
canonical identity construction, delayed `AssessmentContext` construction,
deterministic repeated validation, and unchanged Day 3 and Day 4 behavior.

Two material strict-locator issues were found and corrected during Day 5:

1. `urllib.parse.urlsplit` can discard embedded control whitespace before
   parsing. The validator now rejects non-ASCII, non-printable, and whitespace
   characters from the raw locator before parsing.
2. A locator ending in a bare `?` or `#` parses with an empty query or fragment.
   The validator now rejects those raw delimiters so only the exact locked URL
   shapes are accepted.

The existing unsupported-locator test covers both corrections. Final review
found no remaining material correctness, security, compatibility, or scope
issue. No unnecessary public export, status enum, exception hierarchy,
validation framework, service object, persistence port, workflow behavior, or
network behavior was introduced.

## Verification

Final verification completed with:

```text
Ran 75 tests
OK
```

Python bytecode compilation and `git diff --check` passed. The reviewed change
contains only the Day 5 plan, request-validation module, focused tests, README
status update, and this journal entry.

## Explicit Exclusions

Day 5 did not implement:

* authoritative or persisted `AssessmentRequest` lifecycle state;
* schemas, migrations, repositories, transactions, or other persistence;
* workflow transitions, retries, resumability, or interruption handling;
* audit event creation, audit durability, or observability;
* GitHub API calls, repository existence or visibility checks, authentication,
  authorization, source-ID resolution, or evidence collectors;
* evidence, metric, policy, or Day 4 result changes;
* report generation, AI/model integration, prompt contracts, or grounding;
* APIs, FastAPI, Pydantic, CLI commands, serialization contracts, or user
  interfaces;
* human review, decisions, or authorization rules;
* package-root exports, dependencies, infrastructure, or ADR changes; or
* private repositories, GitLab, enterprise GitHub, SSH locators, clone URLs, or
  arbitrary browser URLs.

## Exact Next Task

Perform a read-only Day 6 direction review. Do not begin Day 6 implementation
as part of Day 5 finalization.
