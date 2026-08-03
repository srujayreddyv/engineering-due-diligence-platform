# Day 5 Assessment Request Validation Plan

## Task

Implement the smallest pure, transient boundary that validates one immutable
assessment-request submission and either produces the existing validated
`AssessmentContext` or returns explicit ordered validation errors.

The public entry point will be:

```python
def validate_assessment_request(
    request: AssessmentRequestInput,
) -> AssessmentRequestValidationResult:
```

## Objective

Establish the missing request-validation boundary before evidence collection,
persistence, or workflow orchestration. Success means that a supported complete
HTTPS GitHub submission produces exactly one context compatible with the Day 3
and Day 4 deterministic boundaries, while expected invalid input produces
deterministic validation data and never a partial context.

This boundary is a transient in-process contract. It does not create or persist
the authoritative `AssessmentRequest` aggregate described by the domain model,
change workflow state, or record audit activity.

## Current State

`models.py` defines a frozen `AssessmentContext` containing:

* `assessment_id`;
* normalized `repository_identity`;
* `intended_use`;
* `environment`;
* `criticality`;
* `expected_lifetime_days`; and
* `risk_tolerance`.

Its `__post_init__` protects the internal invariant that text is nonempty,
categorical fields are the existing enum types, and lifetime is a positive
non-boolean integer. It assumes the repository identity has already been
normalized and raises `ValueError` for programmer-supplied invalid internal
values. It does not accept a submitted locator, preserve submission metadata,
or return field-level validation data.

`assessment.py` defines the Day 4 transient deterministic result and
`evaluate_assessment(context, evidence_records, evaluated_at)`. That boundary
requires an already-valid `AssessmentContext` and already-created evidence. It
does not own request validation.

The domain model requires deterministic request validation before collection,
an exact submitted locator, a normalized repository identity on success,
explicit errors on failure, immutable submitted context, actor identities, an
aware submission time, and a request-definition version. The failure model
classifies invalid or unsupported targets as F01 and missing or invalid required
context as F02. This task returns the facts needed for that later workflow
classification but does not implement workflow state, failure records,
persistence, or audit events.

The current suite contains 61 tests for evidence, deterministic metrics,
policy, and the Day 4 result. No request-validation module or tests exist.

## Locked Assumptions

* The caller creates `assessment_id`; validation does not generate or replace
  it.
* The exact supported request-definition version is
  `assessment-request.v1`, exposed as `REQUEST_DEFINITION_VERSION` from the
  defining module.
* Only an HTTPS `github.com` web locator is supported. Validation proves the
  local locator contract only; it does not prove that the repository exists,
  is public, or resolves to a GitHub source identifier.
* `Environment`, `Criticality`, and `RiskTolerance` remain the existing enum
  contracts. The validator does not parse free-form strings into enums.
* `expected_lifetime_days` remains the existing positive-integer representation
  of expected lifetime.
* The exact input object is retained by the result. This preserves every
  submitted field, including the exact `submitted_at` object and its UTC offset,
  without normalization or copying.
* Expected invalid values may be present at runtime even though fields have
  their expected Python type annotations. `AssessmentRequestInput` therefore
  has no `__post_init__` validation; the public validation function owns all
  expected-input diagnostics.
* A corrected invalid submission is a future new request operation. This
  transient task does not mutate the submitted input or define reassessment
  links.

## Proposed Solution

### Public contracts

Add the following frozen standard-library dataclasses to
`engineering_due_diligence.request`.

```python
@dataclass(frozen=True)
class AssessmentRequestInput:
    assessment_id: str
    submitted_repository_locator: str
    intended_use: str
    environment: Environment
    criticality: Criticality
    expected_lifetime_days: int
    risk_tolerance: RiskTolerance
    submitted_by_actor_id: str
    responsible_reviewer_actor_id: str
    submitted_at: datetime
    request_definition_version: str
```

These are the only input fields. Do not add validation status, workflow state,
normalized identity, repository source ID, notes, organizational references,
related assessments, or persistence metadata to the submitted input.

