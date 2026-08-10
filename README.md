# Engineering Due Diligence Platform

> **Current status:** Days 1 through 12 established the engagement, request and
> domain contracts, all four public GitHub evidence collectors, schema-v4
> SQLite persistence, and strict durable evaluation loading. Day 13 adds one
> narrow execution boundary that validates and persists a request, collects and
> persists the four evidence kinds, and returns the deterministic assessment
> result. Metrics and findings remain transient; customer-facing interaction,
> retry and reassessment, audit, reports, model use, and human decisions remain
> unimplemented.

## Customer Problem

The simulated customer, Northstar Software, is a medium sized software
organization with approximately 60 engineers across six product teams. Teams
use inconsistent practices to evaluate open source repositories, and critical
dependencies require manual security review. Evidence, rationale, conditions,
and approvals can be difficult to reproduce across teams and over time.

This is a simulated four week Forward Deployed Engineering engagement. It does
not claim real customer interviews, production use, or measured business
impact.

## Project Mission

Build a reliable and auditable decision support workflow for evaluating whether
a public open source repository is appropriate for a specified engineering use
case.

The core abstraction is an assessment decision, not a repository. Intended use,
environment, criticality, expected lifetime, and organizational risk tolerance
can lead to different decisions about the same repository.

## Target Workflow

The scoped workflow will:

1. accept a public GitHub repository and its engineering use-case context;
2. validate the request;
3. collect evidence from authoritative sources;
4. store raw evidence with status and provenance;
5. calculate deterministic, versioned metrics;
6. evaluate context-specific, versioned policy;
7. generate a structured, evidence-grounded decision brief;
8. support engineering, security, and management review;
9. require a human to record the final decision; and
10. preserve the request, evidence, versions, report, decision, and audit
    timestamps.

AI is limited to grounded synthesis, tradeoff explanation, uncertainty
communication, and reviewer questions. It does not collect authoritative
evidence, calculate deterministic metrics, enforce policy, control workflow
state, or approve adoption.

## Scope

The four week scope is locked around one end-to-end assessment of a public
GitHub repository for one specified engineering use case. Private repositories,
additional source providers, continuous monitoring, automated installation or
remediation, technology comparisons, vendor reviews, AI model reviews,
automatic approval, and unjustified distributed infrastructure are out of
scope.

Deferred ideas are recorded in [docs/backlog.md](docs/backlog.md). A backlog
entry is not an active commitment.

## Current Project Status

Completed on Day 1:

* project mission, charter, simulated customer, stakeholders, and scope;
* current-workflow model and failure points;
* proposed auditable workflow and responsibility boundaries;
* separate system and prototype customer validation criteria;
* deferred backlog and documentation map; and
* Day 1 execution plan and journal.

Completed on Day 2:

* logical definitions for the seven assessment domain entities;
* entity ownership, identifiers, relationships, lifecycle boundaries,
  immutability, versioning, and audit obligations; and
* documented handling for incomplete evidence, repeat processing, human review,
  reassessment, and workflow interruption;
* final behavioral review of the corrected domain model and failure model; and
* failure taxonomy, stage-specific failure behavior, fail-closed rules,
  idempotency, recovery, audit, and security requirements.

Both Day 2 design documents are complete, passed behavioral review, and are
committed.

Committed on Day 3:

* immutable typed assessment context, evidence, metric, and policy records, with
  local canonical fixtures for the scoped public GitHub facts: archived status,
  license status, latest commit timestamp, and security policy presence;
* fail-closed evidence validation for required and duplicate records, canonical
  kinds, snapshot integrity and normalized values, valid available or
  unavailable states, timezone awareness, and future timestamps;
* versioned metric calculation plus canonical recalculation before policy
  findings are accepted; invalid evidence returns no metric collection, and
  invalid or altered metrics return no finding collection;
* exact UTC elapsed-duration maintenance policy: 180-day and 730-day boundaries
  are inclusive, while one second beyond either boundary fails;
  `days_since_latest_commit` remains a floored display metric;
* intrinsic validation before freshness handling; temporally valid stale or
  unknown evidence remains unavailable and produces `not_evaluable`;
* context-sensitive absent-license policy: `condition_required` for a prototype
  and `fail` for strict production; and
* deterministic, traceable evidence, metric, and finding identifiers, verified
  by 52 passing tests.

Committed on Day 4:

* a frozen transient `DeterministicAssessmentResult` that keeps one assessment
  context, its canonical evidence tuple, exact Day 3 metrics and findings, and
  the caller-supplied aware evaluation timestamp together in memory;
* one `evaluate_assessment` boundary that snapshots caller evidence once,
  delegates exactly once to `evaluate_slice`, canonically orders validated
  evidence, and constructs no partial result on failure;
* preservation of timestamp representations and complete evidence-to-metric-to-
  finding reference closure without duplicating Day 3 validation; and
