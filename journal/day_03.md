# Day 3 Journal

## Work Completed

Implemented the first local deterministic vertical slice from assessment
context through `EvidenceRecord`, `MetricResult`, and `PolicyFinding`.

The slice now:

* accepts immutable context for a short-lived internal prototype or a
  critical long-lived production dependency;
* consumes complete local evidence records for repository archived status,
  license status, latest commit timestamp, and security policy presence;
* calculates four versioned deterministic metrics;
* evaluates four versioned, context-specific policy requirements;
* preserves exact evidence and metric identifiers on every finding;
* rejects an incomplete required evidence set before returning results; and
* converts a complete unavailable evidence record into an unavailable metric
  and a non-passing `not_evaluable` finding.

No GitHub calls, AI behavior, persistence, APIs, infrastructure, or universal
repository score were added.

## Initial Tests and Verification

The initial implementation added eight focused standard-library tests covering
deterministic metric values, absent and unavailable evidence, archived
repositories, context-sensitive security policy, differing prototype and
production findings, traceability, version identifiers, and identical repeated
evaluation.

At that point, `PYTHONPATH=src python3 -m unittest discover -s tests -v` passed
all eight tests. Python bytecode compilation and `git diff --check` also
passed.

## Assumptions

* Local fixture records stand in for already collected and stored evidence;
  neither collection nor durable persistence is implemented.
* A known absent license is an available factual value, while inability to
  establish license status is an unavailable evidence outcome.
* The demonstration policy applies strict controls when the context is
  production, critical, longer than 180 days, or low risk tolerance.
* Demonstration commit-recency thresholds are 180 days for strict contexts and
  730 days otherwise.
* Callers supply a timezone-aware evaluation timestamp so repeated logical
  evaluation can produce identical content and identifiers.

These policy thresholds and conditions have not been validated with the
simulated customer and are not claims of measured effectiveness.

## Unresolved Questions

Policy owners still need to validate the demonstration thresholds and
conditions. Evidence freshness rules, persistent identifier allocation,
durable idempotency, and workflow audit recording remain deferred to their
planned tasks.

## Work Not Implemented

No request workflow, persistence layer, audit event recording, external
collector, report generation, human decision path, API, database, AI
integration, Docker, CI, user interface, or infrastructure was implemented.

## Review and Correction Continuation

Later read-only reviews and focused corrections strengthened the initial slice
without expanding its architectural scope.

The correction sequence:

1. added canonical fixture parsing and required normalized-value agreement for
   archived status, license status, latest commit timestamp, and security policy
   presence while preserving raw snapshot digest validation;
2. required policy evaluation to recalculate and compare every supplied metric
   against its exact evidence, calculation version, and calculation timestamp;
3. enforced temporal ordering so evidence attempts cannot follow metric
   calculation and metric calculation cannot follow policy evaluation;
4. normalized aware timestamps to UTC while accepting equal instants and
   equivalent timezone offsets;
5. changed maintenance decisions to use exact elapsed duration from the source
   commit timestamp rather than the floored `days_since_latest_commit` display
   value;
6. made the 180-day and 730-day boundaries inclusive and made one second beyond
   either boundary fail the corresponding requirement;
7. ensured future commit evidence fails closed for current, stale, and unknown
   freshness instead of allowing freshness to conceal an invalid timestamp;
8. added direct rejection tests for duplicate evidence identifiers, duplicate
   canonical evidence kinds, and naive evidence, metric, and policy timestamps;
9. revalidated raw snapshot integrity during calculation so corruption of an
   already constructed evidence record is rejected before metrics are returned;
   and
10. verified that an absent license produces `condition_required` for the
    prototype context and `fail` for the strict production context while
    retaining exact evidence and metric references.

The final behavior keeps two distinctions explicit:

* intrinsically invalid evidence fails closed, while temporally valid stale or
  unknown evidence produces an unavailable metric and `not_evaluable` finding;
  and
* `days_since_latest_commit` is a floored display metric, while exact
  UTC-normalized source and evaluation timestamps control maintenance policy.

Final verification completed with:

```text
Ran 52 tests in 0.021s
OK
```

Compilation, tracked and untracked whitespace checks, complete diff review, and
working-tree review passed. Nothing was staged, committed, or pushed during
implementation or verification.

## Exact Next Task

Perform the final Day 3 commit readiness review, then create one intentional
commit containing the complete deterministic vertical slice and its
documentation.