```python
@dataclass(frozen=True)
class AssessmentRequestValidationError:
    field: str
    code: str
    message: str
```

An error is transient validation data, not a new domain entity, exception type,
or audit record. The implementation creates errors only from locked constants;
it does not echo the submitted value into `message`.

```python
@dataclass(frozen=True)
class AssessmentRequestValidationResult:
    request: AssessmentRequestInput
    validation_status: str
    normalized_repository_identity: Optional[str]
    context: Optional[AssessmentContext]
    validation_errors: Tuple[AssessmentRequestValidationError, ...]
```

`validation_status` has exactly two allowed values: `"valid"` and `"invalid"`.
Do not add a status enum, result identifier, validation timestamp, schema
version, workflow state, convenience alias, mutable collection, or package-root
export.

`AssessmentRequestValidationResult.__post_init__` enforces only its result-shape
contract:

* `valid` requires a nonempty canonical identity, exactly one
  `AssessmentContext`, and an empty error tuple;
* `invalid` requires `normalized_repository_identity is None`, `context is
  None`, and at least one error; and
* any other status or contradictory field combination is an internal
  construction error.

The validator places the exact caller-supplied `request` object in either
result. It does not rebuild the input or normalize `submitted_at`.

### Required string rules

The following submitted fields must have `type(value) is str`, must contain at
least one non-whitespace character, and must equal `value.strip()`:

1. `assessment_id`;
2. `submitted_repository_locator`;
3. `intended_use`;
4. `submitted_by_actor_id`;
5. `responsible_reviewer_actor_id`; and
6. `request_definition_version`.

Leading or trailing whitespace is rejected instead of silently removed. The
exact accepted value is preserved. Internal whitespace in `intended_use` is
allowed. Identifiers and versions receive no other character or length rule in
this task.

### Locator normalization rules

Use `urllib.parse.urlsplit` from the standard library. Catch parser
`ValueError` for submitted locator data and return the locator validation error;
do not let an expected malformed locator escape as an exception.

A locator is supported only when all of these rules hold:

1. The parsed scheme compares case-insensitively equal to `https`.
2. The complete authority compares case-insensitively equal to `github.com`.
   This rejects credentials, user information, ports, subdomains, and alternate
   GitHub hostnames. Host casing is not retained in the canonical identity.
3. Query and fragment are both empty.
4. The path matches exactly
   `/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+` with at most one optional trailing slash.
5. The owner and repository segments are neither `.` nor `..`.
6. Percent-encoded segments, Unicode characters, whitespace, empty segments,
   additional path segments, and a repository segment ending in `.git` are
   rejected. Clone URLs are not part of this web-locator contract.

The owner and repository segment casing is preserved exactly as submitted. A
supported locator produces:

```text
github.com/<owner>/<repository>
```

The canonical identity removes only the scheme, authority casing, and optional
single trailing slash. It performs no network lookup, case folding of owner or
repository, URL decoding, `.git` stripping, rename resolution, or source-ID
resolution.

Examples:

| Submitted locator | Outcome |
| --- | --- |
| `https://github.com/example/reliable-library` | `github.com/example/reliable-library` |
| `HTTPS://GITHUB.COM/Example/Reliable-Library/` | `github.com/Example/Reliable-Library` |
| `http://github.com/example/reliable-library` | invalid |
| `https://www.github.com/example/reliable-library` | invalid |
| `https://github.com/example/reliable-library.git` | invalid |
| `https://github.com/example/reliable-library/issues` | invalid |
| `https://github.com/example/reliable-library?tab=readme` | invalid |

### Non-locator validation rules

After the required-string checks:

* `environment` must be an `Environment` instance;
* `criticality` must be a `Criticality` instance;
* `expected_lifetime_days` must have `type(value) is int` and be greater than
  zero, so booleans are rejected;
