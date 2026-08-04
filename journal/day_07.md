# Day 7 Journal

## Review Performed

Completed a read-only persistence direction review over the committed Day 3
through Day 6 plans, domain and failure models, durable project memory, current
request and collection boundaries, evidence and evaluation contracts, and all
related tests.

The review traced the intended boundary:

```text
validated request
-> GitHub collection
-> durable source snapshot
-> authoritative EvidenceRecord
-> deterministic evaluation
```

The complete test baseline passed before documentation was finalized:

```text
Ran 88 tests
OK
```

No relevant ADR existed before this review.

## Decisions Accepted

* Use a caller-supplied on-disk SQLite database through Python `sqlite3` as the
  concrete prototype durable store.
* Persist and reopen-verify the complete valid Day 5 request before collection
  begins.
* Store the complete successful GitHub response separately from the compact
  canonical `EvidenceRecord` snapshot.
* For an available result, commit the collection attempt, full source snapshot,
  and normalized evidence row in one transaction.
* For 404, commit the collection attempt and unavailable evidence row in one
  transaction.
* Persist retryable and nonretryable failures only as complete collection
  attempts because the current Day 3 evidence outcome contract cannot
  represent them.
* Close the database connection and reopen the on-disk database before
  returning available or unavailable evidence.
* Rerun exact field, relationship, source-response digest, payload binding,
  compact-snapshot digest, normalization, and existing constructor checks after
  reopening.
* Accept exact request and collection replay without duplicate rows and reject
  conflicting replay without mutation.
* Keep the first implementation concrete and specific to repository archived
  status.

## Corrections to the Initial Proposal

The final direction removed three unnecessary elements from the initial review
proposal:

1. It does not add constant persisted `workflow_state` or
   `validation_status` columns. The persistence boundary accepts only a valid
   Day 5 result, stores its exact submitted fields and normalized identity, and
   adds no workflow behavior.
2. It does not add request-content or collection-result digests. Exact stored
   field comparison is sufficient. Only the existing Day 6 full-response
   digest and Day 3 compact-snapshot digest remain.
3. It does not design a special commit-uncertainty recovery mechanism. A
   commit exception fails closed. A later exact replay may inspect and accept
   already durable content only after complete verification.

The final scope also excludes evaluator integration. Day 8 may return a
verified existing `EvidenceRecord`, but connecting collection persistence to a
complete four-kind assessment remains later work.

## Risks

* SQLite is appropriate for the local prototype but does not establish
  production database, concurrency, backup, encryption, access-control, or
  deployment readiness.
* The compact `EvidenceRecord.raw_snapshot` name may be confused with the full
  GitHub response; the durable source-snapshot link and documentation must keep
  them distinct.
* Day 6 currently has no explicit response-size limit.
* A successful commit followed by failed reopening or verification leaves
  content that must not be returned as authoritative until a later exact replay
  verifies it.
* Retryable and nonretryable collection failures remain in collection-attempt
  storage only until a later deliberate evidence-outcome expansion.
* The first database schema will be intentionally incomplete and specific to
  validated requests and repository archived collection outcomes.

## Deferred Work

Day 7 did not implement or authorize:

* persistence source code, schemas, database files, or tests;
* workflow state, transitions, transition history, retries, scheduling,
  interruption recovery, or audit events;
* APIs, CLIs, ORMs, repository patterns, storage ports, provider abstractions,
  or migration frameworks;
* remaining GitHub collectors or authenticated sources;
* deterministic evaluator integration or metric and policy persistence;
* reporting, model integration, human review, or decisions; or
* PostgreSQL, deployment, concurrency optimization, backup, encryption, access
  control, or production operations.

## Day 8 Direction

The next implementation task should create only one concrete SQLite
persistence module and one focused persistence test module. It should persist a
complete valid Day 5 request and every terminal Day 6 collection outcome,
separate full available source responses from compact evidence snapshots,
return available or unavailable evidence only after close-and-reopen
verification, and enforce exact replay and conflicting replay behavior.

No Day 8 persistence code was implemented during Day 7.
