"""Connection normalization and the WooCommerce credential pairing rule."""

from __future__ import annotations

import pytest
from conftest import connection_payload
from runtime import errors
from runtime.connection import Connection, connection_from_payload, normalize_site_url
from runtime.errors import ExtensionError


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("example.com", "https://example.com"),
        ("  https://Example.COM/  ", "https://example.com"),
        ("https://example.com/wp-json", "https://example.com"),
        ("https://example.com/wp-json/", "https://example.com"),
        ("https://example.com/wp-json/wp/v2", "https://example.com"),
        ("https://example.com/wp-json/wc/v3", "https://example.com"),
        ("https://example.com/blog/wp-json", "https://example.com/blog"),
        ("https://example.com/blog/", "https://example.com/blog"),
        ("https://example.com:8443/shop", "https://example.com:8443/shop"),
        ("https://example.com:443/", "https://example.com"),
    ],
)
def test_site_url_is_normalized_to_a_bare_https_origin(supplied: str, expected: str) -> None:
    assert normalize_site_url(supplied) == expected


@pytest.mark.parametrize(
    "supplied",
    [
        "",
        "   ",
        None,
        123,
        "http://example.com",
        "ftp://example.com",
        "https://user:secret@example.com",  # pragma: allowlist secret
        "https://example.com?probe=1",
        "https://example.com#fragment",
        "https://example.com/../etc",
        "https://example.com/a//b",
        "https:///nohost",
        "https://exa mple.com",
        "https://example.com/\npath",
    ],
)
def test_unusable_site_urls_are_refused(supplied: object) -> None:
    with pytest.raises(ExtensionError) as raised:
        normalize_site_url(supplied)
    assert raised.value.code == errors.INVALID_CONFIGURATION


def test_wordpress_only_connection_is_valid_and_reports_no_woocommerce() -> None:
    connection = connection_from_payload(
        connection_payload("wp_list_posts", {}), connection_ref="conn-1"
    )
    assert connection.site_url == "https://shop.example"
    assert connection.wordpress_username == "svc-flowsteward"
    assert connection.has_woocommerce_credentials is False
    assert connection.wordpress_authorization().startswith("Basic ")


def test_both_woocommerce_secrets_enable_the_woocommerce_header() -> None:
    connection = connection_from_payload(
        connection_payload(
            "wc_list_orders",
            {},
            consumer_key="ck_live",
            consumer_secret="cs_live",  # pragma: allowlist secret
        ),
        connection_ref="conn-1",
    )
    assert connection.has_woocommerce_credentials is True
    assert connection.woocommerce_authorization().startswith("Basic ")
    assert connection.woocommerce_authorization() != connection.wordpress_authorization()


@pytest.mark.parametrize(
    ("consumer_key", "consumer_secret"),
    [("ck_live", ""), ("", "cs_live")],
)
def test_one_woocommerce_secret_alone_is_refused(consumer_key: str, consumer_secret: str) -> None:
    _raises_input_88_1 = connection_payload(
        "wc_list_orders", {}, consumer_key=consumer_key, consumer_secret=consumer_secret
    )
    with pytest.raises(ExtensionError) as raised:
        connection_from_payload(_raises_input_88_1, connection_ref="conn-1")
    assert raised.value.code == errors.WOOCOMMERCE_CREDENTIALS_INCOMPLETE


def test_woocommerce_header_is_refused_when_no_keys_are_configured() -> None:
    connection = connection_from_payload(
        connection_payload("wp_list_posts", {}), connection_ref="conn-1"
    )
    with pytest.raises(ExtensionError) as raised:
        connection.woocommerce_authorization()
    assert raised.value.code == errors.WOOCOMMERCE_NOT_CONFIGURED


def test_connection_must_match_the_requested_reference_and_type() -> None:
    _raises_input_111_1 = connection_payload("wp_list_posts", {})
    with pytest.raises(ExtensionError) as mismatched:
        connection_from_payload(_raises_input_111_1, connection_ref="other-connection")
    assert mismatched.value.code == errors.INVALID_CONNECTION

    _raises_input_117_1 = connection_payload("wp_list_posts", {}, connection_type_id="imap_mailbox")
    with pytest.raises(ExtensionError) as wrong_type:
        connection_from_payload(_raises_input_117_1, connection_ref="conn-1")
    assert wrong_type.value.code == errors.INVALID_CONNECTION


def test_unknown_config_or_secret_fields_are_refused() -> None:
    payload = connection_payload("wp_list_posts", {})
    payload["action"]["target"]["connection"]["config"]["extra"] = "no"
    with pytest.raises(ExtensionError) as raised:
        connection_from_payload(payload, connection_ref="conn-1")
    assert raised.value.code == errors.INVALID_CONNECTION


def test_missing_application_password_is_refused() -> None:
    payload = connection_payload("wp_list_posts", {})
    payload["action"]["target"]["connection"]["secrets"] = {}
    with pytest.raises(ExtensionError) as raised:
        connection_from_payload(payload, connection_ref="conn-1")
    assert raised.value.code == errors.INVALID_CONNECTION


def test_repr_never_carries_a_secret() -> None:
    connection = connection_from_payload(
        connection_payload(
            "wc_list_orders",
            {},
            consumer_key="ck_secret",
            consumer_secret="cs_secret",  # pragma: allowlist secret
        ),
        connection_ref="conn-1",
    )
    rendered = repr(connection)
    assert "ck_secret" not in rendered
    assert "cs_secret" not in rendered
    assert "abcd EFGH ijkl MNOP" not in rendered
    assert isinstance(connection, Connection)