* `risk_tolerance` must be a `RiskTolerance` instance;
* `submitted_at` must be a `datetime` instance with non-`None` `tzinfo` and a
  non-`None` `utcoffset()`; an exception raised while asking a supplied timezone
  for its offset is treated as an invalid submitted time; and
* `request_definition_version` must equal `REQUEST_DEFINITION_VERSION` after it
  passes type, nonempty, and surrounding-whitespace checks.

Validation never reads the current clock, generates an identifier, accesses the
network, mutates the input, or coerces values into expected types.

### Validation errors and stable ordering

Every field contributes at most one error. Checks use the precedence shown
below and stop checking that field after its first failure.

| Field | Error precedence |
| --- | --- |
| `assessment_id` | `invalid_type`, `required`, `surrounding_whitespace` |
| `submitted_repository_locator` | `invalid_type`, `required`, `surrounding_whitespace`, `unsupported_https_github_locator` |
| `intended_use` | `invalid_type`, `required`, `surrounding_whitespace` |
| `environment` | `invalid_environment` |
| `criticality` | `invalid_criticality` |
| `expected_lifetime_days` | `invalid_type`, `must_be_positive` |
| `risk_tolerance` | `invalid_risk_tolerance` |
| `submitted_by_actor_id` | `invalid_type`, `required`, `surrounding_whitespace` |
| `responsible_reviewer_actor_id` | `invalid_type`, `required`, `surrounding_whitespace` |
| `submitted_at` | `invalid_type`, `timezone_aware_required` |
| `request_definition_version` | `invalid_type`, `required`, `surrounding_whitespace`, `unsupported_version` |

Errors are appended only in this immutable field order, regardless of helper
implementation, mapping order, or the submitted values:

```text
assessment_id
submitted_repository_locator
intended_use
environment
criticality
expected_lifetime_days
risk_tolerance
submitted_by_actor_id
responsible_reviewer_actor_id
submitted_at
request_definition_version
```

Messages are deterministic constant templates:

* `invalid_type`: `<field> has an invalid type.`
* `required`: `<field> must not be empty.`
* `surrounding_whitespace`: `<field> must not have leading or trailing whitespace.`
* `unsupported_https_github_locator`: `submitted_repository_locator must be an HTTPS github.com owner/repository URL.`
* `invalid_environment`: `environment must be an Environment.`
* `invalid_criticality`: `criticality must be a Criticality.`
* `must_be_positive`: `expected_lifetime_days must be a positive integer.`
* `invalid_risk_tolerance`: `risk_tolerance must be a RiskTolerance.`
* `timezone_aware_required`: `submitted_at must be timezone-aware.`
* `unsupported_version`: `request_definition_version is not supported.`

The public contract does not depend on dictionary or set iteration. Tests assert
the ordered `(field, code)` tuples rather than sorting returned errors.

### Context construction and exception behavior

Run every request-input check and collect the complete ordered error tuple
before constructing an `AssessmentContext`.

If any error exists, return one `invalid` result with the exact input object,
`None` identity, `None` context, and the complete error tuple. Missing context,
unsupported locator, unsupported version, invalid enum values, invalid lifetime,
and invalid submission time are expected input outcomes and do not raise.

If no error exists, construct exactly one `AssessmentContext` using:

```text
assessment_id                 <- request.assessment_id
repository_identity           <- canonical locator identity
intended_use                  <- request.intended_use
environment                   <- request.environment
criticality                   <- request.criticality
expected_lifetime_days        <- request.expected_lifetime_days
risk_tolerance                <- request.risk_tolerance
```

Return one `valid` result containing the exact input object, canonical identity,
that context, and `validation_errors=()`.

Do not catch `AssessmentContext` construction failures after prevalidation.
Such a failure means the Day 5 preconditions have drifted from the existing
internal invariant and is an internal programming error, not expected invalid
input. Do not parse exception messages or convert constructor exceptions into
field errors.

This separation is intentional: Day 5 owns external submission diagnostics;
`AssessmentContext` remains the defensive internal invariant. Do not change
`models.py`, move its checks, or add a second general validation framework.

