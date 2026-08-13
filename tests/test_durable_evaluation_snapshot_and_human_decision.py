"""Focused schema-v5 evaluation snapshot and human-decision tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import engineering_due_diligence.persistence as persistence
from engineering_due_diligence.assessment import (
    ASSESSMENT_EVALUATION_SCHEMA_VERSION,
    assessment_evaluation_id,
    build_assessment_evaluation_snapshot,
    evaluate_persisted_assessment,
)
from engineering_due_diligence.models import (
    HumanDecisionDisposition,
    PolicyOutcome,
)
from engineering_due_diligence.persistence import (
    SQLitePersistenceError,
    load_verified_assessment_evaluation_snapshot,
    load_verified_human_decision,
    persist_assessment_evaluation_snapshot,
    persist_github_latest_commit_collection,
    persist_github_license_status_collection,
    persist_github_repository_metadata_collection,
    persist_github_security_policy_presence_collection,
    persist_human_decision,
    persist_valid_assessment_request,
)
from tests.test_durable_assessment_evaluation import (
    ASSESSMENT_ID,
    EVALUATED_AT,
    _archived_result,
    _latest_result,
    _license_result,
    _security_result,
    _valid_request,
)


RECORDED_AT = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


def _old_table_rows(path):
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(
                "SELECT {} FROM {} ORDER BY {}".format(
                    ",".join(columns), table, columns[0]
                )
            ).fetchall()
            for table, columns in persistence._EXPECTED_COLUMNS_V4.items()
        }


def _database_dump(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


def _downgrade_empty_v5_concepts_to_exact_v4(path):
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE human_decisions")
        connection.execute("DROP TABLE assessment_evaluation_snapshots")
        connection.execute("PRAGMA user_version = 4")
        connection.commit()


class DurableEvaluationSnapshotAndDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "day-16.sqlite3"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _persist_evidence(self, path=None, *, unavailable_archived=False):
        path = path or self.database_path
        request = _valid_request()
        persist_valid_assessment_request(path, request)
        persist_github_repository_metadata_collection(
            path, _archived_result(unavailable=unavailable_archived)
        )
        persist_github_license_status_collection(path, _license_result())
        persist_github_latest_commit_collection(path, _latest_result())
        persist_github_security_policy_presence_collection(
            path, _security_result()
        )
        return request

    def _persist_snapshot(
        self,
        path=None,
        evaluated_at=EVALUATED_AT,
        *,
        unavailable_archived=True,
    ):
        path = path or self.database_path
        self._persist_evidence(
            path, unavailable_archived=unavailable_archived
        )
        result = evaluate_persisted_assessment(
            path, ASSESSMENT_ID, evaluated_at
        )
        snapshot = persist_assessment_evaluation_snapshot(path, result)
        return result, snapshot

    def _decision_kwargs(self, snapshot, **changes):
        nonpassing = tuple(
            finding.policy_finding_id
            for finding in snapshot.policy_findings
            if finding.outcome is not PolicyOutcome.PASS
        )
        values = {
            "assessment_id": ASSESSMENT_ID,
            "assessment_evaluation_id": snapshot.assessment_evaluation_id,
            "decision_maker_actor_id": "actor-reviewer",
            "disposition": HumanDecisionDisposition.APPROVE,
            "rationale": "The reviewed evidence supports adoption.",
            "conditions": (),
            "information_requests": (),
            "acknowledged_policy_finding_ids": nonpassing,
        }
        values.update(changes)
        return values

    def test_v4_to_v5_migration_preserves_existing_rows(self):
        self._persist_evidence()
        before = _old_table_rows(self.database_path)
        _downgrade_empty_v5_concepts_to_exact_v4(self.database_path)

        persist_valid_assessment_request(
            self.database_path, _valid_request()
        )

        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertFalse(connection.execute("PRAGMA foreign_key_check").fetchall())
        self.assertEqual(version, 5)
        self.assertEqual(
            tables,
            set(persistence._EXPECTED_COLUMNS),
        )
        self.assertEqual(_old_table_rows(self.database_path), before)

    def test_v4_to_v5_migration_failure_rolls_back_to_exact_v4(self):
        self._persist_evidence()
        before = _old_table_rows(self.database_path)
        _downgrade_empty_v5_concepts_to_exact_v4(self.database_path)
        original_verify = persistence._verify_schema_definition

        def fail_v5(connection, expected_columns, expected_sql):
            if expected_columns is persistence._EXPECTED_COLUMNS:
                raise SQLitePersistenceError("schema_incompatible")
            return original_verify(connection, expected_columns, expected_sql)

        with patch.object(
            persistence,
            "_verify_schema_definition",
            side_effect=fail_v5,
        ):
            with self.assertRaises(SQLitePersistenceError):
                persist_valid_assessment_request(
                    self.database_path, _valid_request()
                )

        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 4
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        self.assertEqual(tables, set(persistence._EXPECTED_COLUMNS_V4))
        self.assertEqual(_old_table_rows(self.database_path), before)

    def test_evaluation_identity_and_canonical_payload_are_exact(self):
        self._persist_evidence()
        result = evaluate_persisted_assessment(
            self.database_path, ASSESSMENT_ID, EVALUATED_AT
        )
        first = build_assessment_evaluation_snapshot(result)
        second = build_assessment_evaluation_snapshot(result)
        payload = json.loads(first.snapshot_json)
        payload_bytes = first.snapshot_json.encode("utf-8")

        self.assertEqual(first, second)
        self.assertEqual(
            set(payload),
            {
                "assessment_id",
                "evaluated_at",
                "evaluation_schema_version",
                "evidence_references",
                "metric_results",
                "policy_findings",
            },
        )
        self.assertNotIn("assessment_evaluation_id", payload)
        self.assertNotIn("integrity_digest", payload)
        self.assertEqual(
            first.snapshot_json,
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        self.assertEqual(
            first.evaluation_schema_version,
            ASSESSMENT_EVALUATION_SCHEMA_VERSION,
        )
        self.assertEqual(
            first.integrity_digest,
            hashlib.sha256(payload_bytes).hexdigest(),
        )
        self.assertEqual(
            first.assessment_evaluation_id,
            assessment_evaluation_id(payload_bytes),
        )
        with self.assertRaises(FrozenInstanceError):
            first.integrity_digest = "0" * 64

    def test_snapshot_persists_reopens_and_exactly_replays(self):
        result, first = self._persist_snapshot()
        before = _database_dump(self.database_path)
        replay = persist_assessment_evaluation_snapshot(
            self.database_path, result
        )
        reopened = load_verified_assessment_evaluation_snapshot(
            self.database_path, ASSESSMENT_ID
        )
        after = _database_dump(self.database_path)

        self.assertEqual(replay, first)
        self.assertEqual(reopened, first)
        self.assertEqual(after, before)
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT assessment_evaluation_id, assessment_id, "
                "snapshot_json, integrity_digest "
                "FROM assessment_evaluation_snapshots"
            ).fetchone()
            count = connection.execute(
                "SELECT COUNT(*) FROM assessment_evaluation_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(
            row,
            (
                first.assessment_evaluation_id,
                first.assessment_id,
                first.snapshot_json,
                first.integrity_digest,
            ),
        )

    def test_conflicting_evaluation_replay_has_no_mutation(self):
        self._persist_snapshot()
        before = _database_dump(self.database_path)
        changed = evaluate_persisted_assessment(
            self.database_path,
            ASSESSMENT_ID,
            EVALUATED_AT + timedelta(seconds=1),
        )

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_assessment_evaluation_snapshot(
                self.database_path, changed
            )

        self.assertEqual(raised.exception.category, "conflicting_replay")
        self.assertEqual(
            _database_dump(self.database_path), before
        )

    def test_snapshot_digest_or_payload_corruption_fails_closed(self):
        for field, value in (
            ("integrity_digest", "0" * 64),
            ("snapshot_json", '{"assessment_id":"corrupt"}'),
        ):
            with self.subTest(field=field):
                path = Path(self.temporary_directory.name) / (
                    field + ".sqlite3"
                )
                self._persist_snapshot(path)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE assessment_evaluation_snapshots "
                        "SET {} = ?".format(field),
                        (value,),
                    )
                    connection.commit()
                with self.assertRaises(SQLitePersistenceError) as raised:
                    load_verified_assessment_evaluation_snapshot(
                        path, ASSESSMENT_ID
                    )
                self.assertEqual(
                    raised.exception.category, "verification_failed"
                )

    def test_all_four_human_dispositions_persist_and_reopen(self):
        cases = (
            (HumanDecisionDisposition.APPROVE, (), (), True),
            (
                HumanDecisionDisposition.APPROVE_WITH_CONDITIONS,
                ("Pin the reviewed major version.",),
                (),
                True,
            ),
            (
                HumanDecisionDisposition.NEEDS_MORE_INFORMATION,
                (),
                ("Provide the operating owner.",),
                False,
            ),
            (HumanDecisionDisposition.REJECT, (), (), False),
        )
        for index, (disposition, conditions, requests, acknowledge) in enumerate(cases):
            with self.subTest(disposition=disposition):
                path = Path(self.temporary_directory.name) / (
                    "decision-{}.sqlite3".format(index)
                )
                _, snapshot = self._persist_snapshot(path)
                kwargs = self._decision_kwargs(
                    snapshot,
                    disposition=disposition,
                    conditions=conditions,
                    information_requests=requests,
                    acknowledged_policy_finding_ids=(
                        self._decision_kwargs(snapshot)[
                            "acknowledged_policy_finding_ids"
                        ]
                        if acknowledge
                        else ()
                    ),
                )
                with patch.object(
                    persistence,
                    "_current_decision_time",
                    return_value=RECORDED_AT,
                ):
                    decision = persist_human_decision(path, **kwargs)
                self.assertEqual(
                    load_verified_human_decision(path, ASSESSMENT_ID),
                    decision,
                )
                self.assertIs(decision.disposition, disposition)
                self.assertEqual(decision.recorded_at, RECORDED_AT)

    def test_decision_identity_excludes_generated_id(self):
        _, snapshot = self._persist_snapshot()
        kwargs = self._decision_kwargs(snapshot)
        with patch.object(
            persistence,
            "_current_decision_time",
            return_value=RECORDED_AT,
        ):
            decision = persist_human_decision(
                self.database_path, **kwargs
            )
        payload = {
            "assessment_id": decision.assessment_id,
            "assessment_evaluation_id": decision.assessment_evaluation_id,
            "decision_maker_actor_id": decision.decision_maker_actor_id,
            "disposition": decision.disposition.value,
            "rationale": decision.rationale,
            "conditions": list(decision.conditions),
            "information_requests": list(decision.information_requests),
            "acknowledged_policy_finding_ids": list(
                decision.acknowledged_policy_finding_ids
            ),
            "recorded_at": decision.recorded_at.isoformat(),
            "decision_schema_version": decision.decision_schema_version,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_id = "human-decision-" + hashlib.sha256(
            b"human-decision-id.v1\0" + canonical
        ).hexdigest()
        self.assertNotIn("human_decision_id", payload)
        self.assertEqual(decision.human_decision_id, expected_id)
        with self.assertRaises(FrozenInstanceError):
            decision.rationale = "changed"

    def test_decision_reviewer_reference_and_rationale_validation(self):
        _, snapshot = self._persist_snapshot()
        invalid_changes = (
            {"decision_maker_actor_id": "actor-other"},
            {"assessment_evaluation_id": "assessment-evaluation-" + "0" * 64},
            {"rationale": ""},
            {"rationale": " padded "},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_human_decision(
                        self.database_path,
                        **self._decision_kwargs(snapshot, **changes),
                    )
                self.assertEqual(raised.exception.category, "invalid_input")
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM human_decisions"
                ).fetchone()[0],
                0,
            )

    def test_disposition_specific_content_and_acknowledgments_are_strict(self):
        cases = (
            {"conditions": ("Unexpected.",)},
            {
                "disposition": HumanDecisionDisposition.APPROVE_WITH_CONDITIONS,
                "conditions": (),
            },
            {
                "disposition": HumanDecisionDisposition.APPROVE_WITH_CONDITIONS,
                "conditions": ("",),
            },
            {
                "disposition": HumanDecisionDisposition.APPROVE_WITH_CONDITIONS,
                "conditions": ("Duplicate.", "Duplicate."),
            },
            {
                "disposition": HumanDecisionDisposition.NEEDS_MORE_INFORMATION,
                "acknowledged_policy_finding_ids": (),
                "information_requests": (),
            },
            {
                "disposition": HumanDecisionDisposition.NEEDS_MORE_INFORMATION,
                "acknowledged_policy_finding_ids": (),
                "information_requests": (" padded ",),
            },
            {
                "disposition": HumanDecisionDisposition.REJECT,
                "acknowledged_policy_finding_ids": (),
                "information_requests": ("Unexpected.",),
            },
            {"acknowledged_policy_finding_ids": ()},
            {
                "acknowledged_policy_finding_ids": (
                    "unknown-policy-finding",
                )
            },
        )
        for index, changes in enumerate(cases):
            with self.subTest(index=index):
                path = Path(self.temporary_directory.name) / (
                    "invalid-decision-{}.sqlite3".format(index)
                )
                _, snapshot = self._persist_snapshot(path)
                with self.assertRaises(SQLitePersistenceError) as raised:
                    persist_human_decision(
                        path,
                        **self._decision_kwargs(snapshot, **changes),
                    )
                self.assertEqual(raised.exception.category, "invalid_input")

    def test_recorded_at_must_be_aware_utc_and_not_before_evaluation(self):
        invalid_times = (
            RECORDED_AT.replace(tzinfo=None),
            RECORDED_AT.astimezone(timezone(timedelta(hours=2))),
            EVALUATED_AT.astimezone(timezone.utc) - timedelta(seconds=1),
        )
        for index, recorded_at in enumerate(invalid_times):
            with self.subTest(recorded_at=recorded_at):
                path = Path(self.temporary_directory.name) / (
                    "invalid-time-{}.sqlite3".format(index)
                )
                _, snapshot = self._persist_snapshot(path)
                with patch.object(
                    persistence,
                    "_current_decision_time",
                    return_value=recorded_at,
                ):
                    with self.assertRaises(SQLitePersistenceError) as raised:
                        persist_human_decision(
                            path, **self._decision_kwargs(snapshot)
                        )
                self.assertEqual(raised.exception.category, "invalid_input")

    def test_exact_decision_replay_ignores_system_fields(self):
        _, snapshot = self._persist_snapshot()
        kwargs = self._decision_kwargs(snapshot)
        with patch.object(
            persistence,
            "_current_decision_time",
            side_effect=(RECORDED_AT, RECORDED_AT + timedelta(days=1)),
        ) as clock:
            first = persist_human_decision(self.database_path, **kwargs)
            before = _database_dump(self.database_path)
            second = persist_human_decision(self.database_path, **kwargs)
            after = _database_dump(self.database_path)
        self.assertEqual(second, first)
        self.assertEqual(second.recorded_at, RECORDED_AT)
        self.assertEqual(second.human_decision_id, first.human_decision_id)
        self.assertEqual(before, after)
        clock.assert_called_once_with()

    def test_changed_decision_replay_conflicts_without_mutation(self):
        _, snapshot = self._persist_snapshot()
        kwargs = self._decision_kwargs(snapshot)
        with patch.object(
            persistence,
            "_current_decision_time",
            return_value=RECORDED_AT,
        ):
            persist_human_decision(self.database_path, **kwargs)
        before = _database_dump(self.database_path)

        with self.assertRaises(SQLitePersistenceError) as raised:
            persist_human_decision(
                self.database_path,
                **self._decision_kwargs(
                    snapshot, rationale="A materially changed rationale."
                ),
            )

        self.assertEqual(raised.exception.category, "conflicting_replay")
        self.assertEqual(
            _database_dump(self.database_path), before
        )
        with self.assertRaises(SQLitePersistenceError) as changed_shape:
            persist_human_decision(
                self.database_path,
                **self._decision_kwargs(
                    snapshot,
                    disposition=HumanDecisionDisposition.REJECT,
                ),
            )
        self.assertEqual(
            changed_shape.exception.category, "conflicting_replay"
        )
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM human_decisions"
                ).fetchone()[0],
                1,
            )

    def test_decision_corruption_fails_reopen_verification(self):
        _, snapshot = self._persist_snapshot()
        with patch.object(
            persistence,
            "_current_decision_time",
            return_value=RECORDED_AT,
        ):
            persist_human_decision(
                self.database_path, **self._decision_kwargs(snapshot)
            )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE human_decisions SET rationale = ?",
                ("Corrupted but structurally valid rationale.",),
            )
            connection.commit()

        with self.assertRaises(SQLitePersistenceError) as raised:
            load_verified_human_decision(
                self.database_path, ASSESSMENT_ID
            )
        self.assertEqual(raised.exception.category, "verification_failed")


if __name__ == "__main__":
    unittest.main()
