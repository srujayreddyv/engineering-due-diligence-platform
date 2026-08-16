"""Trust-boundary tests for the Day 19 evaluation runner itself."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import run_deterministic_evaluation as runner
from deterministic_evaluation_scenarios import SCENARIOS


def _result(scenario_id, status="passed"):
    return {
        "scenario_id": scenario_id,
        "terminal_expectation": "completed",
        "status": status,
        "observed_evidence_status_projection": [],
        "metric_projection": [],
        "policy_outcome_projection": [],
        "decision_exercise_status": "not_exercised",
        "report_semantic_check_status": "verified",
        "reproducibility_status": "byte_identical",
        "failure_category": None if status == "passed" else "mismatch",
    }


class DeterministicEvaluationRunnerTests(unittest.TestCase):
    def test_scenario_matrix_is_exactly_ordered_e01_through_e10(self):
        self.assertEqual(
            tuple(scenario.scenario_id for scenario in SCENARIOS),
            tuple("E{:02d}".format(index) for index in range(1, 11)),
        )
        self.assertEqual(len(SCENARIOS), 10)

    def test_summary_schema_and_counts_are_stable(self):
        results = [_result("E01"), _result("E02", "failed")]

        summary = runner.build_summary(results)

        self.assertEqual(
            set(summary),
            {
                "output_schema_version",
                "harness_version",
                "definition_versions",
                "scenario_count",
                "passed_count",
                "failed_count",
                "scenario_results",
            },
        )
        self.assertEqual(
            summary["output_schema_version"],
            "deterministic-system-evaluation-output.v1",
        )
        self.assertEqual(summary["scenario_count"], 2)
        self.assertEqual(summary["passed_count"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["scenario_results"], results)

    def test_failure_aggregation_sets_nonzero_exit_without_short_circuiting(self):
        observed = []

        def evaluator(scenario):
            observed.append(scenario.scenario_id)
            status = "failed" if scenario.scenario_id == "E04" else "passed"
            return _result(scenario.scenario_id, status), None

        summary, exit_code = runner.run_evaluation(evaluator)

        self.assertEqual(
            observed,
            [scenario.scenario_id for scenario in SCENARIOS],
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["passed_count"], 9)
        self.assertEqual(summary["failed_count"], 1)

    def test_summary_serialization_is_byte_deterministic_and_has_no_runtime_data(self):
        summary = runner.build_summary([_result("E01")])

        first = runner.serialize_summary(summary)
        second = runner.serialize_summary(summary)

        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.assertTrue(first.endswith("\n"))
        self.assertNotIn("generated_at", first)
        self.assertNotIn("duration", first)
        self.assertNotIn("database", first)
        self.assertNotIn("traceback", first.casefold())

    def test_main_emits_one_summary_and_returns_aggregated_status(self):
        summary = runner.build_summary([_result("E01", "failed")])
        stdout = io.StringIO()

        with patch.object(
            runner, "run_evaluation", return_value=(summary, 1)
        ), redirect_stdout(stdout):
            exit_code = runner.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), runner.serialize_summary(summary))
        self.assertEqual(stdout.getvalue().count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
