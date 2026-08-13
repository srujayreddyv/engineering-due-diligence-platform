# Codebase Memory

## Repository Purpose

This repository contains the tested library foundation for the Engineering Due
Diligence Platform prototype.

The planned platform will support a reproducible workflow for evaluating
whether a public open source repository is appropriate for a specific
engineering use case.

The planned system will collect evidence, calculate deterministic metrics,
evaluate context specific policies, generate an evidence grounded decision
brief, support human review, and preserve an audit record.

## Primary Workflow

The planned primary workflow is:

1. An engineering reviewer submits a public GitHub repository.
2. The reviewer describes the intended use, environment, criticality,
   expected lifetime, and organizational risk tolerance.
3. The system validates the request.
4. Evidence collectors retrieve data from authoritative sources.
5. The system stores raw evidence.
6. Deterministic metric calculators derive signals from the evidence.
7. The policy engine evaluates context specific requirements.
8. The AI report generator explains findings and uncertainty.
9. A human reviewer records a final decision.
10. The system preserves the request, evidence, versions, report, and decision.

## Current Scope

The planned first workflow will evaluate public GitHub repositories for one
specified engineering use case.

Private repositories, GitLab, continuous monitoring, automated installation,
technology comparisons, vendor reviews, AI model reviews, and automatic
approval are outside the four week scope.

## Implemented Runtime

The current implementation is dependency-free Python library and command-line
code using the standard library, including `urllib` for bounded public GitHub
requests and `sqlite3` for caller-supplied on-disk prototype persistence. Tests
use `unittest` and real temporary SQLite files; collector tests patch the
private transport seam and make no live network calls.

Implemented boundaries include transient request validation, public GitHub
repository-archived, license-status, latest-commit timestamp, and effective
security-policy-presence collection, deterministic evidence-to-policy
evaluation, in-memory assessment result assembly, and SQLite persistence for
validated requests and terminal outcomes from all four collectors. A strict
read-only SQLite loader reconstructs the complete four-kind authoritative
evidence set and passes it to the unchanged deterministic evaluator. The
complete ordered metrics and policy findings are preserved inside one canonical
`AssessmentEvaluationSnapshot` per assessment rather than as independently
managed rows. One one-shot execution boundary connects request validation,
request persistence, the four collectors and their persistence functions,
durable evidence loading, deterministic evaluation, and durable reviewed-
snapshot verification. GitHub license presence means detected metadata only,
not legal or compatibility analysis. Security-policy presence includes
repository-local `SECURITY.md` files and inherited defaults from the owner's
public `.github` repository.

The minimal customer-facing boundary is a noninteractive
`assess -> review -> decide` command-line flow. `assess` requires one database
path and the complete submitted assessment context, privately generates a
lowercase UUID4 assessment ID plus aware UTC submission and collection
timestamps, and calls the one-shot workflow once. The workflow—not the CLI
input—captures the aware evaluation timestamp only after all four authoritative
evidence records exist. Versioned `assessment-cli-output.v1` JSON returns
canonical evidence, metrics, and policy findings without complete GitHub
response bodies or an aggregate recommendation.

`review` accepts only the database path and assessment ID. One read-only SQLite
transaction reconstructs the valid request, complete authoritative evidence,
exact durable evaluation, and optional verified decision. Versioned
`assessment-review-cli-output.v1` JSON exposes canonical review content and the
ordered nonpassing finding IDs required for approval without performing network
requests, writes, new evaluation, or clock capture. `decide` accepts the exact
evaluation reference and existing human-decision business fields, reloads the
verified evaluation, and delegates validation and recording to persistence.
Versioned `human-decision-cli-output.v1` JSON distinguishes first recording
from exact replay and states that actor identifiers are caller asserted.

SQLite schema version 5 stores all four evidence kinds in separate typed
columns and adds ordered GitHub source observations plus multiple source
snapshots for bounded multi-request collection. It adds one canonical
assessment-evaluation snapshot and at most one immutable human decision per
assessment. Exact schema version 4 databases migrate transactionally by adding
the two empty tables while preserving every existing row; the earlier exact
migration chain remains supported. Complete HTTP 200 response bytes remain
separate from compact normalized evidence, and only close-and-reopen verified
content is authoritative. Durable reads accept only an existing exact schema-
v5 database and fail closed on missing, ambiguous, corrupt, mismatched, or
unsupported content.

The one-shot workflow uses deterministic versioned SHA256 collection-attempt
identifiers derived from assessment ID, evidence kind, and attempt number 1.
It persists and reopen-verifies each terminal result before starting the next
collector. Available and unavailable evidence continue; the first failed
outcome stops without evaluation. A first complete evaluation is persisted as
one canonical snapshot and reopen-verified before completion is returned. Exact
workflow replay returns the original evaluation time and snapshot without
reading a later evaluation clock; changed evidence or evaluation content
conflicts without mutation. The workflow adds no durable workflow state, retry,
resume, reassessment, or current-evidence selection.

The library can record one immutable human decision against the same verified
assessment evaluation. It enforces responsible-reviewer identifier equality,
disposition-specific conditions or information requests, complete ordered
nonpassing-finding acknowledgment for approvals, UTC recording time, exact
identity derivation, reopen verification, and business-content-only replay.
The CLI exposes this existing capability without adding a durable replay-status
field; `recorded` or `exact_replay` is returned from the persistence transaction.

The automated suite contains 269 tests. There is no report generation, AI
synthesis, authentication, authorization, retry, resume, reassessment,
decision editing or correction, condition-fulfillment tracking, HTTP API, web
UI, or new observability infrastructure.

FastAPI, Pydantic, PostgreSQL, model integration, OpenTelemetry, Docker Compose,
and Grafana-compatible telemetry remain planned or deferred rather than
implemented. Technology decisions change only through explicit architectural
review; ADR 0001 selects SQLite for the prototype without making a production
database decision.

## Repository Structure

* `src/engineering_due_diligence/` contains the Python boundaries for models,
  deterministic evaluation, request validation, GitHub collection, assessment
  assembly, SQLite persistence, one-shot execution, and the minimal CLI.
* `tests/` contains the automated `unittest` suite, including focused real-file
  SQLite persistence tests.
* `docs/` contains project, engagement, ADR, and checkpoint documentation.
* `plans/` contains temporary implementation plans.
* `journal/` contains daily engagement records.
* `scripts/` contains project automation scripts.
* `examples/` contains example inputs and usage artifacts.
* `data/` contains project data artifacts.