* nine focused Day 4 tests, with all 61 repository tests passing.

Completed on Day 5:

* frozen transient `AssessmentRequestInput`,
  `AssessmentRequestValidationError`, and
  `AssessmentRequestValidationResult` contracts;
* one deterministic `validate_assessment_request` boundary that accepts
  submitted context, validates every field in a stable order, and produces the
  existing `AssessmentContext` only after the complete request is valid;
* structured field-level validation errors with one first-precedence error per
  field and no partial context or normalized identity on invalid input;
* strict HTTPS `github.com/<owner>/<repository>` locator validation and
  canonical `github.com/<owner>/<repository>` identity construction while
  preserving owner and repository casing and the exact submitted request; and
* 14 focused Day 5 tests, with all 75 repository tests passing.

Completed on Day 6:

* frozen transient public GitHub collection input, error, outcome, and result
  contracts plus one dependency-free collector boundary;
* one unauthenticated request to
  `GET https://api.github.com/repos/<owner>/<repository>` that currently
  captures the authoritative GitHub repository ID and archived status only;
* strict noncoercing validation of `id`, `full_name`, and `archived`, with
  case-insensitive repository binding while preserving the requested identity;
* preservation of the exact successful raw response text, matching SHA256
  digest, source identity, collector version, collection-attempt metadata, and
  a sanitized ETag when supplied;
* structured sanitized outcomes for public unavailability, rate limits,
  authorization and request rejection, server failures, timeouts,
  connectivity failures, malformed responses, and unexpected statuses, with
  no partial evidence on unsuccessful outcomes; and
* 13 focused Day 6 tests, with all 88 repository tests passing.

The Day 6 result remains transient until it passes through the Day 8
persistence boundary. The collector itself does not create authoritative
evidence.

Completed on Day 7:

* selected a caller-supplied on-disk SQLite database through Python `sqlite3`
  as the concrete prototype durable store;
* defined request-before-collection ordering, atomic collection-attempt,
  source-snapshot, and normalized-evidence writes, and close-and-reopen
  verification before evidence becomes authoritative;
* kept the complete GitHub response separate from the compact canonical
  snapshot required by the existing `EvidenceRecord`; and
* recorded the decision in
  [ADR 0001](docs/adr/0001_use_sqlite_for_prototype_persistence.md).

Completed on Day 8:

* one concrete standard-library SQLite boundary persists complete valid Day 5
  requests before accepting linked Day 6 collection outcomes;
* schema version 1 stores assessment requests, collection attempts, full GitHub
  source snapshots, and normalized evidence in four linked tables;
* available results atomically store the attempt, exact GitHub response bytes,
  and compact repository-archived `EvidenceRecord`; 404 results atomically
  store the attempt and unavailable evidence; retryable and nonretryable
  failures store only the attempt and produce no evidence;
* the complete GitHub response remains separate from the compact canonical
  evidence snapshot, with both digests independently verified;
* available and unavailable evidence becomes authoritative only after the
  database is closed, reopened, and all fields, relationships, payload
  bindings, digests, versions, and existing constructors are verified;
* exact replay is idempotent, conflicting replay is rejected without mutation,
  and incomplete linked writes roll back; and
* 15 focused Day 8 tests pass, with all 103 repository tests passing.

Completed on Day 9:

* one strict transient collector reuses the existing private transport seam
  for exactly one unauthenticated request to
  `GET https://api.github.com/repos/<owner>/<repository>`;
* a valid GitHub license object becomes `LicenseStatus.PRESENT`, while an
  explicit `license: null` becomes `LicenseStatus.ABSENT`; missing or malformed
  license data fails closed and never becomes absence;
* license presence means only that GitHub returned detected license metadata;
  it is not legal analysis, compatibility analysis, or a policy conclusion;
* SQLite schema version 2 supports durable repository-archived and
  license-status evidence, with exact schema version 1 databases migrated
  transactionally without changing existing archived rows or timestamps;
* available license outcomes atomically persist the attempt, complete GitHub
  response, and compact `EvidenceRecord`; 404 outcomes persist the attempt and
  unavailable evidence, while other failures persist only the attempt;
* complete responses remain separate from compact canonical evidence, and
  only evidence reconstructed and verified after database close and reopen is
  authoritative; and
* 20 focused collector tests and 23 focused persistence tests pass, with all
  146 repository tests passing.

Repository-archived and license-status evidence are now durable. Persistence
is not yet connected to deterministic assessment evaluation.

Completed on Day 10:

* one strict transient collector performs exactly one unauthenticated request
  to
  `GET https://api.github.com/repos/<owner>/<repository>/commits?per_page=1`;
* a valid one-element response uses only `commit.committer.date` to produce
  `EvidenceKind.LATEST_COMMIT_TIMESTAMP`, while a valid empty array produces
  unavailable evidence with the stable `repository_has_no_commits` category;
  HTTP 409 remains a failed collection outcome;
