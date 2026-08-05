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
accessed directly through Python `sqlite3`. Schema version 1 currently covers
only complete valid assessment requests and terminal public GitHub
repository-archived collection outcomes.

The persistence boundary uses four linked records: assessment request,
collection attempt, complete GitHub source snapshot, and compact normalized
evidence. The full successful response is stored separately from the canonical
compact `EvidenceRecord` snapshot. Available writes commit the attempt, source
snapshot, and evidence atomically; 404 writes commit the attempt and
unavailable evidence atomically; other terminal failures persist only the
attempt.

Available or unavailable evidence is authoritative only after the database is
closed, reopened, and its exact fields, relationships, payload binding,
digests, versions, normalization, and existing value invariants are verified.
Exact replay is accepted without duplicates, conflicting replay is rejected,
and incomplete or unverifiable writes fail closed. This boundary is not yet
connected to deterministic evaluation or workflow orchestration.

## Initial Deployment Shape

The first version is a modular backend application rather than a distributed
microservice system.

Additional infrastructure requires demonstrated workflow, reliability, or
scaling needs.
