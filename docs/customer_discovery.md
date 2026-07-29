# Customer Discovery

## Status and Method

This is a simulated Day 1 discovery brief for a four week Forward Deployed
Engineering engagement. It translates the supplied customer profile into
testable workflow hypotheses and interview questions. It is not a transcript of
real interviews and does not claim observed customer behavior or measured
impact.

## Customer Profile

Northstar Software is a simulated medium sized software organization with
approximately 60 engineers across six product teams. The teams build and operate
software with different criticality and lifetime expectations.

Open source adoption practices are inconsistent across teams. Critical
dependencies receive manual security review, while lower-criticality adoption
decisions are often handled within product teams. Evidence, rationale,
conditions, and approvals are not captured through one shared workflow.

## Discovery Goal

Determine whether one context-aware, evidence-grounded assessment workflow can
give engineering and security stakeholders enough trustworthy information to
make and revisit a human adoption decision.

Discovery does not attempt to prove broad business impact. It focuses on the
workflow, information, accountability, and audit needs of the scoped prototype.

## Stakeholder Hypotheses

### Platform Engineering Lead

Working hypotheses:

* Cross-team inconsistency creates repeated review work and unclear ownership.
* A shared workflow is valuable only if teams can use it without bypassing
  important security controls.
* Versioned policies and reusable evidence may improve consistency, but the
  operating burden must remain manageable.

Questions to validate:

1. Which adoption decisions should enter a shared workflow?
2. Which context fields are mandatory before evidence collection begins?
3. Who owns policy changes and workflow operations?
4. What would make product teams bypass the workflow?

### Application Security Engineer

Working hypotheses:

* Review time is spent assembling and validating evidence as well as evaluating
  risk.
* Missing provenance and inconsistent context make decisions difficult to
  reproduce.
* Critical dependencies require a visible human security checkpoint.

Questions to validate:

1. Which authoritative evidence is required for the first workflow?
2. Which findings block a decision, require conditions, or require more
   investigation?
3. How should unavailable or stale evidence affect confidence?
4. What evidence and rationale must be retained for an exception?

### Staff Software Engineer

Working hypotheses:

* Engineers need to explain the intended use before repository signals can be
  interpreted.
* A concise brief is useful only when engineers can trace conclusions to
  evidence.
* Clear conditions may be more actionable than a binary recommendation.

Questions to validate:

1. What information is known when an adoption request begins?
2. Which parts of the current review are repetitive or ambiguous?
3. What level of evidence detail is needed to challenge a finding?
4. How should a reviewer request additional investigation?

### Engineering Manager

Working hypotheses:

* Managers need decision ownership, operational consequences, and unresolved
  uncertainty to be explicit.
* A permanent decision record may help when dependencies outlive the original
  reviewer or team context.
* Final approval cannot be delegated to a model.

Questions to validate:

1. Which decisions require manager awareness or approval?
2. What conditions must be tracked after approval?
3. What makes a decision brief clear enough to support accountability?
4. When should an assessment be revisited?

## Provided Facts and Assumptions

### Provided Engagement Facts

* The customer has approximately 60 engineers across six product teams.
* Open source adoption practices are inconsistent.
* Critical dependencies receive manual security review.
* The initial product workflow evaluates public GitHub repositories for a
  specified engineering use case.
* The engagement lasts four weeks and its scope is locked.

### Assumptions Requiring Validation

* Evidence gathering is duplicated across teams.
* Decision rationale is stored inconsistently or is difficult to retrieve.
* Review handoffs create avoidable waiting and rework.
* Stakeholders agree on the minimum context and evidence needed for the first
  workflow.
* A structured decision brief can be concise without obscuring provenance or
  uncertainty.

These assumptions must not be reported later as customer findings unless the
evaluation produces evidence for them.

## Initial Use-Case Frame

Each prototype assessment concerns one public GitHub repository and one
specified use case. The request must describe:

* intended use;
* runtime or deployment environment;
* criticality;
* expected lifetime;
* organizational risk tolerance; and
* the reviewer responsible for the final decision.

The same repository may receive different decisions for different contexts.
Discovery must therefore test the assessment workflow, not seek a universal
repository quality score.

## Evidence and Decision Needs to Validate

The engagement should validate whether reviewers can:

1. identify the source and collection time of material evidence;
2. distinguish raw evidence from calculated metrics;
3. understand which policy requirement produced each finding;
4. trace material report claims to evidence or policy finding identifiers;
5. see missing or stale evidence and its effect on confidence;
6. record a human decision and any conditions; and
7. retrieve the complete audit record for later review.

## Discovery Risks

* A simulated customer profile may conceal workflow variation that real
  interviews would expose.
* Stakeholder needs may conflict, particularly between review speed and evidence
  depth.
* A workflow that is complete for critical dependencies may be too heavy for
  lower-criticality use cases.
* A polished report may create false confidence if evidence provenance or
  missing data is not prominent.

## Planned Validation Activities

1. Review the current-workflow model with representatives of all four simulated
   stakeholder roles.
2. Walk one representative adoption request through the proposed workflow.
3. Test whether each stakeholder can locate evidence, uncertainty, policy
   rationale, decision ownership, and audit history.
4. Record disagreements and essential feedback without expanding scope
   automatically.
5. Use the criteria in [success_criteria.md](success_criteria.md) to distinguish
   system acceptance from customer workflow validation.

These activities are planned. None has been completed on Day 1.
