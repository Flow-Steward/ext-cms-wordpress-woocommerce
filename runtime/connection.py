"""Project-scoped connection contract: normalization, secrets, and auth headers."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from flowsteward_extension_sdk import PinnedPeerError, assert_safe_remote_http_url

from . import errors
from .errors import ExtensionError

CONNECTION_TYPE_ID = "wordpress_site"

CONFIG_FIELDS: frozenset[str] = frozenset({"site_url", "wordpress_username"})
REQUIRED_CONFIG_FIELDS: frozenset[str] = frozenset({"site_url", "wordpress_username"})
SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "wordpress_application_password",
        "woocommerce_consumer_key",
        "woocommerce_consumer_secret",
    }
)
REQUIRED_SECRET_FIELDS: frozenset[str] = frozenset({"wordpress_application_password"})
WOOCOMMERCE_SECRET_FIELDS: tuple[str, str] = (
    "woocommerce_consumer_key",
    "woocommerce_consumer_secret",
)

MAX_SITE_URL_LENGTH = 512
MAX_USERNAME_LENGTH = 190
MAX_SECRET_LENGTH = 512

#: Path suffixes a user may paste in place of the bare site URL.
_STRIPPED_SUFFIXES: tuple[str, ...] = (
    "/wp-json/wc/v3",
    "/wp-json/wp/v2",
    "/wp-json",
    "/wc/v3",
    "/wp/v2",
)
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class Connection:
    """One validated project connection to a single WordPress site."""

    connection_id: str
    site_url: str
    wordpress_username: str
    _wordpress_application_password: str
    _woocommerce_consumer_key: str
    _woocommerce_consumer_secret: str

    @property
    def has_woocommerce_credentials(self) -> bool:
        return bool(self._woocommerce_consumer_key and self._woocommerce_consumer_secret)

    def wordpress_authorization(self) -> str:
        return _basic_authorization(self.wordpress_username, self._wordpress_application_password)

    def woocommerce_authorization(self) -> str:
        if not self.has_woocommerce_credentials:
            raise ExtensionError(
                errors.WOOCOMMERCE_NOT_CONFIGURED,
                "This connection has no WooCommerce API credentials",
            )
        return _basic_authorization(
            self._woocommerce_consumer_key, self._woocommerce_consumer_secret
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive, never carries secrets
        return f"Connection(connection_id={self.connection_id!r}, site_url={self.site_url!r})"


def _basic_authorization(user: str, password: str) -> str:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {encoded}"


def normalize_site_url(value: Any) -> str:
    """Reduce a pasted site URL to the bare HTTPS origin plus optional base path."""
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > MAX_SITE_URL_LENGTH:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "Enter the address of your WordPress site"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "The site address contains characters that are not part of a web address",
        )
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    if parsed.scheme != "https":
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "The site address must start with https:// — this extension does not send credentials over http://",
        )
    if parsed.username or parsed.password:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "Remove the username and password from the site address; enter them in the fields below instead",
        )
    if parsed.query or parsed.fragment:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "Remove everything after ? or # from the site address"
        )
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or _HOST_RE.fullmatch(host) is None:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "The site address does not include a valid domain name"
        )
    port = ""
    try:
        if parsed.port is not None and parsed.port != 443:
            port = f":{int(parsed.port)}"
    except ValueError as exc:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "The port in the site address is not a number between 1 and 65535",
        ) from exc
    path = parsed.path.rstrip("/")
    lowered = path.lower()
    for suffix in _STRIPPED_SUFFIXES:
        if lowered.endswith(suffix):
            path = path[: len(path) - len(suffix)]
            break
    path = path.rstrip("/")
    if path and (
        ".." in path
        or "//" in path
        or not path.startswith("/")
        or re.fullmatch(r"(?:/[A-Za-z0-9._~-]{1,64})+", path) is None
    ):
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "The site address may end in a folder such as /blog, but nothing further",
        )
    return f"https://{host}{port}{path}"


def assert_site_url_allowed(site_url: str) -> str:
    """Refuse a site URL the default Flow Steward host policy blocks."""
    try:
        return assert_safe_remote_http_url(site_url, purpose="WordPress site URL")
    except PinnedPeerError as exc:
        raise ExtensionError(
            errors.BLOCKED_ADDRESS, "The site address is not reachable under the host policy"
        ) from exc
    except ValueError as exc:
        raise ExtensionError(
            errors.BLOCKED_ADDRESS, "The site address is not reachable under the host policy"
        ) from exc


def _bounded_secret(value: Any, field: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return ""
    if len(text) > MAX_SECRET_LENGTH or any(
        ord(character) < 32 or ord(character) == 127 for character in text
    ):
        raise ExtensionError(errors.INVALID_CONNECTION, f"{field} is not a usable secret")
    return text


def _username(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if (
        not text
        or len(text) > MAX_USERNAME_LENGTH
        or ":" in text
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "wordpress_username is required and must be a username"
        )
    return text


def connection_from_payload(payload: Mapping[str, Any], *, connection_ref: str) -> Connection:
    """Validate the selected project connection before any outbound request."""
    action = payload.get("action")
    target = action.get("target") if isinstance(action, Mapping) else None
    connection = target.get("connection") if isinstance(target, Mapping) else None
    if not isinstance(connection, Mapping):
        raise ExtensionError(errors.INVALID_CONNECTION, "The selected connection is unavailable")
    connection_id = str(connection.get("connection_id") or "")
    if connection_id != connection_ref:
        raise ExtensionError(
            errors.INVALID_CONNECTION, "The selected connection does not match connection_ref"
        )
    connection_type = str(
        connection.get("connection_type_id") or connection.get("connection_type") or ""
    )
    if connection_type and connection_type != CONNECTION_TYPE_ID:
        raise ExtensionError(errors.INVALID_CONNECTION, "The selected connection is not supported")

    config = connection.get("config")
    config = config if isinstance(config, Mapping) else {}
    secrets = connection.get("secrets")
    secrets = secrets if isinstance(secrets, Mapping) else {}
    if set(config) - CONFIG_FIELDS or set(secrets) - SECRET_FIELDS:
        raise ExtensionError(errors.INVALID_CONNECTION, "The connection carries unsupported fields")

    site_url = normalize_site_url(config.get("site_url"))
    username = _username(config.get("wordpress_username"))
    application_password = _bounded_secret(
        secrets.get("wordpress_application_password"), "wordpress_application_password"
    )
    if not application_password:
        raise ExtensionError(
            errors.INVALID_CONNECTION, "The WordPress application password is missing"
        )
    consumer_key = _bounded_secret(
        secrets.get("woocommerce_consumer_key"), "woocommerce_consumer_key"
    )
    consumer_secret = _bounded_secret(
        secrets.get("woocommerce_consumer_secret"), "woocommerce_consumer_secret"
    )
    if bool(consumer_key) != bool(consumer_secret):
        raise ExtensionError(
            errors.WOOCOMMERCE_CREDENTIALS_INCOMPLETE,
            "WooCommerce needs both a consumer key and a consumer secret, or neither",
        )
    return Connection(
        connection_id=connection_id,
        site_url=site_url,
        wordpress_username=username,
        _wordpress_application_password=application_password,
        _woocommerce_consumer_key=consumer_key,
        _woocommerce_consumer_secret=consumer_secret,
    )


__all__ = [
    "CONFIG_FIELDS",
    "CONNECTION_TYPE_ID",
    "REQUIRED_CONFIG_FIELDS",
    "REQUIRED_SECRET_FIELDS",
    "SECRET_FIELDS",
    "WOOCOMMERCE_SECRET_FIELDS",
    "Connection",
    "assert_site_url_allowed",
    "connection_from_payload",
    "normalize_site_url",
]
