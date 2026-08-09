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
    GitHubRepositoryMetadataCollectionError,
    GitHubRepositoryMetadataCollectionInput,
    GitHubSecurityPolicyPresenceCollectionResult,
    GitHubSecurityPolicySourceObservation,
    collect_public_github_security_policy_presence,
)
from engineering_due_diligence.models import EvidenceKind


REPOSITORY_URL = "https://api.github.com/repos/Owner/Repository"
POLICY_SHA = "a" * 40


def _request(repository_identity="github.com/Owner/Repository"):
    return GitHubRepositoryMetadataCollectionInput(
        assessment_id="assessment-11",
        repository_identity=repository_identity,
        collection_attempt_id="security-attempt-1",
        attempt_number=4,
        attempted_at=datetime(2026, 8, 8, 14, 0, tzinfo=timezone.utc),
    )


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _repository_response(full_name="Owner/Repository", repository_id=123):
    return (
        200,
        _json_bytes(
            {"id": repository_id, "full_name": full_name, "extra": [1, 2]}
        ),
        (("ETag", '"repository-etag"'),),
    )


def _policy_url(repository="Repository", path=".github/SECURITY.md"):
    return "https://api.github.com/repos/Owner/{}/contents/{}".format(
        repository, path
    )


def _policy_response(repository="Repository", path=".github/SECURITY.md"):
    url = _policy_url(repository, path)
    return (
        200,
        _json_bytes(
            {
                "type": "file",
                "name": "SECURITY.md",
                "path": path,
                "size": 42,
                "sha": POLICY_SHA,
                "url": url,
                "content": "cG9saWN5",
                "unrelated": {"accepted": True},
            }
        ),
        (("ETag", '"policy-etag"'),),
    )


NOT_FOUND = (404, None, ())


