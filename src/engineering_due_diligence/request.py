"""Pure transient validation for one submitted assessment request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlsplit

from .models import (
    AssessmentContext,
    Criticality,
    Environment,
    RiskTolerance,
)


REQUEST_DEFINITION_VERSION = "assessment-request.v1"

_VALID_STATUS = "valid"
_INVALID_STATUS = "invalid"
_GITHUB_PATH_PATTERN = re.compile(
    r"/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/?\Z"
)


@dataclass(frozen=True)
class AssessmentRequestInput:
    """Immutable submitted values validated only by the public boundary."""

    assessment_id: str
    submitted_repository_locator: str
    intended_use: str
    environment: Environment
    criticality: Criticality
    expected_lifetime_days: int
    risk_tolerance: RiskTolerance
    submitted_by_actor_id: str
    responsible_reviewer_actor_id: str
    submitted_at: datetime
    request_definition_version: str


@dataclass(frozen=True)
class AssessmentRequestValidationError:
    """One deterministic field-level request validation error."""

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class AssessmentRequestValidationResult:
    """A complete valid or invalid transient request-validation result."""

    request: AssessmentRequestInput
    validation_status: str
    normalized_repository_identity: Optional[str]
    context: Optional[AssessmentContext]
    validation_errors: Tuple[AssessmentRequestValidationError, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, AssessmentRequestInput):
            raise ValueError("request must be an AssessmentRequestInput")
        if not isinstance(self.validation_errors, tuple) or not all(
            isinstance(error, AssessmentRequestValidationError)
            for error in self.validation_errors
        ):
            raise ValueError(
                "validation_errors must be a tuple of validation errors"
            )

        if self.validation_status == _VALID_STATUS:
            if (
                type(self.normalized_repository_identity) is not str
                or not self.normalized_repository_identity
                or not isinstance(self.context, AssessmentContext)
                or self.validation_errors
            ):
                raise ValueError(
                    "valid result requires identity, context, and no errors"
                )
            return

        if self.validation_status == _INVALID_STATUS:
            if (
                self.normalized_repository_identity is not None
                or self.context is not None
                or not self.validation_errors
            ):
                raise ValueError(
                    "invalid result requires errors and no identity or context"
                )
            return

        raise ValueError("validation_status must be valid or invalid")


def _validation_error(
    field: str, code: str
) -> AssessmentRequestValidationError:
    if code == "invalid_type":
        message = "{} has an invalid type.".format(field)
    elif code == "required":
        message = "{} must not be empty.".format(field)
    elif code == "surrounding_whitespace":
        message = (
            "{} must not have leading or trailing whitespace.".format(field)
        )
    elif code == "unsupported_https_github_locator":
        message = (
            "submitted_repository_locator must be an HTTPS github.com "
            "owner/repository URL."
        )
    elif code == "invalid_environment":
        message = "environment must be an Environment."
    elif code == "invalid_criticality":
        message = "criticality must be a Criticality."
    elif code == "must_be_positive":
        message = "expected_lifetime_days must be a positive integer."
    elif code == "invalid_risk_tolerance":
        message = "risk_tolerance must be a RiskTolerance."
    elif code == "timezone_aware_required":
        message = "submitted_at must be timezone-aware."
    elif code == "unsupported_version":
        message = "request_definition_version is not supported."
    else:
        raise ValueError("unknown request validation error code")
    return AssessmentRequestValidationError(
        field=field,
        code=code,
        message=message,
    )


def _required_text_error(
    field: str, value: object
) -> Optional[AssessmentRequestValidationError]:
    if type(value) is not str:
        return _validation_error(field, "invalid_type")
    if not value.strip():
        return _validation_error(field, "required")
    if value != value.strip():
        return _validation_error(field, "surrounding_whitespace")
    return None


def _normalize_github_locator(locator: str) -> Optional[str]:
    if (
        not locator.isascii()
        or not locator.isprintable()
        or any(character.isspace() for character in locator)
        or "?" in locator
        or "#" in locator
    ):
        return None
    try:
        parsed = urlsplit(locator)
    except ValueError:
        return None

    if parsed.scheme.casefold() != "https":
        return None
    if parsed.netloc.casefold() != "github.com":
        return None
    if parsed.query or parsed.fragment:
        return None

    path_match = _GITHUB_PATH_PATTERN.fullmatch(parsed.path)
    if path_match is None:
        return None
    owner, repository = path_match.groups()
    if owner in (".", "..") or repository in (".", ".."):
        return None
    if repository.casefold().endswith(".git"):
        return None
    return "github.com/{}/{}".format(owner, repository)


def _submitted_at_error(
    value: object,
) -> Optional[AssessmentRequestValidationError]:
    if not isinstance(value, datetime):
        return _validation_error("submitted_at", "invalid_type")
    try:
        is_aware = value.tzinfo is not None and value.utcoffset() is not None
    except Exception:
        is_aware = False
    if not is_aware:
        return _validation_error(
            "submitted_at", "timezone_aware_required"
        )
    return None


def validate_assessment_request(
    request: AssessmentRequestInput,
) -> AssessmentRequestValidationResult:
    """Validate one submission and return all expected errors in fixed order."""

    errors = []
    normalized_repository_identity: Optional[str] = None

    error = _required_text_error("assessment_id", request.assessment_id)
    if error is not None:
        errors.append(error)

    error = _required_text_error(
        "submitted_repository_locator",
        request.submitted_repository_locator,
    )
    if error is not None:
        errors.append(error)
    else:
        normalized_repository_identity = _normalize_github_locator(
            request.submitted_repository_locator
        )
        if normalized_repository_identity is None:
            errors.append(
                _validation_error(
                    "submitted_repository_locator",
                    "unsupported_https_github_locator",
                )
            )

    error = _required_text_error("intended_use", request.intended_use)
    if error is not None:
        errors.append(error)

    if not isinstance(request.environment, Environment):
        errors.append(
            _validation_error("environment", "invalid_environment")
        )

    if not isinstance(request.criticality, Criticality):
        errors.append(
            _validation_error("criticality", "invalid_criticality")
        )

    if type(request.expected_lifetime_days) is not int:
        errors.append(
            _validation_error("expected_lifetime_days", "invalid_type")
        )
    elif request.expected_lifetime_days <= 0:
        errors.append(
            _validation_error(
                "expected_lifetime_days", "must_be_positive"
            )
        )

    if not isinstance(request.risk_tolerance, RiskTolerance):
        errors.append(
            _validation_error(
                "risk_tolerance", "invalid_risk_tolerance"
            )
        )

    error = _required_text_error(
        "submitted_by_actor_id", request.submitted_by_actor_id
    )
    if error is not None:
        errors.append(error)

    error = _required_text_error(
        "responsible_reviewer_actor_id",
        request.responsible_reviewer_actor_id,
    )
    if error is not None:
        errors.append(error)

    error = _submitted_at_error(request.submitted_at)
    if error is not None:
        errors.append(error)

    error = _required_text_error(
        "request_definition_version", request.request_definition_version
    )
    if error is not None:
        errors.append(error)
    elif request.request_definition_version != REQUEST_DEFINITION_VERSION:
        errors.append(
            _validation_error(
                "request_definition_version", "unsupported_version"
            )
        )

    validation_errors = tuple(errors)
    if validation_errors:
        return AssessmentRequestValidationResult(
            request=request,
            validation_status=_INVALID_STATUS,
            normalized_repository_identity=None,
            context=None,
            validation_errors=validation_errors,
        )

    context = AssessmentContext(
        assessment_id=request.assessment_id,
        repository_identity=normalized_repository_identity,
        intended_use=request.intended_use,
        environment=request.environment,
        criticality=request.criticality,
        expected_lifetime_days=request.expected_lifetime_days,
        risk_tolerance=request.risk_tolerance,
    )
    return AssessmentRequestValidationResult(
        request=request,
        validation_status=_VALID_STATUS,
        normalized_repository_identity=normalized_repository_identity,
        context=context,
        validation_errors=(),
    )
