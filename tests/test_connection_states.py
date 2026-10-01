"""The seven distinct connection states, each reached through the real code path."""

from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

import pytest
from conftest import FakeHttp, connection_payload, json_response
from runtime import errors
from runtime.connection_test import (
    CONNECTION_STATES,
    WOOCOMMERCE_AUTHENTICATION_FAILED,
    WOOCOMMERCE_NOT_CONFIGURED,
    WOOCOMMERCE_NOT_INSTALLED,
    WOOCOMMERCE_READY,
    WORDPRESS_AUTHENTICATION_FAILED,
    WORDPRESS_READY,
    WORDPRESS_UNAVAILABLE,
)
from runtime.operations import handle_runtime

WOO = {"consumer_key": "ck_live", "consumer_secret": "cs_live"}  # pragma: allowlist secret


def _index(*namespaces: str) -> object:
    return json_response({"name": "Example Shop", "namespaces": list(namespaces)})


def _http_error(status: int) -> HTTPError:
    return HTTPError("https://shop.example/x", status, "denied", Message(), None)


def _run(http: FakeHttp, transport_factory, **connection_kwargs) -> dict:
    return handle_runtime(
        connection_payload("test_connection", {}, **connection_kwargs),
        transport_factory=transport_factory,
    )


def test_the_seven_states_are_distinct() -> None:
    assert len(set(CONNECTION_STATES)) == 7


def test_wordpress_ready_without_woocommerce_credentials(http, transport_factory) -> None:
    http.queue(
        _index("wp/v2", "wc/v3"),
        json_response({"id": 7, "slug": "svc-flowsteward"}),
    )
    response = _run(http, transport_factory)
    result = response["result"]

    assert response["ok"] is True
    assert result["wordpress_state"] == WORDPRESS_READY
    assert result["woocommerce_state"] == WOOCOMMERCE_NOT_CONFIGURED
    assert result["wordpress_available"] is True
    assert result["woocommerce_available"] is True
    assert result["wordpress_user_id"] == 7
    assert result["wordpress_user_slug"] == "svc-flowsteward"
    # The WooCommerce namespace is detected, but no WooCommerce request is sent.
    assert [entry["url"] for entry in http.requests] == [
        "https://shop.example/wp-json/",
        "https://shop.example/wp-json/wp/v2/users/me",
    ]


def test_both_providers_ready_are_reported_independently(http, transport_factory) -> None:
    http.queue(
        _index("wp/v2", "wc/v3"),
        json_response({"id": 7, "slug": "svc"}),
        json_response({"environment": {}}),
    )
    result = _run(http, transport_factory, **WOO)["result"]

    assert result["wordpress_state"] == WORDPRESS_READY
    assert result["woocommerce_state"] == WOOCOMMERCE_READY
    assert http.requests[1]["url"] == "https://shop.example/wp-json/wp/v2/users/me"
    assert http.requests[2]["url"] == "https://shop.example/wp-json/wc/v3/system_status"
    assert (
        http.requests[1]["headers"]["authorization"] != http.requests[2]["headers"]["authorization"]
    )


def test_wordpress_unavailable_when_the_index_cannot_be_reached(http, transport_factory) -> None:
    http.queue(TimeoutError("no answer"))
    result = _run(http, transport_factory, **WOO)["result"]

    assert result["wordpress_state"] == WORDPRESS_UNAVAILABLE
    assert result["woocommerce_state"] == WOOCOMMERCE_NOT_INSTALLED
    assert result["wordpress_available"] is False
    assert len(http.requests) == 1


def test_wordpress_unavailable_when_the_site_publishes_no_wp_v2(http, transport_factory) -> None:
    http.queue(_index("oembed/1.0"))
    result = _run(http, transport_factory)["result"]

    assert result["wordpress_state"] == WORDPRESS_UNAVAILABLE
    assert result["woocommerce_state"] == WOOCOMMERCE_NOT_INSTALLED


def test_wordpress_authentication_failure_is_its_own_state(http, transport_factory) -> None:
    http.queue(_index("wp/v2"), _http_error(401))
    result = _run(http, transport_factory)["result"]

    assert result["wordpress_state"] == WORDPRESS_AUTHENTICATION_FAILED
    assert result["woocommerce_state"] == WOOCOMMERCE_NOT_INSTALLED


def test_woocommerce_not_installed_when_the_namespace_is_absent(http, transport_factory) -> None:
    http.queue(_index("wp/v2"), json_response({"id": 1, "slug": "svc"}))
    result = _run(http, transport_factory, **WOO)["result"]

    assert result["wordpress_state"] == WORDPRESS_READY
    assert result["woocommerce_state"] == WOOCOMMERCE_NOT_INSTALLED
    assert result["woocommerce_available"] is False


def test_woocommerce_authentication_failure_does_not_mask_wordpress(
    http, transport_factory
) -> None:
    http.queue(
        _index("wp/v2", "wc/v3"),
        json_response({"id": 1, "slug": "svc"}),
        _http_error(401),
    )
    result = _run(http, transport_factory, **WOO)["result"]

    assert result["wordpress_state"] == WORDPRESS_READY
    assert result["woocommerce_state"] == WOOCOMMERCE_AUTHENTICATION_FAILED


def test_woocommerce_key_permission_failure_reports_authentication_failed(
    http, transport_factory
) -> None:
    http.queue(
        _index("wp/v2", "wc/v3"),
        json_response({"id": 1, "slug": "svc"}),
        _http_error(403),
    )
    result = _run(http, transport_factory, **WOO)["result"]
    assert result["woocommerce_state"] == WOOCOMMERCE_AUTHENTICATION_FAILED


def test_an_undetermined_woocommerce_probe_surfaces_the_transport_failure(
    http, transport_factory
) -> None:
    http.queue(
        _index("wp/v2", "wc/v3"),
        json_response({"id": 1, "slug": "svc"}),
        _http_error(500),
    )
    response = _run(http, transport_factory, **WOO)

    assert response["ok"] is False
    assert response["error_code"] == errors.UPSTREAM_FAILURE


def test_a_half_configured_woocommerce_pair_fails_before_any_request(
    http, transport_factory
) -> None:
    response = _run(http, transport_factory, consumer_key="ck_live")

    assert response["ok"] is False
    assert response["error_code"] == errors.WOOCOMMERCE_CREDENTIALS_INCOMPLETE
    assert http.requests == []


def test_the_index_request_is_unauthenticated(http, transport_factory) -> None:
    http.queue(_index("wp/v2"), json_response({"id": 1, "slug": "svc"}))
    _run(http, transport_factory)
    assert "authorization" not in http.requests[0]["headers"]


@pytest.mark.parametrize("extra_input", [{"unexpected": 1}, {"page": 2}])
def test_test_connection_rejects_undeclared_input(http, transport_factory, extra_input) -> None:
    response = handle_runtime(
        connection_payload("test_connection", extra_input),
        transport_factory=transport_factory,
    )
    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []
