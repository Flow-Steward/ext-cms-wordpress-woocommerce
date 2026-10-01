"""Connection validation and the seven distinct connection states."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.request import Request

from . import errors
from .catalog import WOOCOMMERCE_NAMESPACE, WORDPRESS_NAMESPACE
from .connection import Connection, assert_site_url_allowed
from .errors import ExtensionError
from .transport import RestTransport

WORDPRESS_READY = "wordpress_ready"
WORDPRESS_UNAVAILABLE = "wordpress_unavailable"
WORDPRESS_AUTHENTICATION_FAILED = "wordpress_authentication_failed"
WOOCOMMERCE_READY = "woocommerce_ready"
WOOCOMMERCE_NOT_INSTALLED = "woocommerce_not_installed"
WOOCOMMERCE_NOT_CONFIGURED = "woocommerce_not_configured"
WOOCOMMERCE_AUTHENTICATION_FAILED = "woocommerce_authentication_failed"

WORDPRESS_STATES: tuple[str, ...] = (
    WORDPRESS_READY,
    WORDPRESS_UNAVAILABLE,
    WORDPRESS_AUTHENTICATION_FAILED,
)
WOOCOMMERCE_STATES: tuple[str, ...] = (
    WOOCOMMERCE_READY,
    WOOCOMMERCE_NOT_INSTALLED,
    WOOCOMMERCE_NOT_CONFIGURED,
    WOOCOMMERCE_AUTHENTICATION_FAILED,
)
CONNECTION_STATES: tuple[str, ...] = WORDPRESS_STATES + WOOCOMMERCE_STATES

_AUTH_FAILURES = frozenset({errors.AUTHENTICATION_FAILED, errors.AUTHORIZATION_FAILED})
MAX_NAMESPACES = 200


def test_connection(connection: Connection, transport: RestTransport) -> dict[str, Any]:
    """Validate one connection and report an independent state per provider.

    The index request establishes reachability and which namespaces the site
    publishes. WordPress identity is then proved against ``/wp/v2/users/me``.
    ``/wc/v3`` is detected from the same index but authenticated separately, so
    a WooCommerce problem never masks a working WordPress connection.
    """
    assert_site_url_allowed(connection.site_url)
    reachable, index_body = _index(connection, transport)
    if not reachable:
        return _result(
            connection,
            wordpress_state=WORDPRESS_UNAVAILABLE,
            woocommerce_state=WOOCOMMERCE_NOT_INSTALLED,
            site_name="",
            namespaces=[],
            wordpress_user_id=None,
            wordpress_user_slug="",
        )
    namespaces = _namespaces(index_body)
    site_name = _site_name(index_body)
    if WORDPRESS_NAMESPACE not in namespaces:
        return _result(
            connection,
            wordpress_state=WORDPRESS_UNAVAILABLE,
            woocommerce_state=WOOCOMMERCE_NOT_INSTALLED,
            site_name=site_name,
            namespaces=namespaces,
            wordpress_user_id=None,
            wordpress_user_slug="",
        )

    wordpress_state = WORDPRESS_READY
    user_id: int | None = None
    user_slug = ""
    try:
        identity = _get_json(
            connection,
            transport,
            f"{connection.site_url}/wp-json/{WORDPRESS_NAMESPACE}/users/me",
            authorization=connection.wordpress_authorization(),
            purpose="WordPress identity check",
        )
    except ExtensionError as exc:
        wordpress_state = (
            WORDPRESS_AUTHENTICATION_FAILED if exc.code in _AUTH_FAILURES else WORDPRESS_UNAVAILABLE
        )
    else:
        if isinstance(identity, Mapping):
            raw_id = identity.get("id")
            user_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
            slug = identity.get("slug")
            user_slug = slug[:190] if isinstance(slug, str) else ""

    woocommerce_state = _woocommerce_state(connection, transport, namespaces)
    return _result(
        connection,
        wordpress_state=wordpress_state,
        woocommerce_state=woocommerce_state,
        site_name=site_name,
        namespaces=namespaces,
        wordpress_user_id=user_id,
        wordpress_user_slug=user_slug,
    )


def _woocommerce_state(
    connection: Connection, transport: RestTransport, namespaces: list[str]
) -> str:
    if WOOCOMMERCE_NAMESPACE not in namespaces:
        return WOOCOMMERCE_NOT_INSTALLED
    if not connection.has_woocommerce_credentials:
        return WOOCOMMERCE_NOT_CONFIGURED
    try:
        _get_json(
            connection,
            transport,
            f"{connection.site_url}/wp-json/{WOOCOMMERCE_NAMESPACE}/system_status",
            authorization=connection.woocommerce_authorization(),
            purpose="WooCommerce credential check",
        )
    except ExtensionError as exc:
        if exc.code in _AUTH_FAILURES:
            return WOOCOMMERCE_AUTHENTICATION_FAILED
        if exc.code == errors.NOT_FOUND:
            return WOOCOMMERCE_NOT_INSTALLED
        # Anything else leaves the WooCommerce state genuinely undetermined, and
        # reporting one of the four states anyway would be a guess. Surface the
        # transport failure instead.
        raise
    return WOOCOMMERCE_READY


def _index(connection: Connection, transport: RestTransport) -> tuple[bool, Any]:
    """Fetch ``/wp-json/``; report unreachable rather than raising."""
    try:
        body = _get_json(
            connection,
            transport,
            f"{connection.site_url}/wp-json/",
            authorization="",
            purpose="WordPress REST index",
        )
    except ExtensionError:
        return False, None
    return True, body


def _get_json(
    connection: Connection,
    transport: RestTransport,
    url: str,
    *,
    authorization: str,
    purpose: str,
) -> Any:
    del connection
    headers = {"Accept": "application/json", "User-Agent": "FlowSteward-WordPress-WooCommerce/1.0"}
    if authorization:
        headers["Authorization"] = authorization
    request = Request(url, method="GET", headers=headers)
    return transport.probe(request, purpose=purpose)


def _namespaces(body: Any) -> list[str]:
    if not isinstance(body, Mapping):
        return []
    raw = body.get("namespaces")
    if not isinstance(raw, list):
        return []
    return [item for item in raw[:MAX_NAMESPACES] if isinstance(item, str) and len(item) <= 64]


def _site_name(body: Any) -> str:
    if not isinstance(body, Mapping):
        return ""
    name = body.get("name")
    return name[:190] if isinstance(name, str) else ""


def _result(
    connection: Connection,
    *,
    wordpress_state: str,
    woocommerce_state: str,
    site_name: str,
    namespaces: list[str],
    wordpress_user_id: int | None,
    wordpress_user_slug: str,
) -> dict[str, Any]:
    return {
        "site_url": connection.site_url,
        "site_name": site_name,
        "namespaces": namespaces,
        "wordpress_state": wordpress_state,
        "woocommerce_state": woocommerce_state,
        "wordpress_available": WORDPRESS_NAMESPACE in namespaces,
        "woocommerce_available": WOOCOMMERCE_NAMESPACE in namespaces,
        "wordpress_user_id": wordpress_user_id,
        "wordpress_user_slug": wordpress_user_slug,
    }


__all__ = [
    "CONNECTION_STATES",
    "WOOCOMMERCE_AUTHENTICATION_FAILED",
    "WOOCOMMERCE_NOT_CONFIGURED",
    "WOOCOMMERCE_NOT_INSTALLED",
    "WOOCOMMERCE_READY",
    "WOOCOMMERCE_STATES",
    "WORDPRESS_AUTHENTICATION_FAILED",
    "WORDPRESS_READY",
    "WORDPRESS_STATES",
    "WORDPRESS_UNAVAILABLE",
    "test_connection",
]
