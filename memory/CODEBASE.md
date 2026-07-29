# Codebase Memory

## Repository Purpose

This repository contains the Engineering Due Diligence Platform.

The platform supports a reproducible workflow for evaluating whether a public
open source repository is appropriate for a specific engineering use case.

The system collects evidence, calculates deterministic metrics, evaluates
context specific policies, generates an evidence grounded decision brief,
supports human review, and preserves an audit record.

## Primary Workflow

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

The first supported workflow evaluates public GitHub repositories for one
specified engineering use case.

Private repositories, GitLab, continuous monitoring, automated installation,
technology comparisons, vendor reviews, AI model reviews, and automatic
approval are outside the four week scope.

## Main Technologies

The initial implementation uses Python, FastAPI, Pydantic, PostgreSQL, pytest,
the GitHub API, structured model outputs, OpenTelemetry, Docker Compose, and
Grafana compatible telemetry.

Technology choices may change only through an explicit architectural decision.

## Repository Structure

* `src/engineering_due_diligence/` contains the Python application package.
* `tests/` contains automated tests.
* `docs/` contains project, engagement, ADR, and checkpoint documentation.
* `plans/` contains temporary implementation plans.
* `journal/` contains daily engagement records.
* `scripts/` contains project automation scripts.
* `examples/` contains example inputs and usage artifacts.
* `data/` contains project data artifacts.
