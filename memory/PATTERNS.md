# Engineering Patterns

## General Change Pattern

Before a meaningful implementation task:

1. Read AGENTS.md and all memory files.
2. Inspect relevant source code and tests.
3. Create or update a task plan.
4. State assumptions and acceptance criteria.
5. Implement the smallest complete change.
6. Run focused tests.
7. Run the broader verification suite.
8. Review correctness, security, reliability, and scope.
9. Update durable memory only when lasting knowledge changed.

## Evidence Collection Pattern

Collectors return normalized evidence records.

Collectors do not calculate adoption recommendations.

Raw responses or relevant source snapshots are preserved before derived
calculations occur.

Every collection attempt records success, failure, timestamp, source, and
freshness information.

## Metric Pattern

Metrics are deterministic and independently testable.

A metric result includes:

1. Metric name
2. Metric value
3. Input evidence identifiers
4. Calculation version
5. Calculation timestamp
6. Availability or confidence status

## Policy Pattern

Policies evaluate metric and evidence facts against explicit assessment context.

Policy results must explain which requirement was evaluated and which evidence
or metric caused the result.

Avoid a universal repository quality score.

## AI Output Pattern

AI output uses a strict structured schema.

Every material conclusion must reference evidence or policy finding identifiers.

Unsupported claims invalidate the output or lower confidence.

## Workflow Pattern

Workflow stages are explicit and persisted.

A completed stage should not be repeated unnecessarily after interruption.

Failures are categorized as retryable or nonretryable.

## Testing Pattern

Every behavior change requires focused tests.

Deterministic calculations require unit tests.

External collectors require mocked failure tests.

Workflow stages require integration tests.

Bugs require regression tests.
