"""Focused tests for public GitHub repository metadata collection."""

from __future__ import annotations

import hashlib
import socket
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from urllib.error import URLError
from unittest.mock import patch

from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubRepositoryMetadataCollectionResult,
    collect_public_github_repository_metadata,
)
from engineering_due_diligence.models import EvidenceKind


ATTEMPTED_AT = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
COLLECTOR_VERSION = "public-github-repository-metadata.v1"
SOURCE_IDENTITY = (
    "https://api.github.com/repos/example/reliable-library"
)


def _input(**changes: object) -> GitHubRepositoryMetadataCollectionInput:
    values = {
        "assessment_id": "assessment-day-6",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-6",
        "attempt_number": 1,
        "attempted_at": ATTEMPTED_AT,
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _body(
    *,
    repository_id: object = 123,
    full_name: object = "example/reliable-library",
    archived: object = False,
) -> bytes:
    id_json = (
        str(repository_id).lower()
        if type(repository_id) is bool
        else repr(repository_id).replace("'", '"')
    )
    full_name_json = (
        "null"
        if full_name is None
        else repr(full_name).replace("'", '"')
    )
    archived_json = (
        str(archived).lower()
        if type(archived) is bool
        else (
            "null"
            if archived is None
            else repr(archived).replace("'", '"')
        )
    )
    return (
        '{{"id":{},"full_name":{},"archived":{}}}'.format(
            id_json,
            full_name_json,
            archived_json,
        ).encode("utf-8")
    )


def _assert_no_partial(
    test_case: unittest.TestCase,
    result: GitHubRepositoryMetadataCollectionResult,
) -> None:
    test_case.assertIsNone(result.repository_source_id)
    test_case.assertIsNone(result.archived)
    test_case.assertIsNone(result.raw_snapshot)
    test_case.assertIsNone(result.integrity_digest)
    test_case.assertIsNone(result.response_etag)


class GitHubRepositoryMetadataCollectionTests(unittest.TestCase):
    def test_collection_contracts_are_frozen_and_input_invariants_are_enforced(
        self,
    ) -> None:
        request = _input()
        response_body = _body()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, ()),
        ):
            result = collect_public_github_repository_metadata(request)
        error = GitHubRepositoryMetadataCollectionError(
            category="github_timeout",
            retryability="retryable",
            message="The GitHub repository metadata request timed out.",
        )

        self.assertEqual(
            tuple(outcome.value for outcome in GitHubCollectionOutcome),
            (
                "available",
                "unavailable",
                "failed_retryable",
                "failed_nonretryable",
            ),
        )
        self.assertIs(request.attempted_at, ATTEMPTED_AT)
        self.assertEqual(
            request.repository_identity,
            "github.com/example/reliable-library",
        )
        with self.assertRaises(FrozenInstanceError):
            request.attempt_number = 2
        with self.assertRaises(FrozenInstanceError):
            error.category = "replacement"
        with self.assertRaises(FrozenInstanceError):
            result.archived = True

        invalid_changes = (
            {"assessment_id": ""},
            {"assessment_id": " assessment "},
            {"collection_attempt_id": None},
            {"attempt_number": True},
            {"attempt_number": 0},
            {"attempt_number": -1},
            {"attempted_at": ATTEMPTED_AT.replace(tzinfo=None)},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    _input(**changes)

        invalid_identities = (
            "https://github.com/example/reliable-library",
            "github.com/example/reliable-library/",
            "GITHUB.COM/example/reliable-library",
            "github.com/example",
            "github.com/example/reliable-library/issues",
            "github.com/./reliable-library",
            "github.com/example/..",
            "github.com/example/reliable-library.git",
            "github.com/exämple/reliable-library",
            "github.com/example/reliable library",
        )
        for identity in invalid_identities:
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    _input(repository_identity=identity)

    def test_valid_unarchived_response_returns_complete_available_capture(
        self,
    ) -> None:
        request = _input()
        response_body = _body(archived=False)
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, ()),
        ) as transport:
            result = collect_public_github_repository_metadata(request)

        transport.assert_called_once_with(SOURCE_IDENTITY)
        self.assertIs(result.request, request)
        self.assertEqual(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(
            result.evidence_kind, EvidenceKind.REPOSITORY_ARCHIVED
        )
        self.assertEqual(result.collector_version, COLLECTOR_VERSION)
        self.assertEqual(result.source_identity, SOURCE_IDENTITY)
        self.assertEqual(result.repository_source_id, "123")
        self.assertIs(result.archived, False)
        self.assertEqual(result.raw_snapshot, response_body.decode("utf-8"))
        self.assertEqual(
            result.integrity_digest,
            hashlib.sha256(response_body).hexdigest(),
        )
        self.assertEqual(result.response_status, 200)
        self.assertIsNone(result.response_etag)
        self.assertIsNone(result.error)

    def test_valid_archived_response_returns_true_archived_capture(self) -> None:
        request = _input()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, _body(archived=True), ()),
        ) as transport:
            result = collect_public_github_repository_metadata(request)

        transport.assert_called_once_with(SOURCE_IDENTITY)
        self.assertEqual(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.archived, True)
        self.assertEqual(result.repository_source_id, "123")

    def test_full_name_comparison_is_ascii_case_insensitive_and_source_identity_preserves_requested_casing(
        self,
    ) -> None:
        request = _input(
            repository_identity="github.com/Example/Reliable-Library"
        )
        expected_source = (
            "https://api.github.com/repos/Example/Reliable-Library"
        )
        response_body = _body(full_name="example/reliable-library")
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, ()),
        ) as transport:
            result = collect_public_github_repository_metadata(request)

        transport.assert_called_once_with(expected_source)
        self.assertEqual(
            result.request.repository_identity,
            "github.com/Example/Reliable-Library",
        )
        self.assertEqual(result.source_identity, expected_source)
        self.assertEqual(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIn(
            '"full_name":"example/reliable-library"',
            result.raw_snapshot,
        )

    def test_success_preserves_exact_raw_text_digest_etag_and_unrelated_fields(
        self,
    ) -> None:
        request = _input()
        raw_text = (
            '{\n  "name": "reliable-library", '
            '"id": 987, "owner": {"login": "example"},\n'
            '  "full_name": "example/reliable-library", '
            '"topics": ["security", "python"],\n'
            '  "archived": false, "open_issues_count": 7\n}'
        )
        response_body = raw_text.encode("utf-8")
        headers = (("ETag", '  "source-etag"  '),)
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, headers),
        ) as transport:
            result = collect_public_github_repository_metadata(request)

        transport.assert_called_once_with(SOURCE_IDENTITY)
        self.assertEqual(result.raw_snapshot, raw_text)
        self.assertEqual(
            result.integrity_digest,
            hashlib.sha256(response_body).hexdigest(),
        )
        self.assertEqual(result.response_etag, '"source-etag"')
        self.assertEqual(result.repository_source_id, "987")
        self.assertIs(result.archived, False)

    def test_invalid_success_payload_types_return_sanitized_failure_without_partial_evidence(
        self,
    ) -> None:
        invalid_bodies = (
            ("invalid-utf8", b"\xff"),
            ("malformed-json", b"{"),
            ("non-object", b"[]"),
            (
                "missing-id",
                b'{"full_name":"example/reliable-library","archived":false}',
            ),
            ("missing-full-name", b'{"id":1,"archived":false}'),
            (
                "missing-archived",
                b'{"id":1,"full_name":"example/reliable-library"}',
            ),
            ("nonstandard-constant", b'{"id":1,"full_name":"example/reliable-library","archived":false,"extra":NaN}'),
            ("boolean-id", _body(repository_id=True)),
            ("zero-id", _body(repository_id=0)),
            ("negative-id", _body(repository_id=-1)),
            ("string-id", _body(repository_id="1")),
            ("nonstring-full-name", _body(full_name=7)),
            ("malformed-full-name", _body(full_name="example/repo/extra")),
            ("numeric-archived", _body(archived=1)),
            ("string-archived", _body(archived="false")),
            ("null-archived", _body(archived=None)),
        )

        for name, response_body in invalid_bodies:
            with self.subTest(name=name):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    return_value=(
                        200,
                        response_body,
                        (("ETag", '"must-not-survive"'),),
                    ),
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                self.assertEqual(result.response_status, 200)
                self.assertEqual(
                    result.error.category, "github_response_invalid"
                )
                self.assertEqual(
                    result.error.retryability, "conditionally_retryable"
                )
                self.assertEqual(
                    result.error.message,
                    "GitHub returned an invalid repository metadata response.",
                )
                self.assertNotIn(
                    response_body.decode("utf-8", errors="replace"),
                    result.error.message,
                )
                _assert_no_partial(self, result)

    def test_mismatched_full_name_fails_closed_without_partial_evidence(
        self,
    ) -> None:
        invalid_names = (
            "example/another-repository",
            "example/reliable-library/issues",
            "exämple/reliable-library",
            "./reliable-library",
            "example/..",
            "example/reliable-library.git",
        )
        for full_name in invalid_names:
            with self.subTest(full_name=full_name):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    return_value=(
                        200,
                        _body(full_name=full_name, archived=True),
                        (),
                    ),
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.error.category, "github_response_invalid"
                )
                _assert_no_partial(self, result)

    def test_404_is_unavailable_without_claiming_nonexistence_or_private_visibility(
        self,
    ) -> None:
        secret_body = b'{"message":"private token secret"}'
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(
                404,
                secret_body,
                (("Authorization", "Bearer secret"),),
            ),
        ) as transport:
            result = collect_public_github_repository_metadata(_input())

        transport.assert_called_once_with(SOURCE_IDENTITY)
        self.assertEqual(result.outcome, GitHubCollectionOutcome.UNAVAILABLE)
        self.assertEqual(result.response_status, 404)
        self.assertEqual(
            result.error.category, "repository_not_publicly_available"
        )
        self.assertEqual(
            result.error.message,
            "The repository is not available through the public GitHub endpoint.",
        )
        self.assertNotIn("private", result.error.message.casefold())
        self.assertNotIn("secret", result.error.message.casefold())
        _assert_no_partial(self, result)

    def test_rate_limit_403_and_429_are_retryable_with_only_safe_retry_guidance(
        self,
    ) -> None:
        cases = (
            (
                403,
                (
                    ("x-ratelimit-remaining", "0"),
                    ("retry-after", " 120 "),
                ),
                "120",
            ),
            (429, (("Retry-After", "60"),), "60"),
            (
                429,
                (("Retry-After", "\r\nAuthorization: Bearer secret"),),
                None,
            ),
        )
        for status, headers, expected_retry_after in cases:
            with self.subTest(status=status, headers=headers):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    return_value=(status, b"secret response body", headers),
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_RETRYABLE,
                )
                self.assertEqual(result.error.category, "github_rate_limited")
                self.assertEqual(result.error.retryability, "retryable")
                self.assertEqual(
                    result.error.retry_after, expected_retry_after
                )
                self.assertNotIn("secret", result.error.message.casefold())
                _assert_no_partial(self, result)

    def test_500_and_503_are_retryable_server_failures_without_partial_evidence(
        self,
    ) -> None:
        for status in (500, 503):
            with self.subTest(status=status):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    return_value=(
                        status,
                        b"upstream secret body",
                        (("Retry-After", "30"),),
                    ),
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_RETRYABLE,
                )
                self.assertEqual(result.error.category, "github_server_error")
                self.assertEqual(result.error.retry_after, "30")
                self.assertEqual(result.response_status, status)
                self.assertNotIn("secret", result.error.message.casefold())
                _assert_no_partial(self, result)

    def test_timeout_and_connectivity_failures_return_sanitized_retryable_results(
        self,
    ) -> None:
        cases = (
            (socket.timeout("timeout secret"), "github_timeout"),
            (TimeoutError("timeout token"), "github_timeout"),
            (
                URLError(socket.timeout("wrapped timeout secret")),
                "github_timeout",
            ),
            (URLError("connectivity token"), "github_connectivity_failure"),
            (
                ConnectionError("connection credential"),
                "github_connectivity_failure",
            ),
        )
        for exception, expected_category in cases:
            with self.subTest(exception_type=type(exception).__name__):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    side_effect=exception,
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_RETRYABLE,
                )
                self.assertEqual(result.error.category, expected_category)
                self.assertEqual(result.error.retryability, "retryable")
                self.assertIsNone(result.response_status)
                for unsafe_text in (
                    "secret",
                    "token",
                    "credential",
                ):
                    self.assertNotIn(
                        unsafe_text, result.error.message.casefold()
                    )
                _assert_no_partial(self, result)

    def test_authorization_and_other_4xx_responses_are_safely_classified(
        self,
    ) -> None:
        cases = (
            (
                401,
                (),
                "github_authorization_failed",
                "conditionally_retryable",
            ),
            (
                403,
                (("X-RateLimit-Remaining", "1"),),
                "github_authorization_failed",
                "conditionally_retryable",
            ),
            (
                403,
                (("X-RateLimit-Remaining", "\r\n0"),),
                "github_authorization_failed",
                "conditionally_retryable",
            ),
            (400, (), "github_request_rejected", "nonretryable"),
            (422, (), "github_request_rejected", "nonretryable"),
        )
        for status, headers, category, retryability in cases:
            with self.subTest(status=status):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    return_value=(status, b"credential body", headers),
                ) as transport:
                    result = collect_public_github_repository_metadata(
                        _input()
                    )

                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                self.assertEqual(result.error.category, category)
                self.assertEqual(result.error.retryability, retryability)
                self.assertEqual(result.response_status, status)
                self.assertNotIn("credential", result.error.message.casefold())
                _assert_no_partial(self, result)

    def test_result_invariants_reject_contradictions_and_repeated_normalization_is_deterministic(
        self,
    ) -> None:
        request = _input()
        response_body = _body()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, (("ETag", '"etag"'),)),
        ) as transport:
            first_available = collect_public_github_repository_metadata(request)
            second_available = collect_public_github_repository_metadata(request)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(first_available, second_available)

        changed_snapshot = _body(archived=True).decode("utf-8")
        changed_snapshot_digest = hashlib.sha256(
            changed_snapshot.encode("utf-8")
        ).hexdigest()
        invalid_available_changes = (
            {"repository_source_id": None},
            {"repository_source_id": "0123"},
            {"archived": None},
            {"raw_snapshot": None},
            {"integrity_digest": "0" * 64},
            {
                "raw_snapshot": changed_snapshot,
                "integrity_digest": changed_snapshot_digest,
            },
            {"evidence_kind": EvidenceKind.LICENSE_STATUS},
            {"collector_version": "public-github-repository-metadata.v2"},
            {"source_identity": "https://api.github.com/repos/other/repo"},
            {"response_status": True},
            {"response_etag": "unsafe\nvalue"},
        )
        for changes in invalid_available_changes:
            with self.subTest(available_changes=changes):
                with self.assertRaises(ValueError):
                    replace(first_available, **changes)

        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(404, b"ignored", ()),
        ):
            unavailable = collect_public_github_repository_metadata(request)
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(503, b"ignored", ()),
        ):
            first_failure = collect_public_github_repository_metadata(request)
            second_failure = collect_public_github_repository_metadata(request)
        self.assertEqual(first_failure, second_failure)

        authorization_error = GitHubRepositoryMetadataCollectionError(
            category="github_authorization_failed",
            retryability="conditionally_retryable",
            message=(
                "GitHub did not authorize the public repository metadata request."
            ),
        )
        invalid_nonavailable_cases = (
            (unavailable, {"repository_source_id": "123"}),
            (unavailable, {"raw_snapshot": "{}"}),
            (first_failure, {"archived": False}),
            (
                first_failure,
                {"outcome": GitHubCollectionOutcome.FAILED_NONRETRYABLE},
            ),
            (first_failure, {"error": authorization_error}),
            (first_failure, {"response_status": 99}),
        )
        for original, changes in invalid_nonavailable_cases:
            with self.subTest(nonavailable_changes=changes):
                with self.assertRaises(ValueError):
                    replace(original, **changes)


if __name__ == "__main__":
    unittest.main()
