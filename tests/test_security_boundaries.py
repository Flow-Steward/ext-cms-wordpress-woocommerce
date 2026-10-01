"""Transport security: host policy, redirects, bounds, and credential containment."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from urllib.error import HTTPError, URLError

import pytest
from conftest import FakeResponse, connection_payload, json_response
from flowsteward_extension_sdk import PinnedPeerError
from runtime import connection as connection_module
from runtime import errors
from runtime.connection import assert_site_url_allowed, connection_from_payload
from runtime.errors import ExtensionError
from runtime.operations import handle_runtime
from runtime.transport import MAX_RESPONSE_BYTES


def test_wordpress_retry_after_accepts_http_date() -> None:
    from runtime.transport import _retry_after_seconds

    value = format_datetime(datetime.now(UTC) + timedelta(minutes=10), usegmt=True)

    assert 590 <= (_retry_after_seconds({"Retry-After": value}) or 0) <= 600


APPLICATION_PASSWORD = "abcd EFGH ijkl MNOP"  # pragma: allowlist secret
LIVE_CREDENTIALS = {
    "consumer_key": "ck_live",
    "consumer_secret": "cs_live",  # pragma: allowlist secret
}
TRACER_CREDENTIALS = {
    "consumer_key": "ck_topsecret",
    "consumer_secret": "cs_topsecret",  # pragma: allowlist secret
}


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


@pytest.mark.parametrize(
    "site_url",
    [
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://192.168.1.10",
        "https://[::1]",
        "https://240.0.0.1",
    ],
)
def test_the_real_host_policy_rejects_reserved_addresses(
    monkeypatch: pytest.MonkeyPatch, site_url: str
) -> None:
    """The shipped guard is the SDK's, and the extension adds no exception.

    Note: the SDK derives its policy from ``ipaddress.is_global``, which admits
    IPv4 and IPv6 multicast literals. That gap is reported as a separate Core
    task; this extension deliberately adds no local override for it, and a TCP
    connect to a multicast literal cannot complete in any case.
    """
    monkeypatch.delenv("FS_ALLOW_PRIVATE_REMOTE_URLS", raising=False)
    monkeypatch.setattr(
        connection_module,
        "assert_safe_remote_http_url",
        __import__(
            "flowsteward_extension_sdk", fromlist=["assert_safe_remote_http_url"]
        ).assert_safe_remote_http_url,
    )
    with pytest.raises(ExtensionError) as raised:
        assert_site_url_allowed(site_url)
    assert raised.value.code == errors.BLOCKED_ADDRESS


def test_a_blocked_address_is_rejected_before_any_connection(
    monkeypatch: pytest.MonkeyPatch, http, transport_factory
) -> None:
    monkeypatch.setattr(
        connection_module,
        "assert_safe_remote_http_url",
        lambda url, purpose="": (_ for _ in ()).throw(PinnedPeerError("blocked")),
    )
    response = _run("wp_list_posts", {}, transport_factory, site_url="https://shop.example")

    assert response["ok"] is False
    assert response["error_code"] == errors.BLOCKED_ADDRESS
    assert http.requests == []


def test_an_upstream_redirect_is_rejected_and_credentials_are_not_forwarded(
    http, transport_factory
) -> None:
    http.queue(FakeResponse(301, {"Location": "https://attacker.example/collect"}, b""))
    response = _run("wp_list_posts", {}, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.REDIRECT_REJECTED
    assert len(http.requests) == 1
    assert http.requests[0]["url"].startswith("https://shop.example/")


def test_a_redirect_status_raised_as_an_http_error_is_also_rejected(
    http, transport_factory
) -> None:
    http.queue(HTTPError("https://shop.example/x", 302, "found", Message(), None))
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["error_code"] == errors.REDIRECT_REJECTED


def test_an_oversized_response_is_refused(http, transport_factory) -> None:
    http.queue(FakeResponse(200, {}, b"[" + b"0," * (MAX_RESPONSE_BYTES // 2) + b"0]"))
    response = _run("wp_list_posts", {}, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.RESPONSE_TOO_LARGE
    assert response["result"] == {}


def test_invalid_json_is_reported_without_echoing_the_body(http, transport_factory) -> None:
    http.queue(FakeResponse(200, {}, b"<html>fatal error at /var/www/wp-config.php</html>"))
    response = _run("wp_list_posts", {}, transport_factory)

    assert response["error_code"] == errors.INVALID_JSON_RESPONSE
    assert "wp-config" not in json.dumps(response)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, errors.AUTHENTICATION_FAILED),
        (403, errors.AUTHORIZATION_FAILED),
        (404, errors.NOT_FOUND),
        (400, errors.UPSTREAM_VALIDATION_FAILED),
        (422, errors.UPSTREAM_VALIDATION_FAILED),
        (429, errors.RATE_LIMITED),
        (500, errors.UPSTREAM_FAILURE),
        (503, errors.UPSTREAM_FAILURE),
    ],
)
def test_read_failures_map_to_stable_safe_codes(
    http, transport_factory, status: int, expected: str
) -> None:
    http.queue(
        HTTPError(
            "https://shop.example/x",
            status,
            "err",
            Message(),
            None,
        )
    )
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["error_code"] == expected


def test_rate_limited_read_exposes_retry_facts_without_headers(http, transport_factory) -> None:
    headers = Message()
    headers["Retry-After"] = "11"
    http.queue(HTTPError("https://shop.example/x", 429, "err", headers, None))

    response = _run("wp_list_posts", {}, transport_factory)

    assert (
        response.items()
        >= {
            "failure_class": "provider",
            "retryable": True,
            "retry_after_seconds": 11.0,
            "definitely_no_external_effect": True,
            "external_effect_status": "failed",
            "provider_error_code": errors.RATE_LIMITED,
            "http_status": 429,
        }.items()
    )


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
def test_a_mutation_that_may_have_landed_is_reported_as_ambiguous(
    http, transport_factory, status: int
) -> None:
    http.queue(HTTPError("https://shop.example/x", status, "err", Message(), None))
    response = _run("wp_create_post", {"title": "x"}, transport_factory)

    assert response["error_code"] == errors.TIMEOUT_UNKNOWN
    assert response["external_effect_status"] == errors.TIMEOUT_UNKNOWN
    assert response["definitely_no_external_effect"] is False
    assert response["retryable"] is False


def test_a_read_timeout_is_not_ambiguous(http, transport_factory) -> None:
    http.queue(TimeoutError("slow"))
    response = _run("wp_list_posts", {}, transport_factory)

    assert response["error_code"] == errors.TIMEOUT
    assert response["external_effect_status"] == "failed"
    assert response["definitely_no_external_effect"] is True


def test_a_connection_failure_is_reported_as_such(http, transport_factory) -> None:
    http.queue(URLError("unreachable"))
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["error_code"] == errors.CONNECTION_FAILED


def test_credentials_travel_only_in_the_authorization_header(http, transport_factory) -> None:
    http.queue(json_response([{"id": 1}]))
    _run(
        "wc_list_orders",
        {},
        transport_factory,
        **TRACER_CREDENTIALS,
    )
    request = http.last

    assert TRACER_CREDENTIALS["consumer_key"] not in request["url"]
    assert "cs_topsecret" not in request["url"]
    assert "?" not in request["url"]
    header = request["headers"]["authorization"]
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    assert decoded == "ck_topsecret:cs_topsecret"


def test_no_error_response_ever_carries_a_credential(http, transport_factory) -> None:
    for failure in (
        HTTPError("https://shop.example/x", 401, "no", Message(), None),
        TimeoutError("slow"),
        URLError("down"),
    ):
        http.responses.clear()
        http.queue(failure)
        response = _run(
            "wc_list_orders",
            {},
            transport_factory,
            **TRACER_CREDENTIALS,
        )
        rendered = json.dumps(response)
        assert "ck_topsecret" not in rendered
        assert "cs_topsecret" not in rendered
        assert APPLICATION_PASSWORD not in rendered
        assert "Basic " not in rendered


def test_the_wordpress_header_is_used_for_wp_v2_and_the_woo_header_for_wc_v3(
    http, transport_factory
) -> None:
    connection = connection_from_payload(
        connection_payload(
            "wp_list_posts",
            {},
            **LIVE_CREDENTIALS,
        ),
        connection_ref="conn-1",
    )
    http.queue(json_response([]), json_response([]))
    _run(
        "wp_list_posts",
        {},
        transport_factory,
        **LIVE_CREDENTIALS,
    )
    _run(
        "wc_list_orders",
        {},
        transport_factory,
        **LIVE_CREDENTIALS,
    )

    assert http.requests[0]["headers"]["authorization"] == connection.wordpress_authorization()
    assert http.requests[1]["headers"]["authorization"] == connection.woocommerce_authorization()


def test_requests_use_the_configured_extension_operation_timeout(
    http, transport_factory, monkeypatch
) -> None:
    monkeypatch.setenv("FS_EXTENSION_OPERATION_TIMEOUT_SECONDS", "600")
    http.queue(json_response([]))
    _run("wp_list_posts", {}, transport_factory)
    assert http.last["timeout_seconds"] == 600.0


def test_a_non_utf8_body_is_reported_as_invalid_json(http, transport_factory) -> None:
    http.queue(FakeResponse(200, {}, b"\xff\xfe\x00binary"))
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["error_code"] == errors.INVALID_JSON_RESPONSE


def test_an_empty_body_is_not_mistaken_for_invalid_json(http, transport_factory) -> None:
    http.queue(FakeResponse(200, {}, b""))
    response = _run("wp_get_post", {"id": 1}, transport_factory)
    assert response["ok"] is True
    assert response["result"]["data"] is None