* the commit SHA, exact source timestamp spelling, parsed aware timestamp,
  complete response text, matching SHA256 digest, and unrelated response
  fields are preserved without coercion or reserialization;
* the source timestamp and normalized evidence timestamp may use different
  timezone offsets, but collection and reopened persistence require them to
  identify the same UTC instant;
* SQLite schema version 3 adds a typed latest-commit timestamp value, with exact
  version 2 schemas migrated transactionally while preserving archived and
  license requests, attempts, snapshots, evidence, digests, provenance,
  versions, and timestamp representations;
* available outcomes atomically persist the attempt, full commits response,
  and compact timestamp `EvidenceRecord`; empty-array and 404 outcomes persist
  the attempt and unavailable evidence, while other failures persist only the
  attempt;
* only evidence reconstructed after database close and reopen, source and
  compact digest verification, commit binding, timestamp-instant comparison,
  provenance verification, and existing constructor validation is
  authoritative; and
* exact replay is idempotent, conflicting replay changes no durable history,
  and all 177 repository tests pass.

Repository-archived, license-status, and latest-commit timestamp evidence are
now durable. Persistence remains intentionally disconnected from deterministic
assessment evaluation until the complete four-kind evidence set exists.

Completed on Day 11:

* one bounded collector first verifies the assessed public repository, then
  probes local `.github/SECURITY.md`, `SECURITY.md`, and
  `docs/SECURITY.md` paths before the same inherited paths in the owner's
  public `.github` repository;
* the first strictly valid policy file produces `True`, complete candidate 404
  coverage after repository verification produces `False`, and assessed
  repository 404 produces unavailable evidence; candidate 404 responses are
  ordered negative observations rather than repository unavailability;
* every HTTP 200 response is preserved as exact bytes with a matching SHA256
  digest, including malformed non-UTF-8 bodies, while HTTP error bodies are
  never read or stored and incomplete searches never produce Boolean evidence;
* SQLite schema version 4 adds a typed security-policy Boolean, ordered GitHub
  source observations, and multiple source snapshots per collection attempt;
  exact version 3 schemas migrate transactionally while preserving archived,
  license, and latest-commit rows exactly;
* available `True` and `False` results atomically persist the attempt, complete
  ordered observations, successful snapshots, and compact evidence; repository
  404 persists unavailable evidence, while other failures persist observations
  without evidence;
* close-and-reopen verification reconstructs the entire probe sequence,
  recomputes every source and compact digest, revalidates source binding and
  normalization, and rejects conflicting replay without mutation; and
* 13 focused collector tests and 15 focused persistence tests pass, with all
  205 repository tests passing.

For this project, security-policy presence means an effective `SECURITY.md`
found either in the assessed repository or through the owner's public GitHub
community-health `.github` repository. It establishes presence only; it does
not assess policy quality, response capability, or security posture.

Repository-archived, license-status, latest-commit timestamp, and
security-policy-presence evidence are durable. Day 12 now loads that exact
authoritative four-kind set from SQLite and connects it to deterministic
evaluation without recollection or partial results.

Completed on Day 12:

* frozen `VerifiedAssessmentEvidenceSet` groups one reconstructed valid request
  with exactly four verified `EvidenceRecord` values in canonical evaluator
  order;
* `load_verified_assessment_evidence` opens only an existing exact schema-v4
  SQLite database through read-only URI mode, enables query-only and foreign-
  key checks, and performs all determining reads in one transaction snapshot;
* repository archived, license status, latest commit timestamp, and security
  policy presence must each have exactly one durable evidence row; unavailable
  evidence counts as complete, missing kinds fail as
  `evidence_set_incomplete`, and multiple rows for a kind fail as
  `evidence_set_ambiguous`;
* each record is reconstructed from its durable request, collection attempt,
  complete source snapshots, ordered observations where applicable, and
  compact evidence before digest, provenance, repository, relationship,
  timestamp, version, and existing constructor checks pass;
* `evaluate_persisted_assessment` loads the verified set once and calls the
  unchanged deterministic evaluator once, returning no partial result on
  failure and preserving the exact aware evaluation timestamp; and
* 14 focused Day 12 tests pass, with all 219 repository tests passing.

The read boundary never creates or migrates a database, and evaluation does
not persist metrics or policy findings.

Completed on Day 13:

* frozen `AssessmentExecutionInput`, `AssessmentExecutionFailure`, and
  `AssessmentExecutionResult` contracts plus `AssessmentExecutionStatus`
  represent one terminal one-shot execution;
* `execute_assessment` validates the submitted request, persists and verifies
  a valid request before network activity, then collects and persists repository
  archived, license status, latest commit timestamp, and security policy
  presence in canonical evaluator order;
