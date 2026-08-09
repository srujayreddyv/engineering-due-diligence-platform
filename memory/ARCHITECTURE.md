# Architecture Memory

## Core Abstraction

The core abstraction is an assessment decision, not a repository.

A repository can receive different recommendations depending on intended use,
environment, criticality, expected lifetime, and organizational risk tolerance.

## Architectural Boundaries

The initial system is organized around these boundaries:

1. Assessment API
2. Workflow orchestration
3. Evidence collection
4. Evidence persistence
5. Deterministic metric calculation
6. Policy evaluation
7. AI report generation
8. Human review
9. Audit history
10. Observability

## Evidence Boundary

Raw evidence must be stored before calculations or conclusions are generated.

Evidence records must preserve their source, collection time, status, and
provenance where available.

Calculated metrics, policy findings, model interpretations, and human decisions
must remain distinguishable.

## AI Boundary

The model may synthesize evidence, explain tradeoffs, identify uncertainty,
generate reviewer questions, and translate technical findings into operational
consequences.

The model must not collect authoritative evidence, calculate deterministic
metrics, define workflow state, grant approval, or invent missing facts.

## Human Decision Boundary

The system provides decision support.

A human reviewer owns the final decision and may approve, approve with
conditions, request further investigation, or reject.

## Persistence Boundary

The system must preserve:

1. Original request
2. Raw evidence
3. Calculated metrics
4. Policy findings
5. Policy version
6. Prompt version
7. Model identifier
8. Generated report
9. Human decision
10. Audit timestamps

The concrete prototype store is a caller-supplied on-disk SQLite database
accessed directly through Python `sqlite3`. Schema version 4 covers complete
valid assessment requests plus terminal public GitHub repository-archived,
license-status, latest-commit timestamp, and effective-security-policy
collection outcomes. Exact schema version 3 databases migrate transactionally
while preserving existing archived, license, and latest-commit content; the
existing exact version 1 and 2 migrations remain supported. Unsupported
versions or altered schemas fail closed.

The persistence boundary uses linked assessment requests, collection attempts,
ordered source observations, complete GitHub source snapshots, and compact
normalized evidence. Single-request collectors need one snapshot; the security
policy collector may retain multiple snapshots and the complete ordered probe
sequence. Full HTTP 200 response bytes are stored separately from the canonical
compact `EvidenceRecord` snapshot. Evidence-producing writes commit every
required attempt, observation, snapshot, and evidence row atomically; failed
security-policy searches retain completed observations but produce no Boolean
evidence.

Available or unavailable evidence is authoritative only after the database is
closed, reopened, and its exact fields, relationships, payload binding,
digests, versions, normalization, and existing value invariants are verified.
Repository-archived and security-policy evidence use separate strict Boolean
columns; license-status evidence uses the strict `present` or `absent` column;
latest-commit evidence uses a strict aware timestamp representation;
unavailable evidence uses no typed value column. Latest-commit source timestamp
spelling is preserved separately from its normalized value, and both must
denote the same UTC instant. Exact replay is accepted without duplicates,
conflicting replay is rejected, and incomplete or unverifiable writes fail
closed. All four evaluator-required evidence kinds are durable, but durable
loading and deterministic evaluation integration remain unimplemented.

## Initial Deployment Shape

The first version is a modular backend application rather than a distributed
microservice system.

Additional infrastructure requires demonstrated workflow, reliability, or
scaling needs.