class GitHubSecurityPolicyCollectionTests(unittest.TestCase):
    def _collect(self, responses, request=None):
        with patch(
            "engineering_due_diligence.github."
            "_get_public_github_repository",
            side_effect=responses,
        ) as transport:
            result = collect_public_github_security_policy_presence(
                request or _request()
            )
        return result, transport

    def test_first_local_policy_is_true_and_contracts_are_frozen(self):
        result, transport = self._collect(
            [_repository_response(), _policy_response()]
        )
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in transport.call_args_list],
            [REPOSITORY_URL, _policy_url()],
        )
        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.evidence_kind, EvidenceKind.SECURITY_POLICY_PRESENT)
        self.assertIs(result.security_policy_present, True)
        self.assertEqual(result.policy_scope, "repository_local")
        self.assertEqual(result.policy_path, ".github/SECURITY.md")
        self.assertEqual(result.policy_blob_sha, POLICY_SHA)
        self.assertTrue(
            all(
                type(item) is GitHubSecurityPolicySourceObservation
                for item in result.observations
            )
        )
        with self.assertRaises(FrozenInstanceError):
            result.security_policy_present = False
        with self.assertRaises(FrozenInstanceError):
            result.observations[0].role = "changed"

    def test_precedence_continues_after_candidate_404_and_stops_at_root(self):
        result, transport = self._collect(
            [
                _repository_response(),
                NOT_FOUND,
                _policy_response(path="SECURITY.md"),
            ]
        )
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(
            tuple(item.role for item in result.observations),
            ("repository", "target_dotgithub", "target_root"),
        )
        self.assertEqual(result.policy_path, "SECURITY.md")

    def test_inherited_policy_is_effective_only_after_all_local_404s(self):
        result, transport = self._collect(
            [
                _repository_response(),
                NOT_FOUND,
                NOT_FOUND,
                NOT_FOUND,
                _policy_response(repository=".github"),
            ]
        )
        self.assertEqual(transport.call_count, 5)
        self.assertIs(result.security_policy_present, True)
        self.assertEqual(result.policy_scope, "inherited_default")
        self.assertEqual(result.observations[-1].role, "default_dotgithub")

    def test_all_six_candidate_404s_produce_available_false(self):
        result, transport = self._collect(
            [_repository_response()] + [NOT_FOUND] * 6
        )
        self.assertEqual(transport.call_count, 7)
        self.assertIs(result.outcome, GitHubCollectionOutcome.AVAILABLE)
        self.assertIs(result.security_policy_present, False)
        self.assertEqual(result.response_status, 404)
        self.assertIsNone(result.error)
        self.assertIsNone(result.policy_scope)
        self.assertTrue(
            all(item.error is None for item in result.observations[1:])
        )

    def test_assessed_dotgithub_repository_deduplicates_default_probes(self):
        request = _request("github.com/Owner/.github")
        result, transport = self._collect(
            [_repository_response("Owner/.github")] + [NOT_FOUND] * 3,
            request,
        )
        self.assertEqual(transport.call_count, 4)
        self.assertIs(result.security_policy_present, False)
        self.assertEqual(
            tuple(item.role for item in result.observations[1:]),
            ("target_dotgithub", "target_root", "target_docs"),
        )

    def test_assessed_repository_404_is_unavailable_without_policy_probes(self):
        result, transport = self._collect([NOT_FOUND])
        self.assertEqual(transport.call_count, 1)
        self.assertIs(result.outcome, GitHubCollectionOutcome.UNAVAILABLE)
        self.assertIsNone(result.security_policy_present)
        self.assertEqual(result.error.category, "repository_not_publicly_available")
        self.assertEqual(len(result.observations), 1)

    def test_repository_identity_payload_is_strict_and_bound(self):
        invalid_payloads = (
            {"id": True, "full_name": "Owner/Repository"},
            {"id": 1, "full_name": "Owner/Other"},
            {"id": "1", "full_name": "Owner/Repository"},
            ["not-an-object"],
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                result, transport = self._collect(
                    [(200, _json_bytes(payload), ())]
                )
                self.assertEqual(transport.call_count, 1)
                self.assertIs(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                self.assertEqual(result.error.category, "github_response_invalid")
                self.assertIsNone(result.security_policy_present)

    def test_policy_payload_types_paths_sha_and_url_are_strict(self):
        valid = json.loads(_policy_response()[1])
        invalid_payloads = []
        for key, value in (
            ("type", "dir"),
            ("name", "security.md"),
            ("path", "SECURITY.md"),
            ("size", True),
            ("size", -1),
            ("sha", "A" * 40),
            ("sha", "a" * 39),
            ("url", _policy_url(path="SECURITY.md")),
            ("url", "https://[::"),
        ):
            payload = dict(valid)
            payload[key] = value
            invalid_payloads.append(payload)
        invalid_payloads.extend(([], {"type": "file"}))
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                result, transport = self._collect(
                    [_repository_response(), (200, _json_bytes(payload), ())]
                )
                self.assertEqual(transport.call_count, 2)
                self.assertIs(
                    result.outcome,
                    GitHubCollectionOutcome.FAILED_NONRETRYABLE,
                )
                self.assertEqual(result.error.category, "github_response_invalid")
                self.assertIsNone(result.security_policy_present)

    def test_exact_successful_responses_digests_etags_and_unrelated_fields_remain(self):
        repository = _repository_response()
        policy = _policy_response()
        result, transport = self._collect(
            [repository, policy],
            request=_request("github.com/owner/repository"),
        )
        self.assertEqual(
            [call.args[0] for call in transport.call_args_list],
            [
                "https://api.github.com/repos/owner/repository",
                "https://api.github.com/repos/owner/repository/contents/"
                ".github/SECURITY.md",
            ],
        )
        for observation, response in zip(result.observations, (repository, policy)):
            expected_text = response[1].decode("utf-8")
            self.assertEqual(observation.raw_response_bytes, response[1])
            self.assertEqual(observation.raw_snapshot, expected_text)
            self.assertEqual(
                observation.integrity_digest,
                hashlib.sha256(response[1]).hexdigest(),
            )
        self.assertIn("\"extra\"", result.observations[0].raw_snapshot)
        self.assertIn("\"unrelated\"", result.observations[1].raw_snapshot)
        self.assertEqual(result.observations[0].response_etag, '"repository-etag"')
        self.assertEqual(result.observations[1].response_etag, '"policy-etag"')

    def test_rate_limit_authorization_server_and_unexpected_status_fail_closed(self):
        cases = (
            ((429, None, (("Retry-After", "5"),)), "github_rate_limited", GitHubCollectionOutcome.FAILED_RETRYABLE),
            ((403, None, ()), "github_authorization_failed", GitHubCollectionOutcome.FAILED_NONRETRYABLE),
            ((503, None, ()), "github_server_error", GitHubCollectionOutcome.FAILED_RETRYABLE),
            ((302, None, ()), "github_unexpected_status", GitHubCollectionOutcome.FAILED_NONRETRYABLE),
        )
        for response, category, outcome in cases:
            with self.subTest(category=category):
                result, transport = self._collect(
                    [_repository_response(), NOT_FOUND, response]
                )
                self.assertEqual(transport.call_count, 3)
                self.assertIs(result.outcome, outcome)
                self.assertEqual(result.error.category, category)
                self.assertIsNone(result.security_policy_present)
                self.assertEqual(len(result.observations), 3)

    def test_timeout_and_connectivity_failures_are_safe_and_stop_search(self):
        for exception, category in (
            (socket.timeout("secret timeout"), "github_timeout"),
            (URLError("secret connection"), "github_connectivity_failure"),
        ):
            with self.subTest(category=category):
                result, transport = self._collect(
                    [_repository_response(), NOT_FOUND, exception]
                )
                self.assertEqual(transport.call_count, 3)
                self.assertIs(
                    result.outcome, GitHubCollectionOutcome.FAILED_RETRYABLE
                )
                self.assertEqual(result.error.category, category)
                self.assertNotIn("secret", result.error.message)
                self.assertIsNone(result.observations[-1].raw_snapshot)

    def test_malformed_utf8_and_json_preserve_only_safe_success_data(self):
        malformed_cases = (b"\xff", b"not-json")
        for body in malformed_cases:
            with self.subTest(body=body):
                result, _ = self._collect(
                    [_repository_response(), (200, body, ())]
                )
                self.assertEqual(result.error.category, "github_response_invalid")
                self.assertIsNone(result.security_policy_present)
                self.assertEqual(
                    result.observations[-1].raw_response_bytes, body
                )
                self.assertEqual(
                    result.observations[-1].integrity_digest,
                    hashlib.sha256(body).hexdigest(),
                )
                if body == b"not-json":
                    self.assertEqual(result.observations[-1].raw_snapshot, "not-json")
                else:
                    self.assertIsNone(result.observations[-1].raw_snapshot)

    def test_result_invariants_reject_partial_or_reordered_construction(self):
        result, _ = self._collect(
            [_repository_response(), NOT_FOUND, _policy_response(path="SECURITY.md")]
        )
        with self.assertRaises(ValueError):
            replace(result, security_policy_present=False)
        with self.assertRaises(ValueError):
            replace(result, observations=tuple(reversed(result.observations)))
        with self.assertRaises(ValueError):
            replace(result, policy_blob_sha="b" * 40)
        with self.assertRaises(ValueError):
            replace(
                result.observations[-1],
                source_object_id=None,
                response_etag=None,
                error=GitHubRepositoryMetadataCollectionError(
                    category="github_server_error",
                    retryability="retryable",
                    message=(
                        "GitHub could not complete the repository metadata "
                        "request."
                    ),
                ),
            )
        with self.assertRaises(ValueError):
            GitHubSecurityPolicyPresenceCollectionResult(
                **{
                    **result.__dict__,
                    "observations": result.observations[:-1],
                }
            )


if __name__ == "__main__":
    unittest.main()
