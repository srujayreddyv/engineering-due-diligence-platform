"""Focused tests for public GitHub latest-commit collection."""

from __future__ import annotations

import hashlib
import json
import socket
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from urllib.error import URLError
from unittest.mock import patch

from engineering_due_diligence.github import (
    GitHubCollectionOutcome,
    GitHubLatestCommitCollectionResult,
    GitHubRepositoryMetadataCollectionInput,
    collect_public_github_latest_commit,
)
from engineering_due_diligence.models import EvidenceKind


SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE_TIMESTAMP = "2026-08-07T14:15:16Z"
SOURCE_IDENTITY = (
    "https://api.github.com/repos/example/reliable-library/commits?per_page=1"
)


def _input(**changes: object) -> GitHubRepositoryMetadataCollectionInput:
    values = {
        "assessment_id": "assessment-day-10",
        "repository_identity": "github.com/example/reliable-library",
        "collection_attempt_id": "collection-attempt-day-10-1",
        "attempt_number": 1,
        "attempted_at": datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
    }
    values.update(changes)
    return GitHubRepositoryMetadataCollectionInput(**values)


def _payload(
    *,
    sha: object = SHA,
    url: object | None = None,
    committer_date: object = SOURCE_TIMESTAMP,
    author_date: object = "1999-01-01T00:00:00Z",
    unrelated: bool = False,
) -> bytes:
    commit_url = url if url is not None else (
        "https://api.github.com/repos/example/reliable-library/commits/{}".format(
            SHA
        )
    )
    item = {
        "sha": sha,
        "url": commit_url,
        "commit": {
            "author": {"date": author_date},
            "committer": {"date": committer_date},
        },
    }
    if unrelated:
        item.update({"node_id": "commit-node", "parents": [{"sha": "parent"}]})
        item["commit"]["message"] = "preserved"
    return json.dumps([item], separators=(",", ":")).encode("utf-8")


def _collect(response, request: GitHubRepositoryMetadataCollectionInput | None = None):
    request = request or _input()
    expected_source = (
        "https://api.github.com/repos/{}/commits?per_page=1".format(
            request.repository_identity.removeprefix("github.com/")
        )
    )
    with patch(
        "engineering_due_diligence.github._get_public_github_repository",
        return_value=response,
    ) as transport:
        result = collect_public_github_latest_commit(request)
    transport.assert_called_once_with(expected_source)
    return result


def _assert_no_partial(test: unittest.TestCase, result) -> None:
    test.assertIsNone(result.commit_sha)
    test.assertIsNone(result.latest_commit_at)
    test.assertIsNone(result.source_timestamp)
    test.assertIsNone(result.raw_snapshot)
    test.assertIsNone(result.integrity_digest)
    test.assertIsNone(result.response_etag)


