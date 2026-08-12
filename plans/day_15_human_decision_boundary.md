# Day 15 Human Decision Boundary Plan

## Task

Lock the smallest human review and repository-adoption decision boundary over
the verified deterministic assessment. This is a design-only Day 15 task; it
does not implement production code, tests, migrations, or CLI behavior.

## Objective

Define at most one durable assessment-level evaluation snapshot and at most one
immutable human decision per assessment. The design must establish what the
reviewer saw, who was asserted as the responsible reviewer, what disposition
they recorded, why they recorded it, and the decision time without introducing
authentication, generated-report prerequisites, workflow state, decision
history, condition management, or general audit infrastructure.

The direction is ready for implementation planning when the contracts, schema
v5 shape, deterministic identifiers, replay rules, integrity checks, and
future `decide` command are unambiguous and consistent with the existing
one-shot architecture.

## Current State

The implemented runtime validates and persists one assessment request,
collects and reopen-verifies four authoritative evidence records, and returns
one complete transient `DeterministicAssessmentResult`. That result contains
the assessment context, the four evidence records in canonical order, four
deterministic `MetricResult` values, four deterministic `PolicyFinding`
values, and the exact aware `evaluated_at` captured by the workflow.

SQLite schema version 4 stores the immutable request, collection attempts,
complete source snapshots, ordered source observations, and normalized
evidence. Metrics, policy findings, the assessment-level evaluation, and human
decisions are not durable. The Day 14 CLI emits the deterministic result as
`assessment-cli-output.v1` and explicitly reports that the human decision is
not implemented.

Existing metric identifiers identify individual calculations. The existing
`policy_evaluation_id` groups one policy finding set and is derived from policy
inputs before the complete `PolicyFinding` records are constructed. Neither is
an identity for the complete assessment-level deterministic result, so neither
can serve as the reviewed-evaluation identity.

The earlier logical domain model requires a generated report, authorization
rules, participant tracking, decision submission identities, nonfinal decision
history, workflow state, and audit events. Those assumptions exceed the
implemented prototype and are superseded for this boundary by ADR 0002. Direct
human review of the verified deterministic assessment is sufficient; a
generated report is a later presentation capability.

## Authoritative Product Decisions

1. The decision vocabulary is `APPROVE`, `APPROVE_WITH_CONDITIONS`,
   `NEEDS_MORE_INFORMATION`, and `REJECT`.
2. At most one immutable `HumanDecision` is allowed per assessment.
3. `APPROVE_WITH_CONDITIONS` is a final adoption disposition, but the platform
   does not track or claim condition fulfillment.
4. No current policy outcome is nonwaivable. Every finding whose outcome is
   not `PASS` must be explicitly acknowledged for either approval disposition.
5. The decision-maker actor identifier must exactly equal the request's
   `responsible_reviewer_actor_id`. This is asserted-identifier consistency,
   not authentication or authorization.
6. The exact verified deterministic assessment is sufficient review input.
7. Decisions are immutable and have no edit, correction, supersession, or
   history behavior.
8. Conditions and information requests are minimal ordered human-readable
   statements.
9. Materially new information or reconsideration requires a new assessment in
   the current one-shot model.

## Proposed Solution

### Assessment evaluation identity payload

Add one immutable assessment evaluation for the complete deterministic
assessment result. An assessment has at most one. It is created only after the
valid request and complete four-kind authoritative evidence set have been
reopen-verified and deterministic evaluation has succeeded.

Its canonical identity payload contains no copied request context or raw
evidence. The payload is versioned as
`assessment-evaluation-snapshot.v1` and has this conceptual shape:

