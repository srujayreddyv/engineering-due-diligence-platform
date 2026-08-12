# Day 15 Journal

## Work Completed

Completed the design-only human review and repository-adoption decision
direction. No production code, tests, SQLite schema, migration, CLI behavior,
or README content was changed.

The work began from the completed read-only review of the implemented request,
evidence, deterministic evaluation, one-shot workflow, CLI, persistence,
documentation, and tests. The authoritative product decisions supplied for Day
15 were applied without reopening deferred workflow, authentication, reporting,
or condition-management scope.

Created:

* `plans/day_15_human_decision_boundary.md`;
* `docs/adr/0002_direct_deterministic_review_for_prototype_decisions.md`; and
* `journal/day_15.md`.

Updated durable architecture memory in `memory/ARCHITECTURE.md` and
`memory/DECISIONS.md` because direct deterministic review materially supersedes
the earlier generated-report prerequisite and multiple-decision assumptions for
the prototype.

## Final Direction

### Review input

Direct human review of the verified deterministic assessment is sufficient for
the prototype. A generated report is a later presentation capability and is
not required to establish decision authority.

The reviewed input will become one immutable
`AssessmentEvaluationSnapshot`. It represents the complete assessment-level
deterministic result rather than only a metric, finding, or policy evaluation.
The existing `policy_evaluation_id` was inspected and rejected as the snapshot
identity because it groups the policy finding set and is calculated before the
complete finding records exist.

The planned canonical evaluation identity payload contains:

1. assessment identity;
2. exact aware evaluation time;
3. the four ordered evidence kind and evidence ID references;
4. the four complete ordered metric results;
5. the four complete ordered policy findings;
6. all metric, policy, requirement, engine, and record-schema versions already
   carried by those results;
7. the evaluation-snapshot schema version.

That canonical identity payload expressly excludes the generated assessment-
evaluation ID and integrity digest. `snapshot_json` stores only the canonical
payload, not a self-containing envelope. The durable row supplies the generated
ID and digest around it; only the assessment ID is also projected into a
relational column so SQLite can enforce the assessment relationship.

Request context and raw evidence remain in their existing authoritative SQLite
records and are not duplicated into the snapshot.

### Decision vocabulary and cardinality

The decision values are:

* `APPROVE`;
* `APPROVE_WITH_CONDITIONS`;
* `NEEDS_MORE_INFORMATION`; and
* `REJECT`.

At most one immutable human decision is allowed per assessment.
`NEEDS_MORE_INFORMATION` consumes that single slot. The prototype does not
model a sequence from investigation to final decision. Materially new
information, reconsideration, or a changed disposition requires a new
assessment in the existing one-shot model.

`APPROVE_WITH_CONDITIONS` is an adoption disposition subject to the recorded
ordered condition statements. The platform does not assign condition owners,
track condition status, verify fulfillment, or claim satisfaction.

### Policy findings and human authority

No current policy outcome is nonwaivable. `PASS`, `FAIL`,
`CONDITION_REQUIRED`, and `NOT_EVALUABLE` remain immutable deterministic
findings rather than automatic adoption decisions.

For `APPROVE` or `APPROVE_WITH_CONDITIONS`, the human decision must explicitly
acknowledge every finding in the reviewed snapshot whose outcome is not
`PASS`. The acknowledgments preserve reviewed finding order and do not alter or
silence the findings. For `REJECT` and `NEEDS_MORE_INFORMATION`, the
acknowledgment tuple must be empty.

### Reviewer identity

The decision-maker actor ID must exactly equal the persisted request's
`responsible_reviewer_actor_id`. This is string-level identifier consistency
only. Both values are caller asserted, and the design makes no authentication,
authorization, role, participation, or sign-off claim.

### Human decision content

The planned immutable decision contains only:

* human decision ID;
* assessment ID;
* assessment-evaluation ID;
* asserted decision-maker actor ID;
* disposition;
* rationale;
* ordered conditions;
* ordered information requests;
* ordered acknowledged policy-finding IDs;
* system-captured recorded time; and
* decision schema version.

There is no decision submission identity, prior decision link, finality field,
edit timestamp, correction behavior, workflow state, audit event, condition
owner, or fulfillment status.

## Proposed Schema Version 5

The selected schema-v5 shape adds only:

1. `assessment_evaluation_snapshots`; and
2. `human_decisions`.

The evaluation table stores at most one row per assessment. Its `snapshot_json`
is exactly the canonical versioned identity payload; the row is a separate
envelope containing the generated evaluation ID, relational assessment ID, and
integrity digest. Evaluated time and evaluation schema version remain in the
payload rather than being duplicated as envelope columns. The decision table
stores at most one row per assessment and uses a same-assessment foreign-key
relationship to the evaluation snapshot. Conditions, information requests,
and acknowledged finding IDs are canonical ordered JSON string arrays within
the decision row; they do not create independently managed domain tables.

