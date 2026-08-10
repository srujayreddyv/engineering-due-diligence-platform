# Engineering Patterns

## General Change Pattern

Before a meaningful implementation task:

1. Read AGENTS.md and all memory files.
2. Inspect relevant source code and tests.
3. Create or update a task plan.
4. State assumptions and acceptance criteria.
5. Implement the smallest complete change.
6. Run focused tests.
7. Run the broader verification suite.
8. Review correctness, security, reliability, and scope.
9. Update durable memory only when lasting knowledge changed.

## Evidence Collection Pattern

Collectors return transient collection results. Persistence, not collection,
is the authority boundary that may reconstruct a normalized evidence record.

Collectors do not calculate adoption recommendations.

Exact HTTP 200 response bytes or relevant source snapshots are preserved before
derived calculations occur. A bounded multi-request collector preserves its
ordered source observations and every successful response; an incomplete
search must not produce a normalized Boolean fact.

For timestamp-bearing evidence, preserve the exact source timestamp text
separately from the normalized aware datetime representation. Different offset
representations are valid only when they denote the same UTC instant; exact
replay still treats changed source text as changed source content.

Every collection attempt records success, failure, timestamp, source, and
freshness information.

## SQLite Persistence Pattern

For the concrete prototype persistence boundary:

1. Accept only exact upstream contracts and re-run their existing invariants.
2. Persist a valid request before linked collection outcomes.
3. Use explicit SQLite transactions for every linked record set and roll back
   incomplete writes.
4. Keep complete source responses and ordered observations separate from
   compact normalized evidence.
5. Close and reopen the on-disk database before returning authoritative
   evidence.
6. Recompute digests from reopened bytes, revalidate source payload binding and
   normalized values, and reconstruct existing domain contracts.
7. Treat an exact replay as idempotent and any reused identity with different
   material content as a nonmutating conflict.
8. Expose only stable persistence categories and constant safe messages for
   expected storage failures; do not translate programmer errors into ordinary
   persistence outcomes.
9. Evolve the concrete schema only from an exact supported prior version, in
   one explicit transaction; copy and compare durable rows by primary key,
   verify normalized schema definitions and foreign keys before advancing
   `PRAGMA user_version`, and roll back the complete migration on failure.
10. Use explicit typed columns and constraints for each implemented evidence
    value rather than a generic unvalidated value store.
11. Open aggregate evaluation reads through a separate strict read-only path;
    never call schema creation or migration from a read boundary.
12. Read the request, evidence rows, attempts, source snapshots, observations,
    and integrity checks from one transaction snapshot, reconstruct every
    record from durable source material, and return nothing unless the complete
    canonical evidence set verifies.
13. Treat unavailable evidence as a complete explicit fact, missing evidence
    as incomplete, and multiple records for one required kind as ambiguous;
    never guess which durable record is current.

## Metric Pattern

Metrics are deterministic and independently testable.

A metric result includes:

1. Metric name
2. Metric value
3. Input evidence identifiers
4. Calculation version
5. Calculation timestamp
6. Availability or confidence status

## Policy Pattern

Policies evaluate metric and evidence facts against explicit assessment context.

Policy results must explain which requirement was evaluated and which evidence
or metric caused the result.

Avoid a universal repository quality score.

## AI Output Pattern

AI output uses a strict structured schema.

Every material conclusion uses a type-correct reference from the fixed report
input set: direct factual claims cite the relevant `EvidenceRecord`, calculated
claims cite the exact `MetricResult`, and policy conclusions cite the exact
`PolicyFinding`.

An unsupported material claim makes the output unusable; lowering confidence
does not substitute for the required deterministic validity gate.

## Workflow Pattern

For the concrete one-shot assessment boundary:

1. Validate before opening persistence or making a network call.
2. Persist and verify a valid request before collection.
3. Collect in canonical evaluator order with deterministic, versioned attempt
   identities and attempt number 1 per evidence kind.
4. Persist and reopen-verify each terminal collection outcome before starting
   the next collector.
5. Continue through available and unavailable evidence; persist the first
   retryable or nonretryable failure and stop without later collection or
   evaluation.
6. Evaluate exactly once only after durable loading verifies all four required
   evidence records.
7. Accept exact replay without duplicate durable rows and reject changed
   content under an existing attempt identity without mutation.

The one-shot boundary persists authoritative request and evidence outputs, not
workflow state. Retry, resume, reassessment, and current-evidence selection
require separate explicit rules and must not be inferred from this pattern.

## Testing Pattern

Every behavior change requires focused tests.

Deterministic calculations require unit tests.

External collectors require mocked failure tests.

Workflow stages require integration tests.

Bugs require regression tests.