```json
{
  "assessment_id": "<assessment ID>",
  "evaluated_at": "<exact aware ISO 8601 representation>",
  "evaluation_schema_version": "assessment-evaluation-snapshot.v1",
  "evidence_references": [
    {
      "evidence_kind": "repository_archived",
      "evidence_id": "<evidence ID>"
    }
  ],
  "metric_results": [
    {
      "metric_result_id": "<metric result ID>",
      "assessment_id": "<assessment ID>",
      "calculation_attempt_id": "<calculation attempt ID>",
      "metric_name": "<metric name>",
      "metric_definition_version": "<metric definition version>",
      "input_evidence_ids": ["<evidence ID>"],
      "input_digest": "<input digest>",
      "calculated_at": "<exact aware ISO 8601 representation>",
      "result_status": "<stored enum value>",
      "input_sufficiency": "<stored enum value>",
      "metric_schema_version": "<metric schema version>",
      "value": "<typed value or null>",
      "unit": "<unit or null>",
      "reason_code": "<reason code or null>"
    }
  ],
  "policy_findings": [
    {
      "policy_finding_id": "<policy finding ID>",
      "assessment_id": "<assessment ID>",
      "policy_id": "<policy ID>",
      "policy_version": "<policy version>",
      "policy_engine_version": "<policy engine version>",
      "policy_evaluation_id": "<policy evaluation ID>",
      "requirement_id": "<requirement ID>",
      "requirement_version": "<requirement version>",
      "outcome": "<stored enum value>",
      "input_evidence_ids": ["<evidence ID>"],
      "input_metric_result_ids": ["<metric result ID>"],
      "deterministic_reason": "<deterministic reason>",
      "evaluated_at": "<exact aware ISO 8601 representation>",
      "finding_schema_version": "<finding schema version>",
      "condition_template": "<condition template or null>"
    }
  ]
}
```

The example arrays abbreviate repeated objects only for readability. The real
payload contains all four evidence references, all four metric records, and
all four policy findings. Every listed field is present, including nullable
fields. Enum values use their stored strings and timestamps use the exact aware
ISO 8601 string returned by `datetime.isoformat()`. Metric values retain their
JSON boolean, integer, string, or null type. This object is the complete and
exact logical input to assessment-evaluation identity derivation. It expressly
excludes `assessment_evaluation_id` and `integrity_digest`; neither generated
value can occur in its own hash input.

Canonical UTF-8 bytes are exactly
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
encoded as UTF-8. Arrays preserve order. Evidence references follow
`REQUIRED_EVIDENCE_KINDS`; metric and finding arrays preserve the evaluator's
returned order. The request definition and complete evidence remain
authoritative in their existing rows. Metric and finding fields carry their
exact definition, policy, requirement, engine, and schema versions.

### Assessment evaluation persisted snapshot

`snapshot_json` stores exactly the canonical assessment evaluation identity
payload above, not an envelope and not a CLI output document. The durable row
is the envelope around those payload bytes:

```text
AssessmentEvaluationSnapshotEnvelope(
    assessment_evaluation_id,
    assessment_id,
    snapshot_json,
    integrity_digest,
)
```

`assessment_id` is the only value projected both into a relational column and
inside the payload: the column is required for the foreign key and one-row-per-
assessment constraint, and it must exactly equal the payload value. Evaluation
time and evaluation schema version exist only inside `snapshot_json`; separate
columns would be redundant and are not part of the proposed schema.

The persistence boundary stores the exact canonical payload text and its
SHA256 digest. Reopen verification reconstructs the request and authoritative
evidence, reads the exact `evaluated_at` from the verified payload,
deterministically reevaluates, reconstructs the typed metric and finding
contracts, recreates the canonical payload bytes, and requires equality with
the stored bytes, digest, identifier, and relational `assessment_id` before the
snapshot is authoritative.

### Human decision

Add one immutable logical `HumanDecision` linked to one assessment and its one
authoritative evaluation snapshot. Its fields are limited to:

```python
@dataclass(frozen=True)
class HumanDecision:
    human_decision_id: str
    assessment_id: str
    assessment_evaluation_id: str
    decision_maker_actor_id: str
    disposition: HumanDecisionDisposition
    rationale: str
    conditions: tuple[str, ...]
    information_requests: tuple[str, ...]
    acknowledged_policy_finding_ids: tuple[str, ...]
    recorded_at: datetime
    decision_schema_version: str
```

`decision_schema_version` is `human-decision.v1`. Actor identifiers remain
caller-asserted labels under this version. No field claims identity proof,
role, authorization, participation, or sign-off.

Disposition-specific rules are:

* `APPROVE` requires empty conditions and information requests.
* `APPROVE_WITH_CONDITIONS` requires at least one condition and empty
  information requests.
* `NEEDS_MORE_INFORMATION` requires at least one information request and empty
  conditions. It consumes the assessment's only decision slot; later work
  requires a new assessment.
* `REJECT` requires empty conditions and information requests.

