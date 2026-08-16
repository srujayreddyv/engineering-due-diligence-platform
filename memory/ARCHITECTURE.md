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

A human reviewer owns the decision and may approve, approve with conditions,
record that more information is needed, or reject.

ADR 0002 selects direct review of the verified deterministic assessment for
the prototype. A generated report is a later presentation capability, not a
prerequisite for decision authority. The implemented durable boundary permits
at most one immutable assessment-level evaluation snapshot and at most one
immutable human decision per assessment. `needs_more_information` consumes
that decision slot; new material information or reconsideration requires a new
assessment in the one-shot model.

The decision-maker actor identifier must equal the request's responsible
reviewer actor identifier, but both are caller-asserted labels. The prototype
does not authenticate or authorize them. Conditions and information requests
are ordered human-readable statements without ownership, fulfillment, or
workflow semantics. No current policy outcome is nonwaivable, but either human
approval disposition must explicitly acknowledge every reviewed nonpassing
finding.

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

Schema v5 currently preserves the request, evidence, complete reviewed metric
and policy result with its versions, the optional human decision, and their
record timestamps. Prompt versions, model identifiers, generated reports, and
general audit history remain unimplemented. The deterministic Markdown review
is a transient presentation over verified records, not a generated or durable
business record and not an AI boundary.

The concrete prototype store is a caller-supplied on-disk SQLite database
accessed directly through Python `sqlite3`. Schema version 5 covers complete
valid assessment requests, terminal outcomes from all four public GitHub
collectors, one canonical assessment-evaluation snapshot per assessment, and
at most one immutable human decision per assessment. Exact schema version 4
databases migrate transactionally by adding the two empty Day 16 tables while
preserving every prior row; they receive no fabricated historical evaluation
or decision. The earlier exact migrations remain supported, and unsupported or
altered schemas fail closed.

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

The durable evaluation read boundary opens only an existing exact schema-v5
database in SQLite read-only and query-only modes. One read transaction
reconstructs the valid request and exactly one `EvidenceRecord` for repository
archived, license status, latest commit timestamp, and security policy presence
in canonical evaluator order. Unavailable evidence satisfies completeness;
missing or ambiguous kinds fail closed. Every selected record is reconstructed
from its durable collection attempt and complete source material before it can
enter the unchanged deterministic evaluator.

Schema v5 adds only one canonical, versioned `AssessmentEvaluationSnapshot` and
one `HumanDecision` concept. The
evaluation identity payload preserves the complete ordered deterministic
result, exact evaluation time, assessment and evidence references, and required
versions while leaving request context and raw evidence in their existing
authoritative records. `snapshot_json` contains exactly that canonical payload
and excludes the generated evaluation ID and integrity digest. The integrity
digest covers exactly the canonical payload bytes, and a new namespaced
assessment-level identifier is derived from the same payload; the narrower
`policy_evaluation_id` is not reused. Both record types retain exact
migration, fail-closed, replay, conflict, temporal, and close-and-reopen
verification behavior. The human decision is bound to the same assessment and
evaluation, to the request's asserted responsible reviewer identifier, and to
the exact ordered acknowledgment rules. The library and noninteractive
`review` and `decide` commands expose this boundary without changing it.

The review read boundary uses one read-only, query-only SQLite transaction to
reconstruct the valid request, four authoritative evidence records, exact
evaluation snapshot, and optional human decision. It captures no time, performs
no network request or write, creates no artifact, and uses deterministic
reconstruction only at the snapshot's stored `evaluated_at` as required for
authority verification. Decision replay status is transient operation output
derived inside the existing write transaction; it is not a durable field.

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
evaluation. Metrics and findings are calculated as deterministic domain
records and preserved together inside the one durable reviewed-evaluation
snapshot rather than in independently managed tables.

`collection_attempted_at` remains durable execution-input provenance; the CLI
supplies it. After all four authoritative records exist, the workflow first
loads any verified evaluation snapshot. Exact replay evaluates at and returns
the stored original time without reading the clock. Only a first evaluation
captures `evaluated_at` through one private clock, passes it unchanged to the
deterministic evaluator, and persists and reopen-verifies the resulting
snapshot before returning completion. Temporal violations still fail closed.

This boundary is not a durable workflow engine. It adds no workflow-state
record, retry, resume, reassessment, or current-evidence selection. Exact replay
is idempotent; changed collection or evaluation content under an existing
identity conflicts without mutation.

## Command-Line Boundary

The dependency-free customer boundary is a noninteractive
`assess -> review -> decide` flow. `assess` owns generation of the assessment
ID, submission timestamp, and collection timestamp, then delegates exactly once
to the one-shot execution boundary. It does not duplicate validation,
collection, persistence, metric, or policy logic and does not accept or record
a human decision.

`review` accepts an existing assessment ID and returns versioned JSON containing
the verified request context, canonical evidence summaries and references,
complete durable metrics and policy findings, evaluation identity and integrity
data, required approval acknowledgments, and any existing verified decision.
It also accepts `--format markdown` to render
`assessment-review-report.v1` from the same already-loaded verified review
object. Both formats are direct presentations of durable deterministic records,
not a generated recommendation. Markdown is transient and deterministic, reads
no clock, performs no additional load or write, and preserves the visible
separation between evidence, metrics, findings, and the human decision.

`decide` accepts the exact assessment and evaluation identifiers plus the eight
existing caller-supplied decision business fields. It verifies the referenced
evaluation before invoking the existing immutable persistence boundary, which
remains authoritative for reviewer matching, disposition shape,
acknowledgments, timestamps, replay, and conflicts. Successful versioned JSON
returns `recorded` or `exact_replay`; changed business content uses exit code 6.
Complete GitHub source responses remain only in SQLite, all failures are
sanitized, and no command adds an HTTP API, interactive input, authentication,
authorization, AI synthesis, report persistence, workflow state, or condition
management.

## Deterministic System Evaluation Boundary

The system-level conformance harness lives under `scripts/`, outside the
production package. It declares ten frozen scenarios, patches only existing
transport, identity, and clock seams, and exercises the real CLI, collectors,
schema-v5 persistence, deterministic evaluator, review renderer, and decision
boundary with temporary databases. It does not duplicate collectors, metrics,
policy decisions, review rendering, or durable records.

Successful scenarios rerun from fresh databases and compare stable JSON,
Markdown, and applicable decision output bytes. The context pair holds source
responses, evaluation time, repository facts, and metric projections constant
while changing only assessment risk tolerance. Expected failure scenarios
verify partial durable evidence and corrupt evaluation behavior without
converting failures into conclusions.

This boundary demonstrates current implementation conformance. It is not part
of the customer runtime, does not use a live network, and does not validate
policy fitness, statistical accuracy, customer ROI, or live-repository realism.
Its single versioned JSON summary is transient evaluation output, not a new
business or persistence record.

## Initial Deployment Shape

The first version is a modular backend application rather than a distributed
microservice system.

Additional infrastructure requires demonstrated workflow, reliability, or
scaling needs.
