"""Focused tests for the transient assessment-request validation boundary."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone, tzinfo

from engineering_due_diligence.models import (
    AssessmentContext,
    Criticality,
    Environment,
    RiskTolerance,
)
from engineering_due_diligence.request import (
    REQUEST_DEFINITION_VERSION,
    AssessmentRequestInput,
    AssessmentRequestValidationError,
    AssessmentRequestValidationResult,
    validate_assessment_request,
)


SUBMITTED_AT = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _valid_request(**changes: object) -> AssessmentRequestInput:
    request = AssessmentRequestInput(
        assessment_id="assessment-day-5",
        submitted_repository_locator=(
            "https://github.com/example/reliable-library"
        ),
        intended_use="Critical production authentication dependency",
        environment=Environment.PRODUCTION,
        criticality=Criticality.CRITICAL,
        expected_lifetime_days=1_825,
        risk_tolerance=RiskTolerance.LOW,
        submitted_by_actor_id="actor-submitter",
        responsible_reviewer_actor_id="actor-reviewer",
        submitted_at=SUBMITTED_AT,
        request_definition_version=REQUEST_DEFINITION_VERSION,
    )
    return replace(request, **changes)


def _field_codes(
    result: AssessmentRequestValidationResult,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (error.field, error.code) for error in result.validation_errors
    )


class _MissingOffsetTimezone(tzinfo):
    def utcoffset(self, value: datetime | None) -> None:
        return None

    def dst(self, value: datetime | None) -> None:
        return None

    def tzname(self, value: datetime | None) -> str:
        return "missing-offset"


class _RaisingOffsetTimezone(tzinfo):
    def utcoffset(self, value: datetime | None) -> timedelta:
        raise ValueError("unusable timezone")

    def dst(self, value: datetime | None) -> None:
        return None

    def tzname(self, value: datetime | None) -> str:
        return "raising-offset"


class AssessmentRequestValidationTests(unittest.TestCase):
    def test_request_validation_contracts_are_frozen(self) -> None:
        invalid_request = _valid_request(assessment_id=None)
        invalid_result = validate_assessment_request(invalid_request)
        error = invalid_result.validation_errors[0]

        self.assertEqual(invalid_result.validation_status, "invalid")
        self.assertIs(invalid_result.request, invalid_request)
        self.assertIsInstance(error, AssessmentRequestValidationError)
        self.assertIsInstance(invalid_result.validation_errors, tuple)

        with self.assertRaises(FrozenInstanceError):
            invalid_request.assessment_id = "replacement"
        with self.assertRaises(FrozenInstanceError):
            error.code = "replacement"
        with self.assertRaises(FrozenInstanceError):
            invalid_result.validation_status = "valid"

    def test_valid_request_returns_preserved_input_context_and_canonical_identity(
        self,
    ) -> None:
        request = _valid_request()
        expected_context = AssessmentContext(
            assessment_id=request.assessment_id,
            repository_identity="github.com/example/reliable-library",
            intended_use=request.intended_use,
            environment=request.environment,
            criticality=request.criticality,
            expected_lifetime_days=request.expected_lifetime_days,
            risk_tolerance=request.risk_tolerance,
        )

        result = validate_assessment_request(request)

        self.assertEqual(result.validation_status, "valid")
        self.assertIs(result.request, request)
        self.assertEqual(
            result.normalized_repository_identity,
            "github.com/example/reliable-library",
        )
        self.assertEqual(result.context, expected_context)
        self.assertEqual(result.validation_errors, ())

    def test_aware_offset_submitted_at_is_preserved_exactly(self) -> None:
        supplied_timezone = timezone(timedelta(hours=5, minutes=30))
        supplied_at = SUBMITTED_AT.astimezone(supplied_timezone)
        request = _valid_request(submitted_at=supplied_at)

        result = validate_assessment_request(request)

        self.assertEqual(result.validation_status, "valid")
        self.assertIs(result.request, request)
        self.assertIs(result.request.submitted_at, supplied_at)
        self.assertIs(result.request.submitted_at.tzinfo, supplied_timezone)
        self.assertEqual(
            result.request.submitted_at.isoformat(), supplied_at.isoformat()
        )

    def test_supported_locator_variants_follow_the_locked_normalization_rules(
        self,
    ) -> None:
        variants = (
            (
                "https://github.com/example/reliable-library",
                "github.com/example/reliable-library",
            ),
            (
                "HTTPS://GITHUB.COM/Example/Reliable-Library",
                "github.com/Example/Reliable-Library",
            ),
            (
                "https://github.com/example/reliable-library/",
                "github.com/example/reliable-library",
            ),
        )

        for locator, expected_identity in variants:
            with self.subTest(locator=locator):
                result = validate_assessment_request(
                    _valid_request(submitted_repository_locator=locator)
                )

                self.assertEqual(result.validation_status, "valid")
                self.assertEqual(
                    result.normalized_repository_identity,
                    expected_identity,
                )
                self.assertEqual(
                    result.context.repository_identity,
                    expected_identity,
                )

    def test_unsupported_locator_shapes_return_one_locator_error(self) -> None:
        unsupported_locators = (
            "http://github.com/example/reliable-library",
            "https://gitlab.com/example/reliable-library",
            "https://www.github.com/example/reliable-library",
            "https://user@github.com/example/reliable-library",
            "https://github.com:443/example/reliable-library",
            "https://github.com/example/reliable-library?tab=readme",
            "https://github.com/example/reliable-library?",
            "https://github.com/example/reliable-library#readme",
            "https://github.com/example/reliable-library#",
            "https://github.com//reliable-library",
            "https://github.com/example/",
            "https://github.com/example/reliable-library/issues",
            "https://github.com/example/reliable-library//",
            "https://github.com/example/reliable%2Flibrary",
            "https://github.com/exämple/reliable-library",
            "https://github.com/example/reliable library",
            "https://git\nhub.com/example/reliable-library",
            "\x00https://github.com/example/reliable-library",
            "https://github.com/./reliable-library",
            "https://github.com/example/..",
            "https://github.com/example!/reliable-library",
            "https://github.com/example/reliable-library.git",
            "https://github.com/example/reliable-library.GIT",
        )

        for locator in unsupported_locators:
            with self.subTest(locator=locator):
                result = validate_assessment_request(
                    _valid_request(submitted_repository_locator=locator)
                )

                self.assertEqual(result.validation_status, "invalid")
                self.assertEqual(
                    _field_codes(result),
                    ((
                        "submitted_repository_locator",
                        "unsupported_https_github_locator",
                    ),),
                )
                self.assertIsNone(result.normalized_repository_identity)
                self.assertIsNone(result.context)

    def test_required_text_errors_follow_locked_field_order(self) -> None:
        request = _valid_request(
            assessment_id=None,
            submitted_repository_locator=" ",
            intended_use=" intended use ",
            submitted_by_actor_id="",
            responsible_reviewer_actor_id=7,
            request_definition_version=" assessment-request.v1",
        )

        result = validate_assessment_request(request)

        self.assertEqual(
            _field_codes(result),
            (
                ("assessment_id", "invalid_type"),
                ("submitted_repository_locator", "required"),
                ("intended_use", "surrounding_whitespace"),
                ("submitted_by_actor_id", "required"),
                ("responsible_reviewer_actor_id", "invalid_type"),
                ("request_definition_version", "surrounding_whitespace"),
            ),
        )

    def test_invalid_context_values_return_ordered_validation_data(self) -> None:
        invalid_types = _valid_request(
            environment="production",
            criticality="critical",
            expected_lifetime_days=True,
            risk_tolerance="low",
        )

        result = validate_assessment_request(invalid_types)

        self.assertEqual(
            _field_codes(result),
            (
                ("environment", "invalid_environment"),
                ("criticality", "invalid_criticality"),
                ("expected_lifetime_days", "invalid_type"),
                ("risk_tolerance", "invalid_risk_tolerance"),
            ),
        )
        self.assertIsNone(result.normalized_repository_identity)
        self.assertIsNone(result.context)

        for lifetime in (0, -1):
            with self.subTest(lifetime=lifetime):
                lifetime_result = validate_assessment_request(
                    _valid_request(expected_lifetime_days=lifetime)
                )
                self.assertEqual(
                    _field_codes(lifetime_result),
                    (("expected_lifetime_days", "must_be_positive"),),
                )

    def test_invalid_submitted_at_returns_validation_data(self) -> None:
        values = (
            ("not-datetime", object(), "invalid_type"),
            (
                "naive",
                SUBMITTED_AT.replace(tzinfo=None),
                "timezone_aware_required",
            ),
            (
                "missing-offset",
                SUBMITTED_AT.replace(tzinfo=_MissingOffsetTimezone()),
                "timezone_aware_required",
            ),
            (
                "raising-offset",
                SUBMITTED_AT.replace(tzinfo=_RaisingOffsetTimezone()),
                "timezone_aware_required",
            ),
        )

        for name, submitted_at, expected_code in values:
            with self.subTest(name=name):
                result = validate_assessment_request(
                    _valid_request(submitted_at=submitted_at)
                )

                self.assertEqual(
                    _field_codes(result),
                    (("submitted_at", expected_code),),
                )
                self.assertIsNone(result.normalized_repository_identity)
                self.assertIsNone(result.context)

    def test_unsupported_request_definition_version_is_invalid(self) -> None:
        result = validate_assessment_request(
            _valid_request(request_definition_version="assessment-request.v2")
        )

        self.assertEqual(result.validation_status, "invalid")
        self.assertEqual(len(result.validation_errors), 1)
        error = result.validation_errors[0]
        self.assertEqual(error.field, "request_definition_version")
        self.assertEqual(error.code, "unsupported_version")
        self.assertEqual(
            error.message,
            "request_definition_version is not supported.",
        )
        self.assertIsNone(result.normalized_repository_identity)
        self.assertIsNone(result.context)

    def test_each_field_emits_only_its_first_precedence_error(self) -> None:
        request = _valid_request(
            assessment_id=object(),
            submitted_repository_locator="",
            intended_use=" ",
            submitted_by_actor_id=None,
            responsible_reviewer_actor_id="",
            request_definition_version="",
        )

        result = validate_assessment_request(request)

        self.assertEqual(
            _field_codes(result),
            (
                ("assessment_id", "invalid_type"),
                ("submitted_repository_locator", "required"),
                ("intended_use", "required"),
                ("submitted_by_actor_id", "invalid_type"),
                ("responsible_reviewer_actor_id", "required"),
                ("request_definition_version", "required"),
            ),
        )
        fields = tuple(error.field for error in result.validation_errors)
        self.assertEqual(len(fields), len(set(fields)))

    def test_mixed_invalid_request_returns_complete_stably_ordered_errors(
        self,
    ) -> None:
        request = _valid_request(
            assessment_id=None,
            submitted_repository_locator=(
                "ftp://github.com/example/reliable-library"
            ),
            intended_use="",
            environment="production",
            criticality="critical",
            expected_lifetime_days=0,
            risk_tolerance="low",
            submitted_by_actor_id=" actor-submitter ",
            responsible_reviewer_actor_id=7,
            submitted_at=SUBMITTED_AT.replace(tzinfo=None),
            request_definition_version="assessment-request.v2",
        )

        result = validate_assessment_request(request)

        self.assertIs(result.request, request)
        self.assertEqual(result.validation_status, "invalid")
        self.assertEqual(
            _field_codes(result),
            (
                ("assessment_id", "invalid_type"),
                (
                    "submitted_repository_locator",
                    "unsupported_https_github_locator",
                ),
                ("intended_use", "required"),
                ("environment", "invalid_environment"),
                ("criticality", "invalid_criticality"),
                ("expected_lifetime_days", "must_be_positive"),
                ("risk_tolerance", "invalid_risk_tolerance"),
                ("submitted_by_actor_id", "surrounding_whitespace"),
                ("responsible_reviewer_actor_id", "invalid_type"),
                ("submitted_at", "timezone_aware_required"),
                ("request_definition_version", "unsupported_version"),
            ),
        )
        self.assertEqual(len(result.validation_errors), 11)
        self.assertIsNone(result.normalized_repository_identity)
        self.assertIsNone(result.context)

    def test_expected_invalid_input_never_returns_a_partial_context(self) -> None:
        invalid_changes = (
            {
                "submitted_repository_locator": (
                    "http://github.com/example/reliable-library"
                )
            },
            {"request_definition_version": "assessment-request.v2"},
            {"intended_use": ""},
            {"environment": "production"},
        )

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                result = validate_assessment_request(
                    _valid_request(**changes)
                )

                self.assertEqual(result.validation_status, "invalid")
                self.assertGreaterEqual(len(result.validation_errors), 1)
                self.assertIsNone(result.normalized_repository_identity)
                self.assertIsNone(result.context)

    def test_repeated_validation_is_deterministic(self) -> None:
        valid_request = _valid_request()
        valid_snapshot = replace(valid_request)
        invalid_request = _valid_request(
            submitted_repository_locator="http://github.com/example/repository",
            intended_use="",
            submitted_at=SUBMITTED_AT.replace(tzinfo=None),
        )
        invalid_snapshot = replace(invalid_request)

        first_valid = validate_assessment_request(valid_request)
        second_valid = validate_assessment_request(valid_request)
        first_invalid = validate_assessment_request(invalid_request)
        second_invalid = validate_assessment_request(invalid_request)

        self.assertEqual(first_valid, second_valid)
        self.assertEqual(first_invalid, second_invalid)
        self.assertEqual(
            first_invalid.validation_errors,
            second_invalid.validation_errors,
        )
        self.assertEqual(valid_request, valid_snapshot)
        self.assertEqual(invalid_request, invalid_snapshot)

    def test_validation_result_rejects_contradictory_direct_construction(
        self,
    ) -> None:
        request = _valid_request()
        valid_result = validate_assessment_request(request)
        context = valid_result.context
        error = AssessmentRequestValidationError(
            field="assessment_id",
            code="required",
            message="assessment_id must not be empty.",
        )
        cases = (
            (
                "unknown-status",
                "pending",
                valid_result.normalized_repository_identity,
                context,
                (),
            ),
            ("valid-missing-identity", "valid", None, context, ()),
            (
                "valid-missing-context",
                "valid",
                valid_result.normalized_repository_identity,
                None,
                (),
            ),
            (
                "valid-with-errors",
                "valid",
                valid_result.normalized_repository_identity,
                context,
                (error,),
            ),
            ("invalid-with-identity", "invalid", "github.com/a/b", None, (error,)),
            ("invalid-with-context", "invalid", None, context, (error,)),
            ("invalid-without-errors", "invalid", None, None, ()),
        )

        for name, status, identity, supplied_context, errors in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    AssessmentRequestValidationResult(
                        request=request,
                        validation_status=status,
                        normalized_repository_identity=identity,
                        context=supplied_context,
                        validation_errors=errors,
                    )


if __name__ == "__main__":
    unittest.main()