Every rationale, condition, and information request is a nonempty unpadded
string. Conditions and requests preserve submission order and contain no
duplicates. They have no owner, due date, status, verification, or fulfillment
semantics.

Acknowledged finding identifiers are stored as an ordered tuple in the
reviewed policy-finding order. They must be unique members of the reviewed
evaluation. For `APPROVE` and `APPROVE_WITH_CONDITIONS`, the tuple must equal
the complete ordered set of reviewed findings whose outcome is not `PASS`.
For `NEEDS_MORE_INFORMATION` and `REJECT`, the tuple must be empty. An
acknowledgment does not alter or waive a finding; it records that the human
considered it as part of an approval despite the nonpassing outcome.

### Timestamp ownership

`evaluated_at` belongs to the assessment evaluation snapshot and remains the
exact timestamp captured by the workflow after authoritative evidence exists.
`recorded_at` belongs to the decision and is captured by the decision boundary
through a private aware UTC clock after input validation and before the atomic
write. It must not precede the reviewed evaluation time. There is no
`updated_at`, user-supplied decision time, or separate claimed decision time.

## Deterministic Identifiers

### Assessment evaluation identity

Create a new assessment-level identifier. Do not reuse a metric result ID,
calculation attempt ID, policy finding ID, or `policy_evaluation_id`.

The identifier is:

```text
assessment-evaluation-<full lowercase SHA256 hex digest>
```

The hash input is:

```text
UTF-8("assessment-evaluation-id.v1") + NUL
    + canonical_evaluation_identity_payload_bytes
```

Here `canonical_evaluation_identity_payload_bytes` means only the canonical
assessment evaluation identity payload stored in `snapshot_json`; it contains
neither `assessment_evaluation_id` nor `integrity_digest`.

The separate `integrity_digest` is the full lowercase SHA256 digest of those
same canonical payload bytes alone:

```text
SHA256(canonical_evaluation_identity_payload_bytes).hexdigest()
```

The identifier and digest intentionally cover the same logical evaluation
content. The identifier adds a versioned namespace so the hash can serve as a
typed domain identity; the unprefixed digest directly verifies the bytes held
in `snapshot_json`. The digest never includes itself, and the identifier does
not include either generated value.

### Human decision identity

The identifier is:

```text
human-decision-<full lowercase SHA256 hex digest>
```

The canonical human decision identity payload is exactly:

```json
{
  "assessment_id": "<assessment ID>",
  "assessment_evaluation_id": "<reviewed evaluation ID>",
  "decision_maker_actor_id": "<asserted actor ID>",
  "disposition": "<stored disposition value>",
  "rationale": "<human rationale>",
  "conditions": ["<ordered condition>"],
  "information_requests": ["<ordered information request>"],
  "acknowledged_policy_finding_ids": ["<ordered finding ID>"],
  "recorded_at": "<exact aware UTC ISO 8601 representation>",
  "decision_schema_version": "human-decision.v1"
}
```

It uses the same canonical JSON encoding rules as the evaluation payload,
including `recorded_at.isoformat()` and the lowercase stored disposition value.
The hash input is:

```text
UTF-8("human-decision-id.v1") + NUL
    + canonical_decision_identity_payload_bytes
```

The first system-captured `recorded_at` is intentionally part of the identity
payload. The payload expressly excludes `human_decision_id` and any current or
future digest field; no generated identifier or digest may occur in its own
hash input.

There is no decision submission identity. Replay is resolved through the
assessment's unique decision row and comparison of caller-supplied business
content.

## Proposed SQLite Schema Version 5

Schema v5 adds only `assessment_evaluation_snapshots` and `human_decisions` to
the existing five schema-v4 tables.

### `assessment_evaluation_snapshots`

Conceptual columns:

| Column | Constraint and meaning |
| --- | --- |
| `assessment_evaluation_id` | Text primary key; deterministic full SHA256-prefixed identity |
| `assessment_id` | Nonempty text, foreign key to `assessment_requests`, unique |
| `snapshot_json` | Nonempty canonical JSON text containing exactly the assessment evaluation identity payload, including evaluated time and payload schema version but excluding generated ID and digest |
| `integrity_digest` | Exactly 64 lowercase hexadecimal characters; SHA256 of `snapshot_json` UTF-8 bytes |