### Determinism

Equal frozen inputs produce equal results, including identical ordered error
tuples, canonical identities, and contexts. The implementation uses no current
time, randomness, generated identifiers, external state, locale-dependent
comparison, network request, or unordered output construction.

## Files Affected

This planning task changes only:

* `plans/day_05_assessment_request_validation.md` — this reviewed plan.

The later implementation task is limited to:

* `src/engineering_due_diligence/request.py` — add the three frozen public
  values, locked request-definition version, pure locator normalization, and
  validation function; and
* `tests/test_assessment_request_validation.py` — add exactly the focused tests
  below.

Do not modify `models.py`, `assessment.py`, existing tests, `__init__.py`,
README, journal, memory, documentation, templates, or any other file in this
planning task.

## Database Impact

None. There is no schema, migration, repository, durable request, stored
validation result, state transition, transaction, seed data, or persistence
fixture. The input and result are explicitly transient in-process values.

## Testing Strategy

Add exactly these focused tests to
`tests/test_assessment_request_validation.py`:

1. `test_request_validation_contracts_are_frozen` — construct all three public
   dataclasses, assert field reassignment raises `FrozenInstanceError`, assert
   result errors are a tuple, and confirm the input has no constructor-time
   validation that prevents expected invalid values from reaching the validator.
2. `test_valid_request_returns_preserved_input_context_and_canonical_identity`
   — validate one complete request; assert status `valid`, the result retains
   the exact input object, identity is
   `github.com/example/reliable-library`, context equals an independently
   constructed `AssessmentContext` with the exact seven mapped fields, and
   errors are empty.
3. `test_aware_offset_submitted_at_is_preserved_exactly` — supply a non-UTC
   aware datetime; assert the result retains the exact request and the request
   retains the same timestamp object, timezone object, and ISO representation.
4. `test_supported_locator_variants_follow_the_locked_normalization_rules` —
   use subtests for the basic locator, case-insensitive scheme and authority,
   and one optional trailing slash; assert host canonicalization, owner and
   repository case preservation, and exact canonical identities.
5. `test_unsupported_locator_shapes_return_one_locator_error` — use subtests for
   HTTP, another host, `www.github.com`, credentials, port, query, fragment,
   empty owner, empty repository, extra path component, double trailing slash,
   percent encoding, Unicode, whitespace, dot segments, invalid segment
   characters, and `.git`; assert no exception, one locator error with the
   locked field/code, no identity, and no context.
6. `test_required_text_errors_follow_locked_field_order` — submit invalid text
   values across assessment ID, locator, intended use, both actor IDs, and
   request version; assert the exact returned `(field, code)` sequence follows
   the global field order rather than setup or mapping order.
7. `test_invalid_context_values_return_ordered_validation_data` — supply a
   non-enum environment, non-enum criticality, boolean and nonpositive lifetime
   variants, and non-enum risk tolerance; assert expected codes, locked order,
   no exception, no identity, and no context.
8. `test_invalid_submitted_at_returns_validation_data` — use subtests for a
   non-datetime, a naive datetime, and a datetime whose timezone cannot provide
   an offset; assert `invalid_type` or `timezone_aware_required` as applicable
   and no escaped exception.
9. `test_unsupported_request_definition_version_is_invalid` — provide a
   well-formed noncurrent version; assert the exact field/code/message and
   invalid result shape.
10. `test_each_field_emits_only_its_first_precedence_error` — use values that
    could otherwise trigger later checks, such as an empty locator and empty
    version; assert at most one error per field and the first locked code.
11. `test_mixed_invalid_request_returns_complete_stably_ordered_errors` — make
    all eleven fields invalid at once; assert the exact eleven-field order,
    exact ordered codes, invalid result invariants, and the exact input object.
12. `test_expected_invalid_input_never_returns_a_partial_context` — exercise
    representative F01-style locator/version errors and F02-style context
    errors; assert every returned result is `invalid`, has at least one error,
    and has neither canonical identity nor context.