* each evidence kind uses attempt number 1 and a stable distinct SHA256 attempt
  identifier derived from the assessment ID, evidence kind, attempt number,
  and versioned execution namespace;
* every terminal collection outcome passes its existing transaction and
  close-and-reopen verification boundary before the next collector starts;
  available and unavailable evidence continue, while the first failed outcome
  is persisted and stops execution without evaluation;
* only a complete four-kind authoritative evidence set reaches
  `evaluate_persisted_assessment`, which runs once and returns transient metrics
  and policy findings;
* exact replay creates no duplicate attempts, snapshots, observations, or
  evidence, while changed remote evidence under the same attempt identity
  conflicts without mutation or evaluation; and
* 11 focused Day 13 tests pass, with all 230 repository tests passing.

Day 13 does not change SQLite schema version 4. It is intentionally one shot:
retry, resume, reassessment, and current-evidence selection remain outside the
boundary.

Not yet implemented:

* a customer-facing assessment interaction boundary;
* retry, resume, reassessment, and current-evidence selection;
* audit history, generated reports, and model integration;
* human decisions and review interfaces; and
* production storage and deployment, observability, and prototype evaluation.

## Four Week Milestones

| Week | Milestone | Status |
| --- | --- | --- |
| 1 | Engagement definition, domain and failure models, evaluation methodology, architecture decisions, and implementation plan | Day 1 foundation and Day 2 domain and failure models complete and committed; remaining Week 1 design work planned and not implemented |
| 2 | Tested deterministic foundation for assessment context, evidence, metrics, policy, persistence, and workflow | Request validation, deterministic context-to-policy evaluation, all four durable evidence kinds, verified loading, and one-shot execution are complete |
| 3 | Minimum public GitHub collection, grounded report generation, human review, audit history, and essential observability | All four minimum GitHub collectors and one complete one-shot assessment execution are verified; customer interaction, reporting, review, audit, and observability remain planned |
| 4 | Evaluation, reliability improvements, limitations, and engagement handoff | Planned |

Milestones describe intended sequencing and are not claims of completed
capability.

## Documentation

### Engagement Documents

* [Project charter](docs/project_charter.md) — mission, customer, stakeholders,
  scope, deliverables, and governance.
* [Customer discovery](docs/customer_discovery.md) — simulated hypotheses,
  stakeholder questions, assumptions, and planned validation.
* [Current workflow](docs/current_workflow.md) — informal process and failure
  points to validate.
* [Proposed workflow](docs/proposed_workflow.md) — target workflow and system,
  AI, and human boundaries.
* [Domain model](docs/domain_model.md) — logical entities, relationships,
  lifecycle boundaries, immutability, versioning, and audit requirements.
* [Failure model](docs/failure_model.md) — failure taxonomy, stage behavior,
  idempotency, recovery, fail-closed, audit, and security requirements.
* [Success criteria](docs/success_criteria.md) — system metrics and separate
  prototype customer validation measures.
* [Backlog](docs/backlog.md) — deferred ideas outside active scope.
* [ADR 0001](docs/adr/0001_use_sqlite_for_prototype_persistence.md) — SQLite
  as the concrete prototype persistence store, without making a production
  database decision.

### Engineering Context

* `AGENTS.md` defines contributor behavior, required context, and scope
  controls.
* `memory/` contains durable repository knowledge that agents read before
  tasks.
* `docs/adr/` holds meaningful architectural decisions.
* `docs/checkpoints/` holds engagement checkpoints.
* `plans/` holds temporary task execution plans.
* `journal/` records what actually happened during the engagement.
* `templates/` contains reusable planning and review structures.

## Repository Structure

```text
.
├── AGENTS.md
├── README.md
├── data/
├── docs/
│   ├── adr/
│   └── checkpoints/
├── examples/
├── journal/
├── memory/
├── plans/
├── scripts/
├── src/engineering_due_diligence/
├── templates/
└── tests/
```

The Python package now contains dependency-free transient request validation,
public GitHub archived-status, license-status, latest-commit, and effective
security-policy collection, deterministic evaluation and in-memory result
assembly, concrete SQLite persistence for validated requests and all four
evidence kinds, strict read-only durable evaluation loading, and one-shot
assessment execution. Metrics and policy findings remain transient. It is
library code rather than an API or deployed application.
Run its tests from the repository root with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Working in This Repository

Before planning or editing:

1. read `AGENTS.md`;
2. read every file under `memory/`;
3. read the project charter and backlog;
4. read relevant ADRs and the current task plan; and
5. preserve the locked scope and documentation-layer boundaries.

The current active plan is
[plans/day_13_one_shot_assessment_execution.md](plans/day_13_one_shot_assessment_execution.md),
with its durable storage decision recorded in
[ADR 0001](docs/adr/0001_use_sqlite_for_prototype_persistence.md).
