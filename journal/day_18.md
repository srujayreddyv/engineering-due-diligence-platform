# Day 18 Journal

## Work Completed

Implemented the smallest deterministic human-readable presentation over the
existing Day 17 review authority boundary. The `review` command now accepts
`--format json` or `--format markdown`, with JSON remaining the default. Omitted
format and explicit JSON produce the unchanged
`assessment-review-cli-output.v1` bytes.

`assessment-review-report.v1` Markdown is rendered from the same single
verified review object returned by `load_verified_assessment_review`. The
renderer performs no second database load, network request, database write,
clock read, reevaluation, or durable artifact creation. It uses only stored
request context, authoritative evidence, the exact durable evaluation snapshot,
and the optional immutable human decision.

## Deterministic Presentation

The report presents, in locked order:

1. assessment at a glance;
2. items requiring attention;
3. evidence observed;
4. unavailable information;
5. deterministic metrics;
6. policy requirements;
7. human decision; and
8. technical provenance.

Canonical evidence, metric, policy-finding, acknowledgment, condition,
information-request, and provenance ordering is preserved. Dynamic values are
escaped through one deterministic Markdown helper. The document contains no
generation timestamp, and identical verified durable state produces identical
Markdown bytes.

Unavailable evidence is never shown with a normalized value. Available but
freshness-ineligible evidence retains its observed value while its freshness
status is explicit and the report lists it as unusable for deterministic
evaluation. Exact reasons, freshness bases, categories, affected metrics, and
affected findings are displayed where applicable, with fixed text explaining
that unavailable is not false, absent, or unfavorable. Metrics and policy
findings remain separate from evidence. `not_evaluable` remains distinct from
`fail`, and deterministic policy condition templates remain visibly separate
from human-recorded adoption conditions.

The optional decision section reproduces the durable disposition, rationale,
asserted actor label, recording time, ordered conditions, information requests,
and acknowledgments. It states that actor identity is caller asserted and not
authenticated. Conditional approval explicitly says fulfillment is neither
tracked nor verified, and needs-more-information is identified as the immutable
disposition for the assessment.

Technical provenance includes the existing request, evaluation, evidence,
metric, policy, and optional decision identities, versions, input references,
digests, attempt identifiers, and provenance pairs. Raw GitHub response bodies,
snapshot JSON, database paths, internal verification state, scores,
recommendations, legal conclusions, security-posture conclusions, and
condition-fulfillment claims are not rendered.

## Scope

Day 18 adds no domain model, dependency, schema, migration, report persistence,
AI synthesis, PDF, HTML, ANSI formatting, authentication, authorization,
workflow state, decision editing, condition tracking, retry, resume,
reassessment, HTTP API, web UI, or general audit infrastructure. Existing
review failures continue to use the Day 17 versioned sanitized JSON boundary.

## Verification

Twelve focused Day 18 tests cover JSON compatibility, complete report structure
and versioning, canonical order, outcome counts, required acknowledgments,
read-only and clock-free behavior, byte determinism, unavailable-input
semantics, no-decision and recorded-decision states, conditional approval,
needs-more-information, provenance, source-body exclusion, and corruption
failure through the existing verification boundary.

The complete suite passes 281 tests. Compilation of `src` and `tests` passes
with a workspace-safe bytecode cache, and `git diff --check` passes.