13. `test_repeated_validation_is_deterministic` — validate the same valid input
    twice and the same multi-error invalid input twice; assert pairwise result
    equality, identical ordered errors, and unchanged caller input.
14. `test_validation_result_rejects_contradictory_direct_construction` — use
    subtests for an unknown status, a `valid` result missing its identity or
    context, a `valid` result containing errors, and an `invalid` result with an
    identity, context, or empty error tuple; assert the result's internal shape
    guard rejects each contradictory programmer construction.

Run focused and broad verification without creating bytecode:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_assessment_request_validation -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

No test calls GitHub, patches a clock, depends on current time, adds persistence,
or duplicates Day 3 evidence fixtures. Context compatibility is proven by exact
equality with the existing `AssessmentContext` contract, not by rerunning the
evidence-to-policy slice.

## Acceptance Criteria

* The implementation adds only the three frozen public values, the locked
  request-definition version, and `validate_assessment_request` in
  `request.py`.
* `AssessmentRequestInput` contains exactly the eleven locked fields and
  accepts expected invalid runtime data for public validation.
* The exact input object and its aware `submitted_at` representation are
  preserved in every result.
* Only the locked HTTPS GitHub web-locator shapes are accepted, and each
  accepted shape yields the exact canonical identity format.
* Unsupported or malformed locator data returns the locked validation error and
  does not raise a parser exception.
* Error fields, codes, messages, one-error-per-field behavior, precedence, and
  global ordering match this plan exactly.
* Every expected invalid request returns a complete `invalid` result with no
  context or canonical identity and at least one error.
* Every valid request returns a complete `valid` result with exactly one
  `AssessmentContext`, one canonical identity, and no errors.
* Context fields are copied without transformation from the validated input,
  except that `repository_identity` receives the canonical locator identity.
* Repeated validation of equal input is deterministic.
* Existing `AssessmentContext`, evaluation, Day 4 result behavior, exceptions,
  tests, and module exports remain unchanged.
* All 14 focused tests and the complete existing suite pass.
* No source, test, or repository file other than the two expected implementation
  files is changed during the later implementation task unless separately
  approved.

## Risks

* **Boundary duplication:** The submission validator must preflight the seven
  values later passed to `AssessmentContext` so expected bad input becomes
  validation data. This is boundary-specific diagnostic validation, while the
  existing constructor remains the internal invariant. Changing or catching
  the constructor would create a less stable duplicated authority.
* **Locator overclaiming:** Structural URL acceptance could be mistaken for
  proof that a repository exists or is public. Names, documentation, and tests
  must call this canonical locator validation only; authoritative resolution is
  deferred to collection.
* **Canonical identity aliases:** Preserving owner/repository case means
  differently cased submissions may produce different local identities even if
  GitHub later resolves them to one source. Case folding without authoritative
  resolution would make a stronger unsupported claim, so source-ID alias
  reconciliation remains deferred.
* **Restricted locator surface:** Rejecting clone URLs, `.git`, percent encoding,
  Unicode, subdomains, and query-bearing browser URLs may reject usable GitHub
  links. The restriction is intentional for a one-day deterministic boundary
  and can be broadened only through an explicit later contract change and tests.
* **Direct result construction:** Callers can instantiate public dataclasses.
  Result `__post_init__` protects the valid/invalid shape, while
  `validate_assessment_request` remains the trustworthy semantic construction
  path.
* **Error-contract compatibility:** Field names, codes, messages, precedence,
  and ordering become observable behavior. Later changes require deliberate
  compatibility review rather than relying on incidental helper or dictionary
  order.
* **Malicious parser inputs:** URL parsing can raise for malformed authorities
  or unusual timezone objects can raise during offset evaluation. The validator
  must guard only these expected-input operations and return sanitized constant
  messages without echoing submitted data.

## Rollback Plan

