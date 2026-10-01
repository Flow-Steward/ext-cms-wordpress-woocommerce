"""Stable, safe error vocabulary for the WordPress and WooCommerce extension.

Every failure the runtime can produce maps to exactly one of these codes. No
message carries a credential, an authorization header, a secret reference, or
unbounded upstream content: upstream text is never echoed, only classified.
"""

from __future__ import annotations

from collections.abc import Mapping

INVALID_PAYLOAD = "invalid_payload"
INVALID_CONFIGURATION = "invalid_configuration"
INVALID_CONNECTION = "invalid_connection"
WOOCOMMERCE_CREDENTIALS_INCOMPLETE = "woocommerce_credentials_incomplete"
WOOCOMMERCE_NOT_CONFIGURED = "woocommerce_not_configured"
UNSUPPORTED_OPERATION = "unsupported_operation"
AUTHENTICATION_FAILED = "authentication_failed"
AUTHORIZATION_FAILED = "authorization_failed"
NOT_FOUND = "not_found"
RATE_LIMITED = "rate_limited"
UPSTREAM_VALIDATION_FAILED = "upstream_validation_failed"
UPSTREAM_FAILURE = "upstream_failure"
INVALID_JSON_RESPONSE = "invalid_json_response"
RESPONSE_TOO_LARGE = "response_too_large"
TIMEOUT = "timeout"
CONNECTION_FAILED = "connection_failed"
REDIRECT_REJECTED = "redirect_rejected"
BLOCKED_ADDRESS = "blocked_address"
ARTIFACT_INPUT_UNAVAILABLE = "artifact_input_unavailable"
ARTIFACT_OUTPUT_UNAVAILABLE = "artifact_output_unavailable"
TIMEOUT_UNKNOWN = "timeout_unknown"
INTERNAL_ERROR = "internal_error"

SAFE_ERROR_CODES: tuple[str, ...] = (
    INVALID_PAYLOAD,
    INVALID_CONFIGURATION,
    INVALID_CONNECTION,
    WOOCOMMERCE_CREDENTIALS_INCOMPLETE,
    WOOCOMMERCE_NOT_CONFIGURED,
    UNSUPPORTED_OPERATION,
    AUTHENTICATION_FAILED,
    AUTHORIZATION_FAILED,
    NOT_FOUND,
    RATE_LIMITED,
    UPSTREAM_VALIDATION_FAILED,
    UPSTREAM_FAILURE,
    INVALID_JSON_RESPONSE,
    RESPONSE_TOO_LARGE,
    TIMEOUT,
    CONNECTION_FAILED,
    REDIRECT_REJECTED,
    BLOCKED_ADDRESS,
    ARTIFACT_INPUT_UNAVAILABLE,
    ARTIFACT_OUTPUT_UNAVAILABLE,
    TIMEOUT_UNKNOWN,
    INTERNAL_ERROR,
)

#: Codes that leave a mutation's outcome unknown to the caller.
AMBIGUOUS_ERROR_CODES: frozenset[str] = frozenset({TIMEOUT_UNKNOWN})


class ExtensionError(Exception):
    """A failure already reduced to a safe code and a safe message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        failure_class: str | None = None,
        retryable: bool | None = None,
        retry_after_seconds: float | None = None,
        definitely_no_external_effect: bool | None = None,
        external_effect_status: str | None = None,
        http_status: int | None = None,
    ) -> None:
        safe_code = code if code in SAFE_ERROR_CODES else INTERNAL_ERROR
        super().__init__(message)
        self.code = safe_code
        self.message = message
        self.failure_class = failure_class
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.definitely_no_external_effect = definitely_no_external_effect
        self.external_effect_status = external_effect_status
        self.http_status = http_status

    def retry_facts(self) -> dict[str, object]:
        facts: dict[str, object] = {}
        for key in (
            "failure_class",
            "retryable",
            "retry_after_seconds",
            "definitely_no_external_effect",
            "external_effect_status",
            "http_status",
        ):
            value = getattr(self, key)
            if value is not None:
                facts[key] = value
        if self.failure_class in {"provider", "transient"}:
            facts["provider_error_code"] = self.code
        return facts


def error_response(
    code: str,
    message: str,
    *,
    retry_facts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the failing runtime envelope for one safe error."""
    safe_code = code if code in SAFE_ERROR_CODES else INTERNAL_ERROR
    response: dict[str, object] = {
        "ok": False,
        "result": {},
        "error_code": safe_code,
        "error": message,
        "errors": [{"code": safe_code, "message": message}],
    }
    if safe_code in AMBIGUOUS_ERROR_CODES:
        response["external_effect_status"] = TIMEOUT_UNKNOWN
        response["definitely_no_external_effect"] = False
    if retry_facts:
        response.update(retry_facts)
    return response


def classify_status(status: int, *, mutating: bool) -> tuple[str, str]:
    """Map one upstream HTTP status onto a safe code and a safe message."""
    if 300 <= status < 400:
        return REDIRECT_REJECTED, "The site redirected the request and it was not followed"
    if status == 401:
        return AUTHENTICATION_FAILED, "The site rejected the supplied credentials"
    if status == 403:
        return AUTHORIZATION_FAILED, "The authenticated user is not allowed to do this"
    if status == 404:
        return NOT_FOUND, "The site does not expose the requested resource"
    if status == 429:
        return RATE_LIMITED, "The site is rate limiting requests"
    if status in {400, 409, 422}:
        return UPSTREAM_VALIDATION_FAILED, "The site rejected the request as invalid"
    if status in {408, 500, 502, 503, 504} and mutating:
        return TIMEOUT_UNKNOWN, "The outcome of this request is unknown"
    return UPSTREAM_FAILURE, "The site could not complete the request"


__all__ = [
    "AMBIGUOUS_ERROR_CODES",
    "SAFE_ERROR_CODES",
    "ExtensionError",
    "classify_status",
    "error_response",
]
