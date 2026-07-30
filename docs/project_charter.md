# Project Charter

## Engagement

The Engineering Due Diligence Platform is a four week simulated Forward
Deployed Engineering engagement. The engagement will define, prototype, and
evaluate a reliable and auditable decision support workflow for open source
technology adoption.

The customer and discovery activities described in this repository are
simulated. They provide a credible delivery context but do not represent
completed interviews, production usage, or measured business impact.

## Scope Lock

> **Scope is locked for the four week engagement. New ideas will be captured in
> the backlog and will not enter the active plan unless they are necessary to
> complete the core workflow.**

## Project Mission

Build a reliable and auditable decision support workflow for evaluating whether
a public open source repository is appropriate for a specified engineering use
case.

## Simulated Customer

The simulated customer is Northstar Software, a medium sized software
organization with approximately 60 engineers across six product teams.
Northstar's teams use open source dependencies but do not follow one consistent
adoption process. Individual teams collect different evidence, apply different
risk thresholds, and preserve decisions in different places.

Critical dependencies receive a manual security review. That review provides an
important control, but it depends on handoffs, manually assembled evidence, and
reviewer availability. Lower-criticality decisions may receive only an
informal team review.

## Customer Problem

Northstar cannot consistently answer why a repository was accepted for one use
case, rejected for another, or approved with conditions. The current process
makes evidence difficult to reproduce, context easy to omit, and prior
decisions hard to revisit when facts change.

The customer needs a workflow that:

* evaluates suitability in the context of an intended use rather than assigning
  a universal repository score;
* preserves authoritative raw evidence before deriving metrics or conclusions;
* applies explicit, versioned policy;
* uses AI only for evidence-grounded synthesis;
* keeps the final decision with a human reviewer; and
* preserves a permanent record of the request, evidence, analysis, report, and
  decision.

## Stakeholders

| Stakeholder | Engagement responsibility | Primary need |
| --- | --- | --- |
| Platform Engineering Lead | Owns the shared adoption workflow and its fit across product teams | A repeatable process, clear operating boundaries, and maintainable platform ownership |
| Application Security Engineer | Reviews critical dependencies and defines security requirements | Authoritative evidence, explicit policy findings, provenance, and a reviewable exception path |
| Staff Software Engineer | Submits adoption requests and evaluates technical fit | A workflow that captures use-case context and explains tradeoffs without hiding evidence |
| Engineering Manager | Owns delivery and operational risk for a product team | A concise decision brief, explicit conditions, accountable approval, and an auditable record |

## Primary Workflow

1. An engineering reviewer submits a public GitHub repository.
2. The reviewer describes the intended use, environment, criticality, expected
   lifetime, and organizational risk tolerance.
3. The system validates the request.
4. Evidence collectors retrieve data from authoritative sources.
5. The system stores raw evidence.
6. Deterministic metric calculators derive signals from the evidence.
7. The policy engine evaluates context specific requirements.
8. The AI report generator explains findings and uncertainty.
9. A human reviewer records a final decision.
10. The system preserves the request, evidence, versions, report, and decision.

## In Scope

The four week engagement covers one end-to-end assessment workflow for a public
GitHub repository and one specified engineering use case:

* structured capture and validation of assessment context;
* collection of the minimum authoritative evidence needed by the workflow;
* storage of raw evidence with provenance and collection status;
* deterministic, versioned metric calculation;
* context-specific, versioned policy evaluation;
* structured, evidence-grounded AI report generation;
* human decisions of approve, approve with conditions, request further
  investigation, or reject;
* preservation of an audit record; and
* prototype evaluation, failure testing, and essential observability for this
  workflow.

## Out of Scope

The following are explicitly outside the four week engagement:

* private repository support;
* GitLab or other source-hosting providers;
* continuous monitoring after an assessment;
* automated dependency installation, upgrade, or remediation;
* side-by-side technology comparison or recommendation;
* vendor due diligence;
* AI model due diligence;
* automatic approval or rejection;
* broad source ecosystems unrelated to the public GitHub workflow;
* a general-purpose agent platform;
* distributed microservices without demonstrated operational need; and
* enterprise interfaces or collectors that are not necessary for the core
  workflow;
* a production-grade web interface; and
* organization-wide analytics or benchmarking.

Deferred ideas are recorded in [backlog.md](backlog.md). A backlog entry is not
an engagement commitment.

## Deliverables

By the end of the engagement, the intended deliverables are:

1. complete project, workflow, architecture, evaluation, and operating
   documentation;
2. a tested prototype of the scoped assessment workflow;
3. a small, documented evaluation set and evaluation results;
4. an evidence-grounded decision brief suitable for human review;
5. an auditable record for completed prototype assessments; and
6. a handoff that identifies limitations, risks, and recommended next steps.

These are planned deliverables. At Day 1, only the engagement foundation and
repository documentation exist.

## Engagement Milestones

### Week 1 — Engagement and System Definition

Complete the charter, discovery model, workflows, domain and failure models,
evaluation methodology, architecture decisions, and implementation plan.

### Week 2 — Deterministic Workflow Foundation

Implement and test the assessment context, evidence record, persistence,
deterministic metric, policy, and workflow foundations required by the scoped
vertical slice.

### Week 3 — Collection and Grounded Reporting

Integrate the minimum public GitHub evidence collection, structured grounded
reporting, human review path, audit history, and essential observability.

### Week 4 — Evaluation, Reliability, and Handoff

Run the evaluation set, address material correctness and reliability gaps,
document limitations, and prepare the engagement handoff.

Milestones after Day 1 describe planned work, not completed capability.

## Guardrails

* Assessment context, not repository identity alone, determines suitability.
* Raw evidence is stored before metrics or conclusions.
* Evidence, metrics, policy findings, model interpretations, and human decisions
  remain distinguishable.
* Deterministic software owns metrics and policy.
* Material generated claims use type-correct references from the fixed report
  input set: direct factual claims cite `EvidenceRecord`, calculated claims cite
  the exact `MetricResult`, and policy conclusions cite the exact
  `PolicyFinding`.
* Missing evidence remains explicit and reduces confidence.
* A human owns the final adoption decision.
* Meaningful architectural changes require an ADR.
* No new scope enters the active plan without satisfying the scope-lock rule.

## Engagement Governance

The Platform Engineering Lead is the simulated delivery owner. The Application
Security Engineer owns security policy input and critical-dependency review.
Product-team reviewers submit context and evidence questions. Engineering
Managers own the operational acceptance of final decisions for their teams.

Plans describe current execution, checkpoints summarize engagement state, ADRs
record meaningful architectural decisions, the backlog holds deferred ideas,
and the journal records what actually happened.

## Known Day 1 Limitations

No customer interviews, prototype evaluations, runtime components, external
integrations, databases, model integrations, or business-impact measurements
have been completed. Customer needs and validation criteria are documented as
simulated hypotheses until evaluated during the engagement.
