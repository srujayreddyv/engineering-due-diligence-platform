# Deterministic System Evaluation

## Purpose

Day 19 evaluates whether the implemented prototype behaves according to its
current deterministic contracts across a deliberately varied set of repository
facts and adoption contexts. It exercises the complete product workflow rather
than isolated calculation functions.

This is a ten-scenario engineered conformance suite. It is not a statistical
accuracy evaluation, validation of the provisional adoption policy by a real
policy owner, evidence of commercial optimality, or a customer-ROI study.

## Method

The network-free runner sends frozen GitHub-shaped response bytes through the
real transport and collector path, invokes the real noninteractive `assess`,
JSON and Markdown `review`, and selected `decide` CLI paths, and uses disposable
schema-v5 SQLite databases. Existing private seams freeze assessment identity,
submission time, collection time, evaluation time, decision time, and
transport responses. Production source, policy, schema, and persistence
behavior are not replaced by evaluation implementations.

Every successful scenario checks the canonical four evidence records, four
metrics, four policy findings, exact reasons and applicable condition
templates, definition versions, snapshot identity and digest, required
approval acknowledgments, JSON/Markdown agreement, report semantic boundaries,
and absence of raw response bodies or an automatic recommendation. Each
successful scenario is rerun from a fresh database; stable review JSON,
Markdown, and applicable decision output must be byte identical.

Run the evaluation from the repository root without network access:

```bash
PYTHONPATH=src python3 scripts/run_deterministic_evaluation.py
```

The runner emits exactly one
`deterministic-system-evaluation-output.v1` JSON summary and exits zero only
when all ten scenarios conform.

## Frozen Scenario Matrix

| ID | Scenario | Expected product terminal behavior | Expected policy outcomes in canonical order | Fixed human-supplied workflow exercise |
| --- | --- | --- | --- | --- |
| E01 | Healthy active repository | Completed; exact assessment replay | `pass`, `pass`, `pass`, `pass` | Record caller-supplied `approve`. |
| E02 | Archived repository | Completed; no automatic human decision | `fail`, `pass`, `pass`, `pass` | None. |
| E03 | License metadata absent in tolerant context | Completed | `pass`, `condition_required`, `pass`, `pass` | Record caller-supplied `approve_with_conditions`, then exercise exact decision replay. |
| E04 | Effective security policy absent in tolerant context | Completed; available `false` remains distinct from unavailable | `pass`, `pass`, `pass`, `condition_required` | None. |
| E05 | 365-day-old commit for critical long-lived use | Completed | `pass`, `pass`, `fail`, `pass` | None. |
| E06 | Tolerant side of paired repository facts | Completed | `pass`, `condition_required`, `pass`, `condition_required` | None. |
| E07 | Low-risk-tolerance side of the same paired facts | Completed | `pass`, `fail`, `fail`, `fail` | None. |
| E08 | Empty valid latest-commit response | Completed | `pass`, `pass`, `not_evaluable`, `pass` | Record caller-supplied `needs_more_information`. |
| E09 | Rate limit after archived and license collection | Retryable collection failure; no evaluation or decision | No authoritative policy result | None. |
| E10 | Corrupted durable evaluation | Review and decision fail closed with sanitized verification output | Corrupt result is not presented | None. |

The product-terminal and policy columns state deterministic conformance
expectations. The decision exercises are fixed caller-supplied actions used only
to test decision recording; they are not expected, correct, recommended, or
system-generated adoption decisions.

The outcome order is `repository_not_archived`, `license_declared`,
`commit_recency`, and `security_policy`.

## Observed Result

10 of 10 predefined deterministic conformance scenarios passed.

All completed assessments produced the expected evidence, metric, policy, and
review projections. E01 preserved its durable evaluation identity and original
evaluation time on exact assessment replay. E03 preserved the original human
decision identity and recording time on exact decision replay. No scenario
produced a system-owned adoption recommendation.

## Context Sensitivity

E06 and E07 used byte-identical GitHub-shaped responses, the same evaluation
time, and identical repository facts and metric projections. Only risk
tolerance changed. The tolerant context produced two
`condition_required` findings while the low-tolerance context produced three
`fail` findings. This demonstrates the implemented product claim that the
assessment context—not repository facts alone—is part of the policy decision
object.

## Unavailable Information

E08 used a valid empty commits response. Latest-commit evidence remained
`unavailable` with `repository_has_no_commits`; no timestamp was invented.
`days_since_latest_commit` remained `unavailable` with insufficient input, and
`commit_recency` remained `not_evaluable`, never `pass` or `fail`. Markdown
preserved the fixed explanation that unavailable information was not
established and must not be interpreted as false, absent, or unfavorable. The
separate human exercise recorded `needs_more_information`; the system did not
derive that disposition.

## Failure Behavior

E09 preserved and verified the first two authoritative evidence records, then
stopped on a sanitized retryable GitHub rate-limit failure. It did not call the
later collector, read the evaluation clock, create an evaluation snapshot,
present metrics or policy findings as authoritative, or permit a decision.

E10 altered only the disposable evaluation digest using the same narrow SQLite
technique used by persistence tests. Review returned the existing sanitized
`verification_failed` contract without a report, internal corruption detail,
database path, or SQL text. Decision recording also failed before mutation.

## Reproducibility

E01 through E08 were each executed twice from fresh temporary databases using
identical frozen identities, times, contexts, and response bytes. Review JSON,
review Markdown, and each applicable first decision output were byte identical
between runs. The structured evaluation summary excludes generation time,
duration, temporary paths, raw source bodies, tracebacks, and volatile
environment data.

## Limitations

The scenario matrix is small and intentionally engineered. Its passing result
demonstrates implementation conformance only. It does not establish how often
the current policy produces useful outcomes in live customer work, whether the
provisional thresholds and conditions reflect an organization's policy, or
whether GitHub behavior outside these frozen responses is adequately
represented.

Later live-repository demonstrations should establish realism and practical
usefulness against changing public data. Those demonstrations must remain
separate from this frozen correctness harness and must not weaken its
reproducibility.
