# ADR 0002: Use Direct Deterministic Review for Prototype Decisions

## Status

Accepted on 2026-08-11.

## Context

The implemented prototype produces one verified deterministic assessment for a
public GitHub repository and one specified use case. The request and raw
evidence are durable in SQLite schema version 4, while the complete metric and
policy result remains transient and is emitted by the `assess` CLI.

The earlier logical domain model placed a valid generated report between policy
evaluation and human decision, assumed authorization and participant rules,
allowed nonfinal investigation decisions before a final decision, and paired
completion with workflow state and general audit events. None of those
capabilities exists in the current runtime. Requiring them before a human can
record an adoption decision would expand the next slice beyond the smallest
customer workflow and would incorrectly make a presentation layer an authority
prerequisite.

The prototype still needs to preserve exactly what the human reviewed, keep
deterministic findings distinct from the human disposition, and make no claim
that caller-supplied actor labels are authenticated identities.

## Decision

For the prototype, a human may record a decision directly against one durable,
reopen-verified snapshot of the complete deterministic assessment. A generated
report is an optional later presentation capability and is not a prerequisite
for review or decision authority.

Each assessment has at most one immutable assessment-level evaluation snapshot
and at most one immutable human-decision record. The allowed decision values
are:

* `approve`;
* `approve_with_conditions`;
* `needs_more_information`; and
* `reject`.

`needs_more_information` consumes the assessment's only decision slot. New
material information, reconsideration, or a different disposition requires a
new assessment under the current one-shot model. The prototype has no decision
editing, supersession, correction, prior-decision link, or decision-history
workflow.

The durable evaluation snapshot references the existing immutable request and
authoritative evidence rather than copying them. Its canonical identity payload
preserves the assessment ID, exact evaluation time, canonical ordered evidence
references, complete ordered metric results, complete ordered policy findings,
all required result versions, and a snapshot schema version. `snapshot_json`
stores exactly that payload. The durable row is a separate envelope containing
the generated evaluation ID, the relational assessment ID, and an integrity
digest; generated identifiers and digests are never members of their own hash
inputs. A new assessment-level deterministic identifier covers the complete
canonical payload; narrower metric, finding, and policy-evaluation identifiers
are not reused.

The human decision records only the assessment and evaluation references,
asserted decision-maker actor ID, disposition, rationale, ordered condition or
information-request statements where required, acknowledged nonpassing finding
IDs, recording time, schema version, and deterministic record identity.
At most one row is permitted per assessment.

The decision-maker actor ID must equal the persisted request's
`responsible_reviewer_actor_id`. This is exact identifier consistency only. The
prototype performs no authentication or authorization and must not describe
the actor as verified or authorized.

No current policy outcome is nonwaivable. Policy findings remain deterministic
facts separate from the human disposition. Either approval disposition must
explicitly acknowledge every reviewed finding whose outcome is not `pass`.
`reject` and `needs_more_information` contain no finding acknowledgments.
Acknowledgment does not alter, suppress, or convert the finding.

The human-decision identity payload contains the normalized decision business
fields, the first system-captured recording time, and the decision schema
version, but excludes the generated human-decision ID and any current or future
digest. Exact replay compares only the normalized caller-supplied assessment,
evaluation, actor, disposition, rationale, ordered conditions, ordered
information requests, and ordered acknowledgment fields. Generated ID and time
therefore cannot make an otherwise exact replay conflict.

Conditions and information requests are ordered nonempty human-readable
statements. The platform does not assign condition owners, track status,
verify fulfillment, or claim that conditions were satisfied.

Schema version 5 adds only the assessment-evaluation-snapshot and human-decision
durable concepts. It preserves existing fail-closed,
transactional migration, exact replay, conflict, close-and-reopen verification,
integrity, and temporal principles without adding a persistence abstraction,
workflow engine, or general audit-event model.

## Superseded Prototype Assumptions

For the prototype human-decision boundary, this ADR supersedes earlier logical
model provisions that:

* require a generated report before human review or decision;
* require authenticated or authorized decision makers or participant roles;
* permit multiple human-decision records for investigation followed by a final
  decision;
* require decision-submission identities, prior-decision links, workflow state,
  or general audit events; or
* define condition ownership, verification, monitoring, or fulfillment.

The broader target architecture may reconsider those capabilities after the
one-shot prototype is complete, but they are not implicit in this decision.

## Consequences

### Positive

* The prototype can complete the primary customer workflow without adding AI,
  authentication, or workflow infrastructure.
* The human remains the only authority for adoption disposition.
* The exact metric and policy result reviewed becomes durable and independently
  inspectable without duplicating request context or raw evidence.
* At most one evaluation and one decision per assessment eliminate current
  selection, supersession, and decision-history rules.
* Nonpassing policy findings remain visible even when a human accepts the risk.

### Negative

* A deterministic assessment is less polished than a generated decision brief.
* A caller can assert another person's actor identifier; the database proves
  only consistency with the request label.
* `needs_more_information` closes the current assessment rather than routing a
  continuation.
* Conditions are recorded commitments but have no fulfillment lifecycle.
* Existing schema-v4 assessments cannot be given an exact historical
  evaluation snapshot because their transient evaluation time and output were
  not preserved.

## Rejected Alternatives

### Require a generated report first

Rejected for the prototype because a report is presentation and interpretation,
not the source of deterministic authority, and implementing it would add AI and
validation scope before the human decision path.

### Reuse `policy_evaluation_id`

Rejected because it groups a policy finding set and does not identify the
complete assessment-level result containing evidence references, metrics, and
findings.

### Persist metrics and findings as independently managed tables

Rejected for this one-shot boundary because it introduces separate selection
and lifecycle concerns. One canonical versioned assessment snapshot preserves
the exact reviewed result while keeping request and evidence authority in their
existing records.

### Allow investigation and final decision records in one assessment

Rejected because it requires continuation, current-input selection, and
decision-history rules. A new assessment is the current recovery boundary for
new material information.

### Add authentication, authorization, workflow state, or audit events

Rejected because those systems are not required to prove the selected
prototype boundary and would imply guarantees the runtime does not provide.

## Scope and Implementation Status

This ADR selected the architecture on Day 15. Day 16 implements the contracts,
schema-v5 migration, durable snapshots, immutable decision library boundary,
and workflow snapshot integration. The CLI remains unchanged and does not yet
record human decisions. The locked design remains in
`plans/day_15_human_decision_boundary.md`.
