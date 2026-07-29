# Current Workflow

## Status

This document is a Day 1 working model of Northstar Software's informal open
source adoption process. It is based on the supplied simulated customer profile
and must be validated during the engagement. It is not a record of observed
production behavior or completed customer interviews.

## Current State

Northstar Software has approximately 60 engineers across six product teams.
Teams evaluate open source repositories as needs arise, but they do not share a
single request format, evidence standard, decision policy, or audit record.
Critical dependencies receive manual Application Security review. Other
decisions are generally handled inside the requesting team.

The repository is often treated as the subject of review without fully
capturing the intended use. This makes it difficult to explain why the same
repository may be acceptable for an internal tool but not for a
high-criticality production service.

## Informal Workflow

### 1. Identify a Candidate

A Staff Software Engineer identifies a public open source repository that could
solve a product or platform need.

Typical inputs:

* repository URL;
* immediate technical need;
* informal implementation preference; and
* links shared by team members.

The intended environment, criticality, expected lifetime, and risk tolerance
may remain implicit.

### 2. Perform an Ad Hoc Technical Review

The engineer reads the README, documentation, release history, issues, and
selected source files. The depth and evidence collected vary by reviewer and
team.

Results may be summarized in a ticket, pull request, document, chat thread, or
meeting notes. Some evidence remains only in a browser session or in the
reviewer's memory.

### 3. Ask for Team Feedback

The requesting team discusses technical fit, maintenance signals, operational
concerns, and prior experience. Review criteria depend on who participates and
what that team has used before.

There is no consistent separation between source evidence, derived metrics,
opinions, conditions, and the eventual decision.

### 4. Escalate Critical Dependencies

If the dependency is considered critical, the team opens a manual security
review. The request may omit context or evidence, requiring the Application
Security Engineer to ask follow-up questions and repeat repository research.

The trigger for "critical" may be interpreted differently across teams.

### 5. Assemble Security and Operational Findings

The Application Security Engineer reviews available vulnerability,
maintenance, licensing, provenance, and operational information as relevant.
Evidence is assembled manually and may reflect the state of external sources at
different times.

The review can identify conditions or unresolved questions, but findings may
not reference durable evidence records or a versioned policy.

### 6. Reach a Decision

The Staff Software Engineer, Application Security Engineer, Engineering
Manager, or some combination of them agrees to adopt, adopt with conditions,
investigate further, or decline the repository.

Decision authority and required sign-off are not consistently recorded.

### 7. Record the Outcome

The outcome is captured in whichever artifact the team used for the review.
Evidence, analysis, approval, conditions, and later updates may be split across
systems.

There is no guaranteed permanent record containing the original request,
evidence, calculations, policy rationale, reviewer decision, and timestamps.

### 8. Revisit When a Problem Occurs

A team may revisit the decision when an incident, vulnerability, upgrade,
ownership change, or new use case creates urgency. Reviewers then reconstruct
the earlier context and evidence where possible.

## Failure Points

| Failure point | Current cause | Consequence to validate |
| --- | --- | --- |
| Incomplete assessment context | Requests begin with a repository and solution preference rather than a structured use case | Reviewers may apply the wrong criticality, lifetime, environment, or risk assumptions |
| Inconsistent evidence | Each reviewer chooses sources and depth independently | Similar requests can receive different scrutiny without an explicit reason |
| Lost provenance | Links, screenshots, and notes are scattered or transient | Later reviewers cannot reliably reproduce what was known at decision time |
| Repeated collection | Product and security reviewers independently research the same repository | Handoffs may create rework and delay |
| Evidence mixed with judgment | Raw facts, calculated signals, opinions, and decisions share one narrative | Reviewers cannot tell which claims are authoritative or challenge calculations independently |
| Implicit policy | Requirements live in reviewer knowledge or informal checklists | Decisions can vary by reviewer and policy changes cannot be reproduced |
| Missing-data ambiguity | Unavailable evidence may be omitted without an explicit status | Absence can be mistaken for a favorable result |
| Unclear decision ownership | Required human roles and allowed dispositions are not explicit | Approval accountability and conditions may be unclear |
| Fragmented audit history | Requests, evidence, discussion, and decisions live in different tools | Prior decisions are difficult to retrieve, explain, or reevaluate |
| Repository-level judgment | Intended use is incompletely captured | A decision may be generalized to contexts with different risk |

The consequences above are discovery hypotheses, not measured business impact.

## Current Inputs and Outputs

### Inputs

* public repository URL;
* informal statement of need;
* reviewer-selected evidence;
* team experience and preferences; and
* security review requirements for critical dependencies.

### Outputs

* a ticket, pull request comment, document, chat decision, or meeting outcome;
* optional conditions or follow-up tasks; and
* no guaranteed unified audit record.

## What Must Be Preserved

The proposed workflow should not remove human judgment, team-specific context,
or the Application Security checkpoint for critical dependencies. It should
make the inputs, evidence, policy, uncertainty, decision authority, and audit
record explicit and reproducible.

## Validation Questions

1. Which steps and failure points accurately reflect the six product teams?
2. What currently triggers Application Security review?
3. Where are decisions and conditions recorded today?
4. Which evidence is repeatedly collected?
5. Which omissions have caused a review to be reopened?
6. Which parts of the process must remain flexible by use case or criticality?

No answers are claimed on Day 1.
