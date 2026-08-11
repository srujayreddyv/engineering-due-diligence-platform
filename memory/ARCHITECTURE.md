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
closed.

The durable evaluation read boundary opens only an existing exact schema-v4
database in SQLite read-only and query-only modes. One read transaction
reconstructs the valid request and exactly one `EvidenceRecord` for repository
archived, license status, latest commit timestamp, and security policy presence
in canonical evaluator order. Unavailable evidence satisfies completeness;
missing or ambiguous kinds fail closed. Every selected record is reconstructed
from its durable collection attempt and complete source material before it can
enter the unchanged deterministic evaluator. Metrics and policy findings remain
transient and no schema change is required for this integration.

## One-Shot Execution Boundary

The first application workflow is a concrete one-shot library boundary. It
validates the submitted request, persists and reopen-verifies a valid request,
then collects and persists repository archived status, license status, latest
commit timestamp, and security policy presence in canonical evaluator order.
Every terminal outcome crosses its existing transaction and close-and-reopen
authority boundary before the next collector begins.

Collection attempt identities are deterministic versioned SHA256 values based
on assessment ID, evidence kind, and attempt number 1. Available and
unavailable evidence continue the workflow. The first retryable or
nonretryable failure is persisted and stops later collection and evaluation.
Only the complete verified four-kind evidence set enters deterministic
evaluation, and metrics and findings remain transient.

`collection_attempted_at` remains durable execution-input provenance; the CLI
supplies it. The workflow captures `evaluated_at` through one private clock only
after all four authoritative records exist and passes the exact aware value
unchanged to the transient evaluator. Exact evidence replay may therefore be
reevaluated at a later timestamp without database mutation; temporal violations
still fail closed.

This boundary is not a durable workflow engine. It adds no schema change,
workflow-state record, retry, resume, reassessment, or current-evidence
selection. Exact replay is idempotent; changed collection content under an
existing attempt identity conflicts without mutation.

## Command-Line Boundary

The first customer-facing boundary is one dependency-free `assess` command. It
owns generation of the assessment ID, submission timestamp, and collection
timestamp, then delegates exactly once to the one-shot execution boundary. It
does not duplicate validation, collection, persistence, metric, or policy
logic.

The command returns one versioned JSON document with submitted context,
canonical evidence summaries, deterministic metrics, policy findings, and an
explicit `not_implemented` human-decision status. Complete GitHub source
responses remain only in SQLite. Stable exit codes distinguish usage,
validation, collection, persistence or verification, unexpected internal, and
complete outcomes; failure output is sanitized. This boundary adds no HTTP API,
authentication, report generation, human-decision persistence, or schema
change.

## Initial Deployment Shape

The first version is a modular backend application rather than a distributed
microservice system.

Additional infrastructure requires demonstrated workflow, reliability, or
scaling needs.
