"""Focused tests for the minimal assessment command-line interface."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.cli as cli
import engineering_due_diligence.workflow as workflow


FIXED_UUID = uuid.UUID("12345678-1234-4234-8234-123456789abc")
ASSESSMENT_ID = "assessment-12345678-1234-4234-8234-123456789abc"
REPOSITORY_ENDPOINT = "https://api.github.com/repos/Owner/Repository"
COMMITS_ENDPOINT = REPOSITORY_ENDPOINT + "/commits?per_page=1"
POLICY_ENDPOINT = (
    REPOSITORY_ENDPOINT + "/contents/.github/SECURITY.md"
)
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
POLICY_SHA = "a" * 40
SUBMITTED_AT = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
ATTEMPTED_AT = datetime(2026, 8, 10, 8, 1, tzinfo=timezone.utc)
EVALUATED_AT = datetime(
    2026,
    8,
    10,
    10,
    2,
    tzinfo=timezone(timedelta(hours=2)),
)
_UNSET = object()


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _complete_responses():
    return [
        (
            200,
            _json_bytes(
                {
                    "id": 101,
                    "full_name": "Owner/Repository",
                    "archived": False,
                    "unrelated": "private-full-source-marker",
                }
            ),
            (("ETag", '"archived-etag"'),),
        ),
        (
            200,
            _json_bytes(
                {
                    "id": 101,
                    "full_name": "Owner/Repository",
                    "license": {
                        "key": "mit",
                        "name": "MIT License",
                        "spdx_id": "MIT",
                    },
                    "unrelated": ["private-license-source"],
                }
            ),
            (("ETag", '"license-etag"'),),
        ),
        (
            200,
            _json_bytes(
                [
                    {
                        "sha": COMMIT_SHA,
                        "url": (
                            REPOSITORY_ENDPOINT
                            + "/commits/"
                            + COMMIT_SHA
                        ),
                        "commit": {
                            "committer": {
                                "date": "2026-08-08T12:00:00-05:00"
                            }
                        },
                        "unrelated": "private-commit-source",
                    }
                ]
            ),
            (("ETag", '"commit-etag"'),),
        ),
        (
            200,
            _json_bytes(
                {
                    "id": 101,
                    "full_name": "Owner/Repository",
                    "unrelated": "private-security-repository-source",
                }
            ),
            (("ETag", '"security-repository-etag"'),),
        ),
        (
            200,
            _json_bytes(
                {
                    "type": "file",
                    "name": "SECURITY.md",
                    "path": ".github/SECURITY.md",
                    "size": 42,
                    "sha": POLICY_SHA,
                    "url": POLICY_ENDPOINT,
                    "content": "cHJpdmF0ZS1wb2xpY3ktc291cmNl",
                }
            ),
            (("ETag", '"policy-etag"'),),
        ),
    ]


class AssessmentCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "assessment-cli.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _arguments(self, **changes):
        values = {
            "database": str(self.database_path),
            "repository": "https://github.com/Owner/Repository",
            "intended_use": "Critical production authentication dependency",
            "environment": "production",
            "criticality": "critical",
            "expected_lifetime_days": "1825",
            "risk_tolerance": "low",
            "submitted_by_actor_id": "actor-submitter",
            "responsible_reviewer_actor_id": "actor-reviewer",
        }
        values.update(changes)
        return [
            "assess",
            "--database",
            values["database"],
            "--repository",
            values["repository"],
            "--intended-use",
            values["intended_use"],
            "--environment",
            values["environment"],
            "--criticality",
            values["criticality"],
            "--expected-lifetime-days",
            values["expected_lifetime_days"],
            "--risk-tolerance",
            values["risk_tolerance"],
            "--submitted-by-actor-id",
            values["submitted_by_actor_id"],
            "--responsible-reviewer-actor-id",
            values["responsible_reviewer_actor_id"],
        ]

    def _invoke(
        self,
        arguments,
        *,
        responses=(),
        execution_error=None,
        execution_result=_UNSET,
        output_override=None,
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with ExitStack() as stack:
            transport = stack.enter_context(
                patch(
                    "engineering_due_diligence.github."
                    "_get_public_github_repository",
                    side_effect=responses,
                )
            )
            uuid_seam = stack.enter_context(
                patch.object(cli, "_new_uuid", return_value=FIXED_UUID)
            )
            cli_clock = stack.enter_context(
                patch.object(
                    cli,
                    "_current_utc_time",
                    side_effect=(SUBMITTED_AT, ATTEMPTED_AT),
                )
            )
            workflow_clock = stack.enter_context(
                patch.object(
                    workflow,
                    "_current_evaluation_time",
                    return_value=EVALUATED_AT,
                )
            )
            if execution_error is not None:
                execution = stack.enter_context(
                    patch.object(
                        cli,
                        "execute_assessment",
                        side_effect=execution_error,
                    )
                )
            elif execution_result is not _UNSET:
                execution = stack.enter_context(
                    patch.object(
                        cli,
                        "execute_assessment",
                        return_value=execution_result,
                    )
                )
            else:
                execution = stack.enter_context(
                    patch.object(
                        cli,
                        "execute_assessment",
                        wraps=cli.execute_assessment,
                    )
                )
            if output_override is not None:
                stack.enter_context(
                    patch.object(
                        cli,
                        "_execution_output",
                        return_value=output_override,
                    )
                )
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            exit_code = cli.main(arguments)
        return {
            "exit_code": exit_code,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "transport": transport,
            "uuid": uuid_seam,
            "cli_clock": cli_clock,
            "workflow_clock": workflow_clock,
            "execution": execution,
        }

    def test_complete_execution_emits_canonical_machine_readable_result(self):
        invoked = self._invoke(
            self._arguments(), responses=_complete_responses()
        )

        self.assertEqual(invoked["exit_code"], 0)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(
            output["output_schema_version"], "assessment-cli-output.v1"
        )
        self.assertEqual(output["status"], "complete")
        self.assertEqual(
            output["assessment"]["assessment_id"], ASSESSMENT_ID
        )
        self.assertEqual(
            output["assessment"]["submitted_at"], SUBMITTED_AT.isoformat()
        )
        self.assertEqual(
            output["assessment"]["collection_attempted_at"],
            ATTEMPTED_AT.isoformat(),
        )
        self.assertEqual(
            output["assessment"]["evaluated_at"],
            EVALUATED_AT.isoformat(),
        )
        self.assertEqual(
            output["context"],
            {
                "assessment_id": ASSESSMENT_ID,
                "repository_identity": "github.com/Owner/Repository",
                "intended_use": (
                    "Critical production authentication dependency"
                ),
                "environment": "production",
                "criticality": "critical",
                "expected_lifetime_days": 1825,
                "risk_tolerance": "low",
            },
        )
        self.assertEqual(
            [record["evidence_kind"] for record in output["evidence_records"]],
            [
                "repository_archived",
                "license_status",
                "latest_commit_timestamp",
                "security_policy_present",
            ],
        )
        self.assertEqual(len(output["metric_results"]), 4)
        self.assertEqual(len(output["policy_findings"]), 4)
        self.assertEqual(
            output["human_decision"], {"status": "not_implemented"}
        )
        self.assertNotIn("recommendation", output)
        self.assertNotIn('"recommendation"', invoked["stdout"])
        self.assertTrue(
            all(
                metric["calculated_at"] == EVALUATED_AT.isoformat()
                for metric in output["metric_results"]
            )
        )
        self.assertTrue(
            all(
                finding["evaluated_at"] == EVALUATED_AT.isoformat()
                for finding in output["policy_findings"]
            )
        )

        first_provenance = output["evidence_records"][0]["provenance"]
        self.assertIs(type(first_provenance), list)
        self.assertEqual(
            [entry["key"] for entry in first_provenance],
            [
                "source_snapshot_id",
                "source_snapshot_integrity_digest",
                "repository_source_id",
            ],
        )
        for record in output["evidence_records"]:
            self.assertNotIn("raw_snapshot", record)
            self.assertNotIn("response_bytes", record)
        for source_marker in (
            "private-full-source-marker",
            "private-license-source",
            "private-commit-source",
            "private-security-repository-source",
            "cHJpdmF0ZS1wb2xpY3ktc291cmNl",
        ):
            self.assertNotIn(source_marker, invoked["stdout"])

        invoked["uuid"].assert_called_once_with()
        self.assertEqual(invoked["cli_clock"].call_count, 2)
        invoked["workflow_clock"].assert_called_once_with()
        invoked["execution"].assert_called_once()
        execution_input = invoked["execution"].call_args.args[1]
        self.assertIs(execution_input.request.submitted_at, SUBMITTED_AT)
        self.assertIs(
            execution_input.collection_attempted_at, ATTEMPTED_AT
        )
        self.assertFalse(hasattr(execution_input, "evaluated_at"))
        self.assertEqual(invoked["transport"].call_count, 5)
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 4
            )

    def test_invalid_request_returns_validation_without_side_effects(self):
        invoked = self._invoke(
            self._arguments(repository="http://github.com/Owner/Repository")
        )

        self.assertEqual(invoked["exit_code"], 3)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(output["status"], "invalid_request")
        self.assertEqual(
            [error["field"] for error in output["validation_errors"]],
            ["submitted_repository_locator"],
        )
        self.assertIsNone(output["context"])
        self.assertIsNone(output["assessment"]["evaluated_at"])
        self.assertEqual(output["evidence_records"], [])
        self.assertEqual(output["metric_results"], [])
        self.assertEqual(output["policy_findings"], [])
        self.assertFalse(self.database_path.exists())
        invoked["transport"].assert_not_called()
        invoked["workflow_clock"].assert_not_called()
        invoked["execution"].assert_called_once()

    def test_collection_failure_is_sanitized_and_has_no_partial_results(self):
        invoked = self._invoke(
            self._arguments(), responses=[(503, None, ())]
        )

        self.assertEqual(invoked["exit_code"], 4)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(output["status"], "collection_failed")
        self.assertEqual(
            output["collection_failure"]["evidence_kind"],
            "repository_archived",
        )
        self.assertEqual(
            output["collection_failure"]["outcome"], "failed_retryable"
        )
        self.assertEqual(
            output["collection_failure"]["error"]["category"],
            "github_server_error",
        )
        self.assertEqual(output["evidence_records"], [])
        self.assertEqual(output["metric_results"], [])
        self.assertEqual(output["policy_findings"], [])
        invoked["workflow_clock"].assert_not_called()
        invoked["execution"].assert_called_once()
        invoked["transport"].assert_called_once_with(REPOSITORY_ENDPOINT)

    def test_persistence_failure_is_sanitized_without_database_path(self):
        database_path = ":memory:"
        invoked = self._invoke(
            self._arguments(database=database_path)
        )

        self.assertEqual(invoked["exit_code"], 5)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(output["status"], "persistence_failed")
        self.assertEqual(
            output["error"],
            {
                "category": "invalid_database_path",
                "message": (
                    "The database path must identify an on-disk SQLite "
                    "database."
                ),
            },
        )
        self.assertNotIn(database_path, invoked["stdout"])
        self.assertNotIn("sqlite3", invoked["stdout"].casefold())
        invoked["transport"].assert_not_called()
        invoked["workflow_clock"].assert_not_called()
        invoked["execution"].assert_called_once()

    def test_usage_error_is_json_and_has_no_execution_activity(self):
        invoked = self._invoke(
            ["assess", "--database", str(self.database_path)]
        )

        self.assertEqual(invoked["exit_code"], 2)
        self.assertEqual(invoked["stdout"], "")
        output = json.loads(invoked["stderr"])
        self.assertEqual(output["status"], "usage_error")
        self.assertEqual(
            output["error"],
            {
                "category": "usage_error",
                "message": "The command arguments are invalid.",
            },
        )
        invoked["uuid"].assert_not_called()
        invoked["cli_clock"].assert_not_called()
        invoked["workflow_clock"].assert_not_called()
        invoked["execution"].assert_not_called()
        invoked["transport"].assert_not_called()
        self.assertFalse(self.database_path.exists())

    def test_unexpected_failure_is_constant_sanitized_json(self):
        unsafe_message = (
            "secret-token SQL SELECT /private/database.sqlite3 traceback"
        )
        invoked = self._invoke(
            self._arguments(),
            execution_error=RuntimeError(unsafe_message),
        )

        self.assertEqual(invoked["exit_code"], 1)
        self.assertEqual(invoked["stdout"], "")
        output = json.loads(invoked["stderr"])
        self.assertEqual(output["status"], "internal_error")
        self.assertEqual(
            output["error"],
            {
                "category": "internal_error",
                "message": "The assessment could not be completed.",
            },
        )
        self.assertNotIn(unsafe_message, invoked["stderr"])
        self.assertNotIn("traceback", invoked["stderr"].casefold())
        self.assertNotIn("select", invoked["stderr"].casefold())
        invoked["execution"].assert_called_once()
        invoked["transport"].assert_not_called()

    def test_unexpected_output_serialization_failure_is_sanitized(self):
        invoked = self._invoke(
            self._arguments(),
            execution_result=object(),
            output_override=({"unsafe": object()}, 0),
        )

        self.assertEqual(invoked["exit_code"], 1)
        self.assertEqual(invoked["stdout"], "")
        output = json.loads(invoked["stderr"])
        self.assertEqual(output["status"], "internal_error")
        self.assertEqual(
            output["error"],
            {
                "category": "internal_error",
                "message": "The assessment could not be completed.",
            },
        )
        self.assertNotIn("object is not JSON serializable", invoked["stderr"])
        self.assertNotIn("traceback", invoked["stderr"].casefold())
        invoked["transport"].assert_not_called()

    def test_invalid_enum_is_domain_validation_not_usage_failure(self):
        invoked = self._invoke(
            self._arguments(environment="unsupported-environment")
        )

        self.assertEqual(invoked["exit_code"], 3)
        self.assertEqual(invoked["stderr"], "")
        output = json.loads(invoked["stdout"])
        self.assertEqual(output["status"], "invalid_request")
        self.assertEqual(
            [
                (error["field"], error["code"])
                for error in output["validation_errors"]
            ],
            [("environment", "invalid_environment")],
        )
        invoked["transport"].assert_not_called()
        invoked["workflow_clock"].assert_not_called()
        self.assertFalse(self.database_path.exists())


if __name__ == "__main__":
    unittest.main()
