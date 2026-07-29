# Proposed Workflow

## Status

This document defines the proposed target workflow for the scoped four week
prototype. It describes intended behavior and responsibility boundaries. The
workflow is not implemented on Day 1.

## Goal

Produce a reproducible, evidence-grounded decision brief for one public GitHub
repository and one specified engineering use case, support an accountable human
decision, and preserve a permanent audit record.

The workflow assesses a decision in context. It does not assign a universal
quality score to a repository.

## Actors

| Actor | Responsibility |
| --- | --- |
| Staff Software Engineer acting as the engineering reviewer | Submits the request, supplies use-case context, examines findings, and participates in the final decision |
| Platform Engineering Lead | Owns the shared workflow and operational boundaries |
| Application Security Engineer | Defines or reviews security requirements and participates when criticality or policy requires |
| Engineering Manager | Owns product-team operational risk and required management approval |
| Deterministic system components | Validate requests, collect and preserve evidence, calculate metrics, evaluate versioned policy, and control workflow state |
| AI report generator | Produces structured, evidence-grounded explanations and reviewer questions without collecting evidence or deciding |

## End-to-End Workflow

### 1. Submit the Adoption Request

A Staff Software Engineer acting as the engineering reviewer submits:

* public GitHub repository URL;
* intended use;
* runtime or deployment environment;
* criticality;
* expected lifetime;
* organizational risk tolerance; and
* responsible reviewer.

The system creates an immutable request identity and records the submitted
context. A repository used in another context requires a distinct assessment.

### 2. Validate the Request

Deterministic validation confirms that required context is present, the
repository is a supported public GitHub target, and values use known formats.

Invalid or unsupported requests stop with explicit validation results. The
workflow does not ask a model to repair or infer missing required context.

### 3. Collect Authoritative Evidence

Collectors retrieve the minimum evidence required by the scoped workflow from
defined authoritative sources. Each collection attempt records:

* source;
* collection time;
* success or failure status;
* freshness information where available;
* provenance where available; and
* the raw response or relevant source snapshot.

Collectors normalize evidence records but do not calculate metrics, policy
outcomes, or adoption recommendations.

### 4. Persist Raw Evidence

Raw evidence is stored before any metric or conclusion is generated. Evidence
identifiers become the traceable inputs for later stages.

Unavailable, stale, partial, or failed evidence remains represented with an
explicit status. The workflow does not invent a favorable or unfavorable fact
to fill a gap.

### 5. Calculate Deterministic Metrics

Versioned, independently testable calculators derive metrics from stored
evidence. Every metric result records:

* metric name and value;
* input evidence identifiers;
* calculation version and timestamp; and
* availability or confidence status.

The same evidence and calculation version must produce the same metric result.
Model prompts do not own this logic.

### 6. Evaluate Context-Specific Policy

A deterministic, versioned policy engine evaluates evidence and metrics against
the assessment context. Findings identify:

* the requirement evaluated;
* the outcome;
* the evidence or metric identifiers that caused it;
* the policy version; and
* whether human review, conditions, or further investigation are required.

Policy evaluates suitability for this request. It does not produce a universal
repository score.

### 7. Generate an AI-Assisted Decision Brief

The report generator receives only structured assessment context, evidence
references, metric results, and policy findings. It may:

* explain evidence and tradeoffs;
* translate findings into operational consequences;
* identify uncertainty and missing evidence;
* generate questions for the reviewer; and
* organize the material into a strict report schema.

Every material generated claim must reference evidence or policy finding
identifiers. Unsupported claims invalidate the output or lower confidence.

The model does not collect authoritative evidence, calculate metrics, enforce
policy, control workflow state, or grant approval.

### 8. Conduct Human Review

The appropriate engineering, security, and management reviewers inspect the
brief and trace material claims to their sources. They may request further
investigation when evidence is missing, stale, disputed, or insufficient.

Criticality and policy determine which human roles must participate. The
prototype must keep these requirements explicit.

### 9. Record the Human Decision

An authorized human reviewer records one of:

* approve;
* approve with conditions;
* request further investigation; or
* reject.

The decision includes rationale, conditions, reviewer identity, and timestamp.
The platform never converts a model recommendation into automatic approval or
rejection.

### 10. Preserve the Permanent Audit Record

The completed assessment preserves:

1. original request;
2. raw evidence and collection status;
3. calculated metrics;
4. policy findings;
5. policy version;
6. prompt version;
7. model identifier;
8. generated report;
9. human decision and conditions; and
10. audit timestamps and workflow transitions.

This record supports reproduction, debugging, later review, and reevaluation.

## Stage Boundaries

| Stage | Owns | Must not own |
| --- | --- | --- |
| Evidence collection | Source retrieval, status, provenance, normalized evidence | Metrics, policy, recommendations |
| Metric calculation | Deterministic derivation from evidence | Evidence invention, policy, narrative conclusions |
| Policy evaluation | Explicit requirements applied to context and facts | Universal scoring, AI interpretation, human approval |
| AI report generation | Grounded synthesis, uncertainty communication, reviewer questions | Authoritative collection, deterministic calculations, workflow state, approval |
| Human review | Final decision, rationale, conditions, requests for investigation | Silent mutation of evidence, metrics, or policy history |
| Audit history | Immutable linkage and versions across stages | Reinterpretation of historical records |

## Failure and Interruption Handling

* Collection failures are recorded as retryable or nonretryable.
* Missing evidence reduces confidence or triggers further investigation; it is
  never silently treated as a pass.
* A failed stage does not erase earlier persisted records.
* A completed stage is not repeated unnecessarily after interruption.
* Retries preserve attempt history and do not overwrite provenance.
* Invalid AI output is rejected or marked unusable rather than accepted without
  evidence references.
* A human can request further investigation without fabricating a final
  disposition.

Detailed failure behavior will be defined in a later failure-model document
within the locked scope.

## Workflow Outputs

The workflow produces:

* a validated assessment request;
* a versioned evidence set with explicit availability;
* deterministic metrics;
* versioned policy findings;
* a structured, grounded decision brief;
* a human-owned decision with conditions where applicable; and
* a permanent audit record.

These are target outputs. No output-generating application exists on Day 1.

## Evaluation Focus

The prototype will be evaluated for boundary preservation, evidence provenance,
determinism, grounding, failure transparency, human decision ownership, and
audit completeness. Customer workflow validation is measured separately from
system behavior in [success_criteria.md](success_criteria.md).
