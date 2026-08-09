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

The current implementation is dependency-free Python library code using the
standard library, including `urllib` for bounded public GitHub requests and
`sqlite3` for caller-supplied on-disk prototype persistence. Tests use
`unittest` and real temporary SQLite files; collector tests patch the private
transport seam and make no live network calls.

Implemented boundaries include transient request validation, public GitHub
repository-archived, license-status, latest-commit timestamp, and effective
security-policy-presence collection, deterministic evidence-to-policy
evaluation, in-memory assessment result assembly, and SQLite persistence for
validated requests and terminal outcomes from all four collectors. A strict
read-only SQLite loader reconstructs the complete four-kind authoritative
evidence set and passes it to the unchanged deterministic evaluator; metrics
and policy findings remain transient. GitHub license presence means detected
metadata only, not legal or compatibility analysis. Security-policy presence
includes repository-local `SECURITY.md` files and inherited defaults from the
owner's public `.github` repository.

SQLite schema version 4 stores all four evidence kinds in separate typed
columns and adds ordered GitHub source observations plus multiple source
snapshots for bounded multi-request collection. Exact schema version 3
databases migrate transactionally while preserving archived, license, and
latest-commit content; the existing exact version 1 and 2 migrations remain
supported. Complete HTTP 200 response bytes remain separate from compact
normalized evidence, and only close-and-reopen verified evidence is
authoritative. For latest commits, the exact source timestamp spelling and the
normalized timestamp representation are preserved separately and must denote
the same UTC instant. Durable evaluation loading accepts only an existing exact
schema-v4 database, reads one consistent transaction snapshot, requires exactly
one record for each evaluator-required kind, and fails closed on missing,
ambiguous, corrupt, or mismatched evidence.

FastAPI, Pydantic, PostgreSQL, model integration, OpenTelemetry, Docker Compose,
and Grafana-compatible telemetry remain planned or deferred rather than
implemented. Technology decisions change only through explicit architectural
review; ADR 0001 selects SQLite for the prototype without making a production
database decision.

## Repository Structure

* `src/engineering_due_diligence/` contains the Python library boundaries for
  models, deterministic evaluation, request validation, GitHub collection,
  assessment assembly, and SQLite persistence.
* `tests/` contains the automated `unittest` suite, including focused real-file
  SQLite persistence tests.
* `docs/` contains project, engagement, ADR, and checkpoint documentation.
* `plans/` contains temporary implementation plans.
* `journal/` contains daily engagement records.
* `scripts/` contains project automation scripts.
* `examples/` contains example inputs and usage artifacts.
* `data/` contains project data artifacts.
