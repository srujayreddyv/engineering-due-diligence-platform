"""Focused tests for public GitHub license-status collection."""

from __future__ import annotations

import hashlib
import json
import socket
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import URLError

from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubLicenseStatusCollectionResult,
    GitHubRepositoryMetadataCollectionInput,
    collect_public_github_license_status,
)
from engineering_due_diligence.models import EvidenceKind, LicenseStatus


ATTEMPTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
SOURCE_IDENTITY = "https://api.github.com/repos/example/reliable-library"
COLLECTOR_VERSION = "public-github-license-status.v1"


def _input(**changes: object) -> GitHubRepositoryMetadataCollectionInput:
    values = {
        "assessment_id": "assessment-day-9",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-9-license-1",
        "attempt_number": 1,
        "attempted_at": ATTEMPTED_AT,
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _body(
    *,
    repository_id: object = 9123,
    full_name: object = "example/reliable-library",
    license_metadata: object = ...,
    include_license: bool = True,
    **extra: object,
) -> bytes:
    payload = {
        "id": repository_id,
        "full_name": full_name,
        **extra,
    }
    if include_license:
        payload["license"] = (
            {
                "key": "mit",
                "name": "MIT License",
                "spdx_id": "MIT",
            }
            if license_metadata is ...
            else license_metadata
        )
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _collect(
    response: tuple[object, object, object],
    request: GitHubRepositoryMetadataCollectionInput | None = None,
) -> GitHubLicenseStatusCollectionResult:
    with patch(
        "engineering_due_diligence.github._get_public_github_repository",
        return_value=response,
    ):
        return collect_public_github_license_status(request or _input())


def _assert_no_partial(
    test_case: unittest.TestCase,
    result: GitHubLicenseStatusCollectionResult,
) -> None:
    test_case.assertIsNone(result.repository_source_id)
    test_case.assertIsNone(result.license_status)
    test_case.assertIsNone(result.raw_snapshot)
    test_case.assertIsNone(result.integrity_digest)
    test_case.assertIsNone(result.response_etag)


class GitHubLicenseStatusCollectionTests(unittest.TestCase):
    def test_exactly_one_patched_transport_call_and_frozen_contract(self) -> None:
        request = _input()
        response_body = _body()
        with patch(
            "engineering_due_diligence.github._get_public_github_repository",
            return_value=(200, response_body, ()),
        ) as transport:
            result = collect_public_github_license_status(request)

        transport.assert_called_once_with(SOURCE_IDENTITY)
        self.assertIs(result.request, request)
        self.assertIs(result.evidence_kind, EvidenceKind.LICENSE_STATUS)
        self.assertEqual(result.collector_version, COLLECTOR_VERSION)
        with self.assertRaises(FrozenInstanceError):
            result.license_status = LicenseStatus.ABSENT
        contradictions = (
            {"evidence_kind": EvidenceKind.REPOSITORY_ARCHIVED},
            {"license_status": LicenseStatus.ABSENT},
            {"repository_source_id": None},
            {"integrity_digest": "0" * 64},
            {"response_status": 404},
        )
        for changes in contradictions:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(result, **changes)

    def test_license_object_becomes_present(self) -> None:
        result = _collect((200, _body(), ()))

        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.license_status, LicenseStatus.PRESENT)
        self.assertEqual(result.repository_source_id, "9123")
        self.assertIsNone(result.error)

    def test_license_null_becomes_absent(self) -> None:
        result = _collect((200, _body(license_metadata=None), ()))

        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.license_status, LicenseStatus.ABSENT)

    def test_missing_license_field_fails(self) -> None:
        result = _collect((200, _body(include_license=False), ()))

        self.assertEqual(result.error.category, "github_response_invalid")
        _assert_no_partial(self, result)

    def test_invalid_license_types_fail_without_coercion(self) -> None:
        for value in (False, True, 0, 1, "MIT", [], ["MIT"]):
            with self.subTest(value=value):
                result = _collect((200, _body(license_metadata=value), ()))
                self.assertEqual(
                    result.error.category, "github_response_invalid"
                )
                _assert_no_partial(self, result)

    def test_invalid_required_license_object_fields_fail(self) -> None:
        valid = {"key": "mit", "name": "MIT License", "spdx_id": "MIT"}
        invalid_values = (None, False, 1, "", " MIT ", "line\nbreak")
        for field_name in ("key", "name", "spdx_id"):
            missing = dict(valid)
            missing.pop(field_name)
            candidates = [missing]
            for invalid in invalid_values:
                candidate = dict(valid)
                candidate[field_name] = invalid
                candidates.append(candidate)
            for candidate in candidates:
                with self.subTest(field=field_name, candidate=candidate):
                    result = _collect(
                        (200, _body(license_metadata=candidate), ())
                    )
                    self.assertEqual(
                        result.error.category, "github_response_invalid"
                    )

    def test_repository_id_is_strict_positive_nonboolean_integer(self) -> None:
        for repository_id in (True, False, 0, -1, "9123", 9123.0):
            with self.subTest(repository_id=repository_id):
                result = _collect(
                    (200, _body(repository_id=repository_id), ())
                )
                self.assertEqual(
                    result.error.category, "github_response_invalid"
                )

    def test_repository_full_name_is_strictly_bound_case_insensitively(self) -> None:
        request = _input(
            repository_identity="github.com/Example/Reliable-Library"
        )
        result = _collect(
            (200, _body(full_name="example/reliable-library"), ()),
            request,
        )
        mismatch = _collect(
            (200, _body(full_name="other/reliable-library"), ())
        )

        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertEqual(
            result.source_identity,
            "https://api.github.com/repos/Example/Reliable-Library",
        )
        self.assertEqual(mismatch.error.category, "github_response_invalid")

    def test_unrelated_repository_and_license_fields_are_preserved(self) -> None:
        raw_text = (
            '{"id":9123,"full_name":"example/reliable-library",'
            '"topics":["security"],"license":{"key":"mit",'
            '"name":"MIT License","spdx_id":"MIT",'
            '"url":"https://api.github.com/licenses/mit","node_id":"L1"},'
            '"open_issues_count":7}'
        )
        result = _collect((200, raw_text.encode("utf-8"), ()))

        self.assertEqual(result.raw_snapshot, raw_text)
        self.assertIn('"node_id":"L1"', result.raw_snapshot)
        self.assertIn('"open_issues_count":7', result.raw_snapshot)

    def test_exact_successful_text_and_digest_are_preserved(self) -> None:
        raw_text = (
            '{\n  "full_name": "example/reliable-library", '
            '"license": {"spdx_id":"MIT","name":"MIT License",'
            '"key":"mit"},\n  "id": 9123\n}'
        )
        response_body = raw_text.encode("utf-8")
        result = _collect((200, response_body, ()))

        self.assertEqual(result.raw_snapshot, raw_text)
        self.assertEqual(
            result.integrity_digest,
            hashlib.sha256(response_body).hexdigest(),
        )

    def test_etag_is_sanitized(self) -> None:
        safe = _collect((200, _body(), (("ETag", '  "safe"  '),)))
        unsafe = _collect((200, _body(), (("ETag", "secret\r\nLeak"),)))

        self.assertEqual(safe.response_etag, '"safe"')
        self.assertIsNone(unsafe.response_etag)

    def test_repository_404_is_unavailable(self) -> None:
        result = _collect((404, None, (("ETag", '"secret"'),)))

        self.assertIs(result.outcome, GitHubCollectionOutcome.UNAVAILABLE)
        self.assertEqual(
            result.error.category, "repository_not_publicly_available"
        )
        _assert_no_partial(self, result)

    def test_rate_limit_is_retryable(self) -> None:
        for status, headers in (
            (429, (("Retry-After", "60"),)),
            (403, (("X-RateLimit-Remaining", "0"),)),
        ):
            with self.subTest(status=status):
                result = _collect((status, None, headers))
                self.assertIs(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_RETRYABLE,
                )
                self.assertEqual(result.error.category, "github_rate_limited")

    def test_authorization_failure_is_nonretryable(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                result = _collect((status, None, ()))
                self.assertIs(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                self.assertEqual(
                    result.error.category, "github_authorization_failed"
                )

    def test_server_failure_is_retryable(self) -> None:
        result = _collect((503, None, (("Retry-After", "120"),)))

        self.assertIs(
            result.outcome, GitHubCollectionOutcome.FAILED_RETRYABLE
        )
        self.assertEqual(result.error.category, "github_server_error")
        self.assertEqual(result.error.retry_after, "120")

    def test_timeouts_are_retryable(self) -> None:
        for failure in (socket.timeout("private"), URLError(socket.timeout())):
            with self.subTest(failure=type(failure).__name__):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    side_effect=failure,
                ):
                    result = collect_public_github_license_status(_input())
                self.assertEqual(result.error.category, "github_timeout")
                self.assertNotIn("private", result.error.message)

    def test_connectivity_failures_are_retryable_and_sanitized(self) -> None:
        for failure in (ConnectionError("credential"), URLError("private")):
            with self.subTest(failure=type(failure).__name__):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    side_effect=failure,
                ):
                    result = collect_public_github_license_status(_input())
                self.assertEqual(
                    result.error.category, "github_connectivity_failure"
                )
                self.assertNotIn("private", result.error.message)

    def test_malformed_success_responses_fail_safely(self) -> None:
        invalid = (
            b"\xff",
            b"{",
            b"[]",
            b"null",
            b'{"id":9123,"full_name":"example/reliable-library",'
            b'"license":null,"extra":NaN}',
        )
        for response_body in invalid:
            with self.subTest(response_body=response_body):
                result = _collect((200, response_body, ()))
                self.assertEqual(
                    result.error.category, "github_response_invalid"
                )

    def test_other_rejected_request_is_nonretryable(self) -> None:
        result = _collect((422, None, ()))

        self.assertIs(
            result.outcome, GitHubCollectionOutcome.FAILED_NONRETRYABLE
        )
        self.assertEqual(result.error.category, "github_request_rejected")

    def test_every_unsuccessful_outcome_contains_no_partial_evidence(self) -> None:
        results = (
            _collect((404, b"secret", (("ETag", '"secret"'),))),
            _collect((429, b"secret", ())),
            _collect((401, b"secret", ())),
            _collect((500, b"secret", ())),
            _collect((200, b"{}", (("ETag", '"secret"'),))),
        )
        for result in results:
            with self.subTest(category=result.error.category):
                _assert_no_partial(self, result)
                self.assertNotIn("secret", result.error.message)


if __name__ == "__main__":
    unittest.main()