An exact v4-to-v5 migration will create the two empty tables transactionally,
prove that all v4 rows remain unchanged, verify exact schema and foreign keys,
and advance the version only after validation. It will not fabricate evaluation
snapshots for existing v4 assessments because their transient evaluation time
and output were not preserved.

SQLite remains schema version 4 on Day 15.

## Identifier and Replay Decisions

The assessment-evaluation ID is a full SHA256-based identity over a versioned
namespace and the complete canonical evaluation payload bytes. Its integrity
digest hashes exactly the same payload bytes without the namespace. Neither
generated value is inside `snapshot_json` or either hash input. The two hashes
intentionally cover the same content: the namespaced form is a typed domain
identity, while the plain digest verifies the stored payload bytes.

The human-decision ID is a full SHA256-based identity over the complete
recorded decision payload, including its first durable `recorded_at` and
excluding the generated `human_decision_id` and any future digest. There is no
decision submission ID.

Evaluation replay returns the assessment's existing verified snapshot and does
not capture a later evaluation time. A changed snapshot for the same assessment
conflicts without mutation.

Decision replay looks up the assessment's unique decision and compares exactly
the normalized caller-supplied assessment ID, evaluation ID, actor ID,
disposition, rationale, ordered conditions, ordered information requests, and
ordered acknowledgment IDs. Identical content returns the existing verified
decision with its original system-generated ID and timestamp; neither system
field participates in replay comparison. Any changed business field conflicts
without mutation. There is no replacement path.

## Future Customer Interaction

The planned CLI is one noninteractive `decide` command requiring the database,
assessment ID, explicit assessment-evaluation ID, asserted reviewer actor ID,
decision, and rationale. Repeated condition, information-request, and finding-
acknowledgment flags preserve user order. IDs, timestamps, versions, roles,
authorization, workflow state, condition owners, and condition status are not
user-overridable inputs.

The command will perform no network activity and will return one versioned,
machine-readable decision document after durable reopen verification. It is not
implemented on Day 15.

## Architectural Decision

ADR 0002 records why the prototype may review deterministic output directly
and explicitly supersedes earlier prototype assumptions that required a
generated report, authorization rules, multiple decision records, workflow
state, decision history, general audit events, or condition management.

This change preserves the larger architectural boundaries: evidence remains
the source of truth, metrics and policy remain deterministic, and only the
human decision records adoption disposition.

## Review and Verification

Reviewed the Day 15 documents for:

* consistency with all thirteen authoritative product decisions;
* assessment-level rather than policy-level evaluation identity;
* at most one evaluation and one decision per assessment;
* complete deterministic result preservation without request or evidence
  duplication;
* direct review without report, AI, authentication, or authorization claims;
* disposition-specific conditions and information requests;
* complete nonpassing-finding acknowledgment for approvals;
* immutable and fail-closed replay behavior;
* exact v4-to-v5 migration direction and no legacy backfill fabrication;
* absence of workflow, audit, decision-history, and condition-management scope;
  and
* honest separation between selected design and unimplemented functionality.

No automated tests were run because no runtime behavior changed. Documentation
verification is limited to content review, whitespace checking, diff review,
and confirmation that no prohibited files changed.

## Risks and Remaining Issues

No product decision remains open before implementation. The future
implementation must reproduce and test the byte-exact serializer locked in the
plan before writing schema-v5 data and must retain support for every definition
version accepted into a snapshot. These are engineering acceptance details,
not new product scope.

Existing schema-v4 assessments remain valid evidence histories but are not
decision-eligible because their exact reviewed evaluation was not durable. The
migration will not invent missing historical output.

## Explicit Exclusions

Day 15 adds no production models, persistence functions, migration code,
workflow changes, tests, CLI parsing or output, report generation, AI,
authentication, authorization, retry, resume, reassessment, current-evidence
selection, decision history, corrections, workflow state, general audit
events, condition management, HTTP API, ORM, PostgreSQL, or README feature
claim.

## Recommended Day 16 Slice

Implement the durable boundary without the customer-facing `decide` command:

1. add the frozen evaluation-snapshot and human-decision contracts plus their
   deterministic identifiers;
2. implement the exact schema-v5 migration containing both selected tables;
3. implement canonical evaluation snapshot serialization, persistence,
   close-and-reopen deterministic verification, and exact replay;
4. integrate one-snapshot persistence into completed one-shot assessment
   execution; and
5. implement and test the human-decision persistence boundary, validation,
   one-row invariant, replay, conflict, and reopen verification through a
   library function.

Keep the CLI unchanged until that durable boundary is complete and reviewed.
A subsequent narrow slice can add only the `decide` command over the verified
library behavior.