class GitHubLatestCommitCollectionTests(unittest.TestCase):
    def test_contract_is_frozen_and_one_patched_request_returns_available(self) -> None:
        result = _collect((200, _payload(), (("ETag", '"commit-etag"'),)))

        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.evidence_kind, EvidenceKind.LATEST_COMMIT_TIMESTAMP)
        self.assertEqual(result.commit_sha, SHA)
        self.assertEqual(
            result.latest_commit_at,
            datetime(2026, 8, 7, 14, 15, 16, tzinfo=timezone.utc),
        )
        self.assertEqual(result.source_timestamp, SOURCE_TIMESTAMP)
        self.assertEqual(result.response_etag, '"commit-etag"')
        with self.assertRaises(FrozenInstanceError):
            result.commit_sha = "changed"  # type: ignore[misc]

    def test_committer_date_is_used_without_author_fallback(self) -> None:
        result = _collect((200, _payload(author_date="2030-01-01T00:00:00Z"), ()))
        self.assertEqual(result.source_timestamp, SOURCE_TIMESTAMP)

        missing_committer = json.loads(_payload())
        del missing_committer[0]["commit"]["committer"]
        invalid = _collect(
            (200, json.dumps(missing_committer).encode("utf-8"), ())
        )
        self.assertEqual(invalid.error.category, "github_response_invalid")

    def test_exact_source_timestamp_raw_text_and_digest_are_preserved(self) -> None:
        raw = _payload(committer_date="2026-08-07T09:15:16-05:00", unrelated=True)
        result = _collect((200, raw, ()))

        self.assertEqual(result.source_timestamp, "2026-08-07T09:15:16-05:00")
        self.assertEqual(result.raw_snapshot, raw.decode("utf-8"))
        self.assertEqual(result.integrity_digest, hashlib.sha256(raw).hexdigest())
        self.assertIn('"message":"preserved"', result.raw_snapshot)

    def test_empty_array_is_unavailable_without_invented_evidence(self) -> None:
        result = _collect((200, b"[]", (("ETag", '"ignored"'),)))

        self.assertIs(result.outcome, GitHubCollectionOutcome.UNAVAILABLE)
        self.assertEqual(result.response_status, 200)
        self.assertEqual(result.error.category, "repository_has_no_commits")
        _assert_no_partial(self, result)

    def test_more_than_one_commit_and_invalid_top_level_shapes_fail(self) -> None:
        one = json.loads(_payload())[0]
        candidates = (
            json.dumps([one, one]).encode("utf-8"),
            b"{}",
            b"null",
            b'"commit"',
        )
        for raw in candidates:
            with self.subTest(raw=raw):
                result = _collect((200, raw, ()))
                self.assertEqual(result.error.category, "github_response_invalid")
                _assert_no_partial(self, result)

    def test_missing_or_wrongly_typed_commit_fields_fail(self) -> None:
        base = json.loads(_payload())[0]
        candidates = []
        for field in ("sha", "url", "commit"):
            candidate = dict(base)
            candidate.pop(field)
            candidates.append(candidate)
        candidates.extend((None, [], "commit"))
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = _collect(
                    (200, json.dumps([candidate]).encode("utf-8"), ())
                )
                self.assertEqual(result.error.category, "github_response_invalid")

    def test_commit_sha_is_strict_lowercase_40_hex(self) -> None:
        for sha in (True, "", "abc", SHA.upper(), "g" * 40, "0" * 64):
            with self.subTest(sha=sha):
                result = _collect((200, _payload(sha=sha), ()))
                self.assertEqual(result.error.category, "github_response_invalid")

    def test_commit_url_must_bind_repository_and_sha(self) -> None:
        invalid_urls = (
            "http://api.github.com/repos/example/reliable-library/commits/" + SHA,
            "https://github.com/example/reliable-library/commit/" + SHA,
            "https://api.github.com/repos/other/reliable-library/commits/" + SHA,
            "https://api.github.com/repos/example/reliable-library/commits/" + "1" * 40,
            "https://api.github.com/repos/example/reliable-library/commits/" + SHA + "?x=1",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                result = _collect((200, _payload(url=url), ()))
                self.assertEqual(result.error.category, "github_response_invalid")

        request = _input(repository_identity="github.com/Example/Reliable-Library")
        result = _collect(
            (
                200,
                _payload(
                    url="https://api.github.com/repos/example/reliable-library/commits/"
                    + SHA
                ),
                (),
            ),
            request,
        )
        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)

    def test_invalid_and_naive_timestamps_fail_without_coercion(self) -> None:
        for timestamp in (None, 0, "", "2026-08-07T14:15:16", "not-a-date"):
            with self.subTest(timestamp=timestamp):
                result = _collect((200, _payload(committer_date=timestamp), ()))
                self.assertEqual(result.error.category, "github_response_invalid")
                _assert_no_partial(self, result)

    def test_repository_404_and_http_409_are_distinct(self) -> None:
        unavailable = _collect((404, None, (("ETag", '"secret"'),)))
        rejected = _collect((409, None, ()))

        self.assertIs(unavailable.outcome, GitHubCollectionOutcome.UNAVAILABLE)
        self.assertEqual(
            unavailable.error.category, "repository_not_publicly_available"
        )
        self.assertIs(
            rejected.outcome, GitHubCollectionOutcome.FAILED_NONRETRYABLE
        )
        self.assertEqual(rejected.error.category, "github_request_rejected")
        _assert_no_partial(self, unavailable)
        _assert_no_partial(self, rejected)

    def test_rate_limit_authorization_and_server_failures_are_classified(self) -> None:
        cases = (
            (429, (("Retry-After", "60"),), "github_rate_limited", True),
            (403, (("X-RateLimit-Remaining", "0"),), "github_rate_limited", True),
            (401, (), "github_authorization_failed", False),
            (403, (), "github_authorization_failed", False),
            (503, (("Retry-After", "120"),), "github_server_error", True),
        )
        for status, headers, category, retryable in cases:
            with self.subTest(status=status, category=category):
                result = _collect((status, None, headers))
                self.assertEqual(result.error.category, category)
                self.assertIs(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_RETRYABLE
                    if retryable
                    else GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                _assert_no_partial(self, result)

    def test_timeout_and_connectivity_failures_are_safe(self) -> None:
        cases = (
            (socket.timeout("private timeout"), "github_timeout"),
            (URLError(socket.timeout("private")), "github_timeout"),
            (ConnectionError("credential"), "github_connectivity_failure"),
            (URLError("private endpoint"), "github_connectivity_failure"),
        )
        for failure, category in cases:
            with self.subTest(category=category):
                with patch(
                    "engineering_due_diligence.github._get_public_github_repository",
                    side_effect=failure,
                ) as transport:
                    result = collect_public_github_latest_commit(_input())
                transport.assert_called_once_with(SOURCE_IDENTITY)
                self.assertEqual(result.error.category, category)
                self.assertNotIn("private", result.error.message)
                _assert_no_partial(self, result)

    def test_malformed_success_responses_fail_safely(self) -> None:
        for body in (b"\xff", b"[", None, "[]"):
            with self.subTest(body=body):
                result = _collect((200, body, (("Authorization", "secret"),)))
                self.assertEqual(result.error.category, "github_response_invalid")
                _assert_no_partial(self, result)

    def test_contradictory_direct_result_construction_fails(self) -> None:
        available = _collect((200, _payload(), ()))
        with self.assertRaises(ValueError):
            replace(available, commit_sha=None)
        with self.assertRaises(ValueError):
            replace(available, latest_commit_at=datetime.now())


if __name__ == "__main__":
    unittest.main()