The table also exposes a composite uniqueness constraint on
`(assessment_evaluation_id, assessment_id)` for the decision's same-assessment
foreign key. One snapshot per assessment prevents later evaluation-time drift
and ambiguity in the one-shot prototype.

### `human_decisions`

Conceptual columns:

| Column | Constraint and meaning |
| --- | --- |
| `human_decision_id` | Text primary key; deterministic full SHA256-prefixed identity |
| `assessment_id` | Nonempty text, unique foreign key to `assessment_requests` |
| `assessment_evaluation_id` | Nonempty text, unique reference to the reviewed snapshot |
| `decision_maker_actor_id` | Nonempty unpadded asserted identifier |
| `disposition` | `approve`, `approve_with_conditions`, `needs_more_information`, or `reject` |
| `rationale` | Nonempty unpadded human-authored text |
| `conditions_json` | Non-null canonical ordered JSON string array; nonempty only for conditional approval and exactly `[]` otherwise |
| `information_requests_json` | Non-null canonical ordered JSON string array; nonempty only for needs-more-information and exactly `[]` otherwise |
| `acknowledged_policy_finding_ids_json` | Canonical ordered JSON string array; exactly all non-`PASS` finding IDs in reviewed order for either approval, and exactly `[]` for rejection or needs-more-information |
| `recorded_at` | Nonempty canonical aware UTC ISO 8601 text |
| `decision_schema_version` | Exact supported value `human-decision.v1` |

A composite foreign key on `(assessment_evaluation_id, assessment_id)` binds
the decision to an evaluation of the same assessment. Database checks enforce
the disposition vocabulary and the null/non-null or empty/nonempty
disposition-specific shape where SQLite can do so. Exact array content,
membership, order, duplicates, actor matching, timestamp ordering, identifier
derivation, and canonical JSON are revalidated by the application before write
and after reopen.

### Migration direction

An exact schema-v4 database migrates to v5 in one explicit transaction. The
migration creates the two new empty tables, compares every existing v4 row by
primary key, verifies exact schema definitions and foreign keys, advances
`PRAGMA user_version` only after all checks pass, and rolls back completely on
failure. Existing assessment rows are not backfilled because schema v4 did not
durably preserve their evaluation time or deterministic output. Such legacy
assessments are not decision-eligible without a newly reviewed evaluation in a
new supported operation; the migration must not invent one.

Existing supported v1-to-v4 migrations may continue into the exact v4-to-v5
migration. Unsupported versions and altered schemas fail closed.

## Persistence and Replay Semantics

### Evaluation snapshot

* If no snapshot exists, persist the complete canonical payload and its
  envelope in one transaction, close, reopen, reconstruct, deterministically
  reevaluate, and
  verify every field, relationship, byte, digest, version, timestamp, and ID.
* Exact replay for an assessment returns the existing verified snapshot.
  It does not capture a later evaluation timestamp or create another snapshot.
* A different snapshot, evaluation time, or identifier for an assessment that
  already has a snapshot is a nonmutating conflict.
* Missing, corrupt, cross-assessment, incomplete, ambiguous, or unsupported
  content fails closed and returns no authoritative evaluation.

### Human decision

* The persistence operation first loads the one verified request and one
  verified evaluation snapshot in a consistent transaction view.
* It requires `decision_maker_actor_id` to equal the persisted request's
  `responsible_reviewer_actor_id` exactly.
* If no decision exists, it validates the complete input, captures
  `recorded_at`, derives the decision ID, writes the row atomically, closes,
  reopens, reconstructs, and verifies it before returning authority.
* Replay comparison uses exactly these normalized caller-supplied business
  fields: `assessment_id`, `assessment_evaluation_id`,
  `decision_maker_actor_id`, `disposition`, `rationale`, ordered `conditions`,
  ordered `information_requests`, and ordered
  `acknowledged_policy_finding_ids`. The existing row must independently pass
  schema-version and integrity verification, but `decision_schema_version` is
  not caller supplied and is not a replay comparison field.
* If all eight business fields match, return the existing verified decision
  with its original `human_decision_id` and `recorded_at`. Those system-
  generated fields, and any future digest field, are never compared as caller
  replay content and therefore cannot turn an otherwise exact replay into a
  conflict.
* Any changed business content for an assessment that already has a decision
  is a nonmutating conflict. There is no edit, correction, supersession, second
  decision, or replacement path.