Revert `src/engineering_due_diligence/request.py` and
`tests/test_assessment_request_validation.py`. No existing module imports the
new boundary, and there is no database, migration, stored record, API, workflow
state, package-root export, or external side effect to reverse.

This planning change can be rolled back by removing only
`plans/day_05_assessment_request_validation.md`.

## Explicit Exclusions

* Persistence, schemas, migrations, repositories, durable request identity,
  transactions, or idempotent submission storage.
* Full authoritative `AssessmentRequest` lifecycle, validation-status
  persistence, workflow transitions, retries, interruption, or resumption.
* `AuditEvent` creation or failure-category persistence.
* Network access, GitHub API calls, repository existence or visibility checks,
  source-ID resolution, authentication, authorization, rate limiting, or
  collection.
* Private repositories, GitLab, alternate GitHub hosts, enterprise GitHub,
  clone locators, SSH locators, or arbitrary browser URLs.
* Evidence records, new evidence kinds, source normalization, metrics, policy,
  report generation, model integration, or human decisions.
* FastAPI, Pydantic, CLI commands, serialization schemas, UI behavior, or
  package-root exports.
* Free-form enum parsing, silent trimming, default values, inferred context,
  automatic identifier creation, or current-clock reads.
* Changes to `models.py`, `assessment.py`, existing tests, README, journal,
  memory, docs, templates, dependencies, infrastructure, or ADRs.
* General URL-validation frameworks, validation registries, error hierarchies,
  status enums, builders, factories, service objects, or persistence ports.

## Plan Review

* **Ambiguous validation rules:** Resolved. Types, required strings, whitespace,
  version, timestamp awareness, URL parsing, accepted authority and path,
  canonical casing, optional slash, rejected components, error precedence, and
  result shapes are explicit.
* **Unnecessary abstractions:** None planned. The boundary has exactly the three
  requested frozen values, one function, one required version constant, and
  small private validation helpers. No framework, service class, status enum,
  exception hierarchy, general validator, repository, or port is introduced.
* **Duplicated `AssessmentContext` validation:** Controlled. Submission checks
  provide stable external error data before construction; the existing context
  constructor remains unchanged as the internal invariant. The validator maps
  one valid request to one context and neither catches nor parses constructor
  errors.
* **Unstable error ordering:** Resolved. Each field emits at most one first-
  precedence error, and fields are traversed in one locked sequence. Returned
  errors are never sorted from an unordered collection.
* **Scope expansion:** None planned. The task remains pure and transient and
  excludes workflow, persistence, audit, collectors, APIs, new domain entities,
  infrastructure, and changes outside the two implementation files.
* **Correctness:** Valid and invalid result invariants are mutually exclusive;
  context construction happens only after complete validation; malformed URL
  and timezone behavior is converted to expected validation data.
* **Security:** Credentials, user information, ports, query strings, fragments,
  and unexpected authorities are rejected, and error messages never echo input.
* **Performance:** Work is bounded local validation over eleven scalar fields
  and one URL; no meaningful performance risk exists.
* **Backward compatibility:** Existing modules and contracts are untouched. The
  new module is additive and has no package-root export.
* **Test coverage:** The 14 locked tests cover immutability, success, timestamp
  preservation, normalization, every locator rejection class, every field
  category, error precedence and ordering, invalid-result atomicity, and
  determinism.

## Implementation Checklist

* Confirm the eleven input fields and exact public result fields.
* Add the three frozen values and locked request-definition version in
  `request.py` without constructor-time input validation.
* Implement bounded HTTPS GitHub locator parsing and exact canonicalization.
* Implement one-error-per-field validation in the locked field and precedence
  order.
* Return complete invalid data before any `AssessmentContext` construction.
* Construct exactly one context for a completely valid request.
* Add exactly the 14 focused tests above.
* Run focused tests, full discovery, and `git diff --check` with bytecode writes
  disabled.
* Review correctness, security, determinism, error compatibility, context
  boundary separation, and scope.
* Do not modify or stage any file outside the approved implementation scope.
