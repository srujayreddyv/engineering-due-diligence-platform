# Durable Decisions

## D001: The Decision Is the Core Abstraction

A repository alone is not sufficient to determine suitability.

Assessment context changes how evidence should be interpreted. The same project
may be suitable for an internal tool and unsuitable for a high criticality
authentication service.

## D002: Evidence Is Stored Separately from Conclusions

Raw evidence must be retained before metrics, policy findings, model
interpretations, or human decisions are produced.

This supports auditability, reproducibility, debugging, and reevaluation.

## D003: Deterministic Software Owns Metrics and Policy

The model does not calculate risk metrics or enforce policy.

Deterministic implementations are easier to test, version, reproduce, and
explain.

## D004: AI Is Used for Grounded Synthesis

AI is used for explanation, tradeoff analysis, uncertainty communication,
reviewer questions, and context aware report generation.

Generated conclusions must use type-correct identifiers from the fixed report
input set: direct factual claims cite `EvidenceRecord`, calculated claims cite
the exact `MetricResult`, and policy conclusions cite the exact
`PolicyFinding`.

## D005: Human Approval Is Required

The platform does not automatically approve or reject technology adoption.

The human reviewer owns the final decision.

## D006: The Initial System Is a Modular Application

The first version will not begin as a collection of microservices.

The architecture may be decomposed only when measured operational requirements
justify the additional complexity.

## D007: Four Week Scope Is Locked

New ideas are recorded in docs/backlog.md.

They enter active scope only when required for the primary workflow, correctness,
security, reliability, evaluation, or essential customer feedback.
