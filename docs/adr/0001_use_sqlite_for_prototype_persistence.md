# ADR 0001: Use SQLite for Prototype Persistence

## Status

Accepted on 2026-08-03.

## Context

The prototype has a validated transient assessment request, one transient
public GitHub repository-metadata collector, immutable evidence contracts, and
deterministic metric and policy evaluation. It does not yet have a durable
boundary between collection and evaluation.

Raw evidence must be stored before an `EvidenceRecord` becomes eligible for
deterministic evaluation. The persistence boundary must store a valid request
before collection begins, atomically store the linked terminal collection
records, reject conflicting replay, and close and reopen storage before
returning authoritative evidence.

The four-week scope favors the smallest concrete implementation that supplies
real transaction, relationship, and integrity behavior without introducing a
database service, ORM, storage abstraction, or deployment infrastructure.

## Decision

The prototype durable store will be an on-disk SQLite database accessed through
Python's standard-library `sqlite3` module.

The caller supplies the database path. In-memory SQLite databases are not valid
for the durable boundary.

Every connection enables SQLite foreign-key enforcement. Explicit transactions
protect linked writes. In particular, an available repository-metadata
collection writes its collection attempt, complete GitHub source snapshot, and
normalized evidence row in one transaction. A 404 unavailable outcome writes
its attempt and unavailable evidence row atomically. Other terminal failures
store only their collection-attempt row.

The complete successful GitHub response is stored separately from the compact
canonical snapshot required by the existing `EvidenceRecord`. The source
snapshot retains the existing Day 6 SHA256 digest. The normalized evidence
retains its existing Day 3 compact-snapshot digest and links back to the full
source snapshot through provenance.

A valid request is committed and verified before collection begins. After a
successful evidence commit, the connection is closed, the on-disk database is
reopened, and all required relationships, exact fields, digests, source
binding, normalization, and existing value invariants are verified before an
`EvidenceRecord` is returned.

Exact replays are accepted without duplicate records. Reusing an identity with
conflicting content is rejected without mutation. A commit exception fails
closed; a later exact replay may accept already durable content after complete
verification, but there is no special commit-uncertainty recovery protocol.

The first implementation is concrete and limited to repository archived
status. It uses parameterized SQL directly and adds no ORM, repository pattern,
storage interface, provider abstraction, workflow engine, retry executor, or
evaluator integration.

## Consequences

### Positive

* The prototype gains real on-disk durability and atomic multi-record writes
  using only the Python standard library.
* Foreign keys and uniqueness constraints can enforce request, attempt,
  snapshot, and evidence relationships.
* Close-and-reopen tests can prove that returned evidence was reconstructed
  from durable content rather than retained process memory.
* The full source response and compact normalized evidence remain distinct,
  preserving both Day 6 provenance and Day 3 integrity checks.
* The design remains local and modular without introducing a database service
  or premature portability layer.

### Negative

* SQLite introduces a concrete storage dependency into the prototype and will
  require deliberate migration if a later production design selects another
  database.
* SQLite durability depends on correct connection settings and the behavior of
  the host operating system, filesystem, and storage device.
* The initial schema is specific to the archived-status persistence slice and
  is not a complete assessment database.
* Backup, restore, encryption, access control, file permissions, concurrent
  writers, and operational maintenance are not solved by selecting SQLite.

## Rejected Alternatives

### One JSON file

Rejected because linked request, attempt, source-snapshot, and evidence updates
would require application-owned transaction, locking, uniqueness, and recovery
logic.

### Separate files with atomic rename

Rejected because a rename can make one file replacement atomic but cannot make
the complete linked record set commit atomically or enforce foreign keys.

### Append-only JSON Lines

Rejected because exact replay, conflicting replay, referential integrity, and
complete-record selection would become custom database behavior.

### `shelve` or `dbm`

Rejected because they do not provide the required relational constraints and
multi-record transactions.

### PostgreSQL now

Deferred because it requires a database service, driver, configuration,
deployment, and operational setup before the first persistence boundary is
proven. The planned production technology has not been rejected.

## Scope and Deferred Decisions

SQLite is the concrete prototype store. It is not a production database
decision.

PostgreSQL selection and implementation, deployment infrastructure,
concurrency optimization, connection pooling, backup and restore, encryption,
file and database access control, retention, monitoring, and production
operations remain deferred.

Workflow state transitions, transition history, audit events, automatic
retries, remaining collectors, metric and policy persistence, reports, APIs,
CLIs, and model integration also remain outside this decision.
