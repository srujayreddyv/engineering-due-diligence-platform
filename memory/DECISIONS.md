# Durable Decisions

## D001: The Decision Is the Core Abstraction

A repository alone is not sufficient to determine suitability.

Assessment context changes how evidence should be interpreted. The same project
may be suitable for an internal tool and unsuitable for a high criticality
authentication service.

## D002: Evidence Is Stored Separately from Conclusions

Raw evidence must be retained before metrics, policy findings, model
interpretations, or human decisions are produced.

This supports auditability, reproducibility, debugging, and reevaluation.

## D003: Deterministic Software Owns Metrics and Policy

The model does not calculate risk metrics or enforce policy.

Deterministic implementations are easier to test, version, reproduce, and
explain.

## D004: AI Is Used for Grounded Synthesis

AI is used for explanation, tradeoff analysis, uncertainty communication,
reviewer questions, and context aware report generation.

Generated conclusions must use type-correct identifiers from the fixed report
input set: direct factual claims cite `EvidenceRecord`, calculated claims cite
the exact `MetricResult`, and policy conclusions cite the exact
`PolicyFinding`.

## D005: Human Approval Is Required

The platform does not automatically approve or reject technology adoption.

The human reviewer owns the final decision.

## D006: The Initial System Is a Modular Application

The first version will not begin as a collection of microservices.

The architecture may be decomposed only when measured operational requirements
justify the additional complexity.

## D007: Four Week Scope Is Locked

New ideas are recorded in docs/backlog.md.

They enter active scope only when required for the primary workflow, correctness,
security, reliability, evaluation, or essential customer feedback.

## D008: SQLite Is the Prototype Durable Store

The first concrete persistence boundary uses an on-disk SQLite database through
Python's standard-library `sqlite3` module with a caller-supplied path,
foreign-key enforcement, transactional linked writes, and close-and-reopen
verification before authoritative evidence is returned.

The complete source response is stored separately from the compact normalized
`EvidenceRecord` snapshot. This is a prototype storage decision, not a
production database selection; PostgreSQL and production operations remain
deferred.

The concrete schema is versioned with `PRAGMA user_version`. Schema version 5
supports repository-archived, license-status, latest-commit timestamp, and
security-policy-presence evidence through separate typed value columns, plus
one canonical evaluation snapshot and at most one immutable human decision per
assessment. It also supports ordered source observations and multiple full
source snapshots for a bounded multi-request collection attempt. An exact
schema version 4 database migrates in one transaction by adding the two empty
tables, preserving all prior rows, and advancing the version only after schema,
row, and foreign-key verification; the earlier exact migration paths remain.
Latest-commit source timestamp text is preserved separately from its normalized
aware datetime and both must denote the same UTC instant. This does not
introduce a general migration framework or generic evidence-value store.

## D009: Direct Deterministic Review Is Sufficient for Prototype Decisions

ADR 0002 selects the verified deterministic assessment as sufficient human
review input for the prototype. A generated report remains a later presentation
capability and is not a prerequisite for human decision authority.

The implemented library boundary permits at most one immutable canonical
assessment-level evaluation snapshot and at most one immutable human decision
per assessment.
The snapshot references the existing request and authoritative evidence,
preserves the complete ordered metric and policy result plus exact evaluation
time and versions, and receives its own deterministic assessment-level
identity. A metric, finding, or policy-evaluation identifier is too narrow for
that purpose.

The allowed decisions are approve, approve with conditions, needs more
information, and reject. Needs-more-information consumes the single decision
slot; new material information or reconsideration requires a new assessment.
Actor identifiers remain asserted labels, conditions and information requests
remain ordered text, and no authentication, authorization, decision history,
workflow state, condition management, or general audit-event system is implied.
No current policy outcome is nonwaivable, but either approval must explicitly
acknowledge every reviewed nonpassing finding.