* A failure before complete durable verification returns no authoritative
  decision. Commit uncertainty is resolved by reopening and comparing the
  assessment's unique row before any retry can create content.

## Required Invariants

1. One assessment has at most one authoritative evaluation snapshot and at
   most one authoritative human decision.
2. A decision cannot exist without the exact referenced evaluation snapshot,
   and both records belong to the same persisted assessment.
3. A snapshot cannot exist until the valid request and complete canonical
   four-kind evidence set are authoritative.
4. Snapshot evidence references exactly match the four verified evidence IDs
   in canonical kind order; request context and evidence content are referenced
   rather than copied.
5. Stored metrics and findings exactly reconstruct from the verified evidence,
   persisted context, exact `evaluated_at`, and supported versions.
6. Metric and finding references form a complete same-assessment closure over
   the snapshot's evidence, metric, and finding sets.
7. The snapshot's bytes, digest, deterministic ID, timestamp, and versions
   verify after close and reopen.
8. The decision maker ID exactly equals the request's responsible reviewer ID;
   this proves only identifier consistency.
9. The disposition-specific rationale, conditions, information requests, and
   acknowledgments satisfy the frozen decision contract.
10. Either approval disposition acknowledges exactly every reviewed nonpassing
    policy finding in canonical finding order. `REJECT` and
    `NEEDS_MORE_INFORMATION` acknowledge none. No policy outcome automatically
    selects or prohibits a human disposition.
11. `recorded_at` is aware UTC and is not earlier than `evaluated_at`.
12. Human decisions never mutate request, evidence, metrics, findings, or the
    reviewed snapshot.
13. Exact replay is idempotent; conflicting replay changes no durable content.
14. `NEEDS_MORE_INFORMATION` consumes the only decision slot and does not
    create workflow or continuation state. New material information requires a
    new assessment.

## Future `decide` CLI Contract

The smallest future customer interaction is one noninteractive command:

```text
PYTHONPATH=src python3 -m engineering_due_diligence.cli decide \
  --database <path> \
  --assessment-id <assessment ID> \
  --assessment-evaluation-id <evaluation ID from assess output> \
  --reviewer-actor-id <asserted responsible reviewer ID> \
  --decision <approve|approve_with_conditions|needs_more_information|reject> \
  --rationale <text> \
  [--condition <ordered statement>]... \
  [--information-request <ordered statement>]... \
  [--acknowledge-policy-finding <finding ID>]...
```

The evaluation ID is required even though an assessment has only one snapshot;
it makes the reviewed input explicit and prevents recording against a different
assessment output by accident. Repeated condition, information-request, and
acknowledgment flags preserve command order.

The CLI does not accept decision IDs, timestamps, versions, roles,
authorization claims, condition owners, condition status, or workflow state.
It performs no network calls and no deterministic reevaluation outside the
existing persistence verification boundary.

Successful recording or exact replay returns one versioned
`human-decision-cli-output.v1` JSON document containing the assessment ID,
assessment-evaluation ID, complete decision, and an explicit identity-assurance
statement that actor identifiers are caller asserted. The proposed exit codes
are 0 for recorded or exact replay, 1 for unexpected internal failure, 2 for
usage error, 3 for decision validation failure, 5 for persistence or durable
verification failure, and 6 for an existing-decision conflict. Exit code 4
remains reserved for the existing `assess` collection-failure meaning. Output
must not expose database paths, SQL, source bodies, or exception text.

## Files Affected by Day 15 Design

* `plans/day_15_human_decision_boundary.md` locks this direction.
* `journal/day_15.md` records the design work, decisions, review, and exclusions.
* `docs/adr/0002_direct_deterministic_review_for_prototype_decisions.md` records
  the architectural change from a generated-report prerequisite to direct
  deterministic review and the one-decision prototype boundary.
* `memory/ARCHITECTURE.md` records the durable selected boundary while clearly
  distinguishing it from implemented schema-v4 behavior.
* `memory/DECISIONS.md` records the new durable architectural decision.

No README, source, test, migration, or CLI file changes on Day 15.

## Database Impact

Day 15 changes no database. It specifies the future exact schema-v5 direction
above. SQLite remains schema version 4 until a separately reviewed Day 16
implementation changes production code and tests.

## Testing Strategy for Future Implementation

Day 16 tests should cover:

1. exact v4-to-v5 migration, row preservation, rollback, schema verification,
   and unchanged prior persistence behavior;
2. canonical evaluation-payload serialization, full assessment-level identifier and
   digest derivation, ordering, timestamp representation, and version closure;
3. evaluation persistence only after four verified evidence records;
4. close-and-reopen deterministic reconstruction from durable evidence;
5. exact snapshot replay and conflicting later evaluation rejection;
6. frozen decision contracts and all four disposition-specific shapes;
7. exact reviewer-ID equality without authentication claims;
8. exact complete approval acknowledgment for every nonpassing finding and an
   empty acknowledgment tuple for rejection and needs-more-information;
9. one decision per assessment, exact replay, conflicting replay, transaction
   rollback, commit reconciliation, and reopen verification;
10. missing, corrupt, cross-assessment, temporally invalid, and unsupported
    version failures; and
11. unchanged evidence authority, no network activity in persistence, and safe
    error categories.

Future CLI tests should be a separate focused slice unless implementation size
remains demonstrably small after the durable boundary is complete.

## Risks

* Canonical JSON becomes a durable contract and must not reuse the CLI output
  envelope, which contains presentation fields and human-decision status.
* JSON-contained evidence and finding references are not individually protected
  by SQLite foreign keys; strict one-transaction reconstruction and reopen
  verification are therefore mandatory.
* A future evaluator that removes support for stored definition versions could
  make deterministic reconstruction unavailable. Version support or an
  explicit migration decision is required before changing those definitions.
* Existing schema-v4 assessments cannot be backfilled honestly because their
  transient evaluation time and output were not stored.
* A caller can impersonate the responsible reviewer label. The interface must
  consistently describe identity as asserted and make no authorization claim.
* Recording `NEEDS_MORE_INFORMATION` permanently consumes the assessment's
  decision slot; the CLI output must make the new-assessment consequence clear.

## Alternatives Rejected

* Reusing `policy_evaluation_id`: it identifies the policy evaluation, not the
  complete assessment-level result.
* Independent metric and finding persistence tables: they add lifecycle and
  selection concepts unnecessary for one fixed reviewed snapshot.
* A decision row that stores only an evaluation digest: it cannot independently
  show the exact metric and finding content reviewed.
* Duplicating request context or raw evidence in the snapshot: it creates
  competing authoritative copies.
* Multiple decisions, prior links, correction, or supersession: they contradict
  the selected one-shot product behavior.
* Decision submission identifiers: one unique assessment decision plus material
  content comparison is sufficient for replay.
* Generated-report prerequisites, authentication, authorization, workflow
  state, and general audit events: they are not required for the prototype
  human-owned decision boundary.
* Condition owners, status, verification, or fulfillment: they create a
  condition-management domain outside the task.

## Rollback Plan

Before implementation, revert the Day 15 plan, journal, ADR, and corresponding
durable-memory additions. No runtime or database rollback is needed because
Day 15 changes documentation only.

After a future implementation, rollback would require reverting the decision
and evaluation code plus migrating or retiring schema-v5 databases through a
separately reviewed data-preservation plan. Destructive downgrade is not
assumed.

## Acceptance Criteria

* The four decision values and their required content are exact.
* At most one immutable decision is allowed per assessment, including
  `NEEDS_MORE_INFORMATION`.
* Direct verified deterministic review replaces the report prerequisite only
  for the prototype and does not add AI behavior.
* A new assessment-level evaluation identity covers the complete reviewed
  result and does not reuse a narrower identifier.
* Schema v5 contains only the evaluation snapshot and human decision concepts.
* Existing request and evidence remain referenced rather than duplicated.
* Every approval acknowledges every nonpassing finding without making any
  finding nonwaivable.
* Actor matching is explicit identifier consistency and never authentication or
  authorization.
* Persistence, migration, integrity, temporal, fail-closed, and replay behavior
  follow existing patterns without a new abstraction layer.
* Day 15 modifies documentation only and does not update README with planned
  functionality.

## Implementation Checklist

* Record the architecture change in ADR 0002 and durable memory.
* Complete the Day 15 journal after reviewing the design documents.
* Confirm no production, test, schema, migration, CLI, or README changes exist.
* Review the contracts, schema, identifiers, replay behavior, risks, and
  exclusions against the authoritative product decisions.
* Stop before Day 16 implementation.
