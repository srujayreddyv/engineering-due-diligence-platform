# Backlog

## Backlog Policy

This file records useful ideas that are outside the active four week
engagement. A backlog entry is not approved scope, a delivery commitment, or an
implemented capability.

Items enter the active plan only when they are required for the primary
workflow, correctness, security, reliability, evaluation, or essential customer
feedback. Any entry that changes architecture or scope also requires explicit
review and, where meaningful, an ADR.

## Deferred Ideas

| ID | Idea | Potential value | Reason deferred | Reconsideration trigger |
| --- | --- | --- | --- | --- |
| B001 | Private GitHub repository support | Evaluate internal or commercially sensitive repositories | Requires authentication, authorization, secret handling, and enterprise data boundaries beyond the public workflow | A validated customer need that cannot be evaluated with public repositories and an approved security design |
| B002 | GitLab and additional source providers | Support teams using other repository hosts | Adds provider abstractions and collectors before the first GitHub workflow is proven | Completion of the public GitHub workflow plus essential customer demand |
| B003 | Continuous monitoring and reassessment | Detect evidence changes after a decision | Adds scheduling, notification, lifecycle, and stale-decision semantics | The one-time assessment is reliable and a monitoring interval and owner are defined |
| B004 | Automated installation or upgrades | Shorten the path from approval to adoption | Moves the platform from decision support into code and environment mutation | A separate approved product scope with security, rollback, and ownership controls |
| B005 | Automated remediation | Respond directly to adverse findings | Introduces destructive actions and operational risk beyond assessment | A separately governed remediation workflow with explicit human authorization |
| B006 | Side-by-side technology comparison | Help teams choose among multiple repositories | Requires a comparison domain and could encourage a universal score | The single-assessment workflow is validated and a context-aware comparison method is approved |
| B007 | Vendor due diligence | Evaluate commercial suppliers | Requires different evidence, contracts, ownership, and policy | A separate engagement charter for vendor assessment |
| B008 | AI model due diligence | Evaluate models and model providers | Requires model-specific evidence, evaluation, and governance | A separate approved domain and evaluation methodology |
| B009 | Automatic approval or rejection | Reduce manual decision steps | Violates the current human decision boundary and increases accountability risk | Not eligible within the current mission; would require an explicit replacement of durable decision D005 |
| B010 | General-purpose agent platform | Support autonomous multi-step work beyond the assessment | Expands the product domain and weakens deterministic boundaries | A separate product decision after the core workflow is complete |
| B011 | Microservice decomposition | Independently deploy or scale components | Adds operational complexity without measured need | Demonstrated reliability, scaling, or ownership requirements documented in an ADR |
| B012 | Broad enterprise interfaces and collectors | Integrate additional ticketing, messaging, asset, or policy systems | Increases interface count before essential workflow needs are known | Essential customer feedback identifies a blocking handoff in the core workflow |
| B013 | Production-grade web interface | Provide a polished interactive experience | Day 1 and the initial vertical slice prioritize workflow correctness and auditability | The core workflow and user tasks are validated and the required interface is defined |
| B014 | Organization-wide analytics and benchmarking | Compare adoption activity across teams | Requires sufficient real usage, privacy review, and stable metrics | Real adoption records, approved aggregation rules, and a validated decision need |

## Active-Scope Exclusions

No backlog item above should appear in a task plan, milestone claim, or README
feature list as active work unless its reconsideration trigger has been met and
the scope change has been explicitly approved.

## How to Add an Item

A useful deferred idea should include:

1. the customer or engineering value it might provide;
2. why it is not necessary for the current primary workflow;
3. the risk or complexity it introduces; and
4. the concrete evidence that would justify reconsideration.

Do not use this file for daily progress, defects in active scope, or task notes.
