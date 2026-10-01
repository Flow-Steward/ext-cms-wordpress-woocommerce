"""Shared HTTP transport for the WordPress and WooCommerce REST namespaces.

This module owns only transport concerns: JSON serialization, native multipart
media upload, URL and query encoding, authentication headers, timeouts, bounded
responses, and safe error normalization. It does not know what any route means.
Every request goes out through the public Flow Steward extension SDK, which
performs URL validation, DNS/IP pinning, connected-peer verification, redirect
rejection, and timeout enforcement. This extension adds no bypass and no local
override. Note that the SDK's address policy derives from
``ipaddress.is_global``, which admits multicast literals; that gap is a reported
Core issue and is deliberately not worked around here.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from flowsteward_extension_sdk import PinnedPeerError, open_pinned_url, parse_retry_after

from . import errors
from .catalog import (
    SUPPORTED_METHODS,
    SUPPORTED_NAMESPACES,
    WOOCOMMERCE_NAMESPACE,
    Operation,
)
from .connection import Connection, assert_site_url_allowed
from .errors import ExtensionError

_MESSAGE_THAT_ROUTE_IS_NOT_SUPPORTED = "That route is not supported"


DEFAULT_TIMEOUT_SECONDS = 300.0
MIN_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 3600.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 16 * 1024
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_QUERY_PAIRS = 50
MAX_QUERY_BYTES = 4096
CHUNK_BYTES = 64 * 1024

_USER_AGENT = "FlowSteward-WordPress-WooCommerce/1.0"


@dataclass(frozen=True)
class Response:
    """One bounded upstream response."""

    status: int
    headers: Any
    body: Any


class RestTransport:
    """Issues exactly the request one declared operation describes."""

    def __init__(
        self,
        connection: Connection,
        *,
        opener: Callable[..., Any] = open_pinned_url,
        timeout_seconds: float | None = None,
    ) -> None:
        self._connection = connection
        self._opener = opener
        self._timeout_seconds = (
            operation_timeout_seconds()
            if timeout_seconds is None
            else max(MIN_TIMEOUT_SECONDS, min(float(timeout_seconds), MAX_TIMEOUT_SECONDS))
        )

    # -- URL construction -------------------------------------------------

    def build_url(
        self,
        row: Operation,
        path_values: Mapping[str, str],
        query: Sequence[tuple[str, str]] = (),
    ) -> str:
        if row.namespace not in SUPPORTED_NAMESPACES:
            raise ExtensionError(
                errors.UNSUPPORTED_OPERATION, "That REST namespace is not supported"
            )
        if row.method not in SUPPORTED_METHODS:
            raise ExtensionError(errors.UNSUPPORTED_OPERATION, "That HTTP method is not supported")
        route = row.route
        for name, kind in row.path_params:
            placeholder = "{" + name + "}"
            if placeholder not in route:
                raise ExtensionError(
                    errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_ROUTE_IS_NOT_SUPPORTED
                )
            value = path_values.get(name, "")
            if not value:
                raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} is required")
            # Percent-encode the segment so its contents cannot change the
            # URL's structure. Two documented parameter kinds are themselves
            # paths, so they keep the separator and nothing else.
            safe = "/" if kind in {"namespaced_slug", "plugin_file"} else ""
            route = route.replace(placeholder, quote(value, safe=safe))
        if "{" in route or "}" in route:
            raise ExtensionError(errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_ROUTE_IS_NOT_SUPPORTED)
        url = f"{self._connection.site_url}/wp-json/{row.namespace}{route}"
        if query:
            encoded = urlencode(list(query), doseq=False, quote_via=quote)
            if len(encoded) > MAX_QUERY_BYTES:
                raise ExtensionError(errors.INVALID_PAYLOAD, "The query is too long")
            url = f"{url}?{encoded}"
        _assert_same_site(url, self._connection.site_url, row.namespace)
        return url

    # -- Requests ---------------------------------------------------------

    def request_json(
        self,
        row: Operation,
        url: str,
        *,
        body: Any = None,
        mutating: bool,
        purpose: str,
    ) -> Response:
        headers = self._headers(row)
        data: bytes | None = None
        if body is not None:
            data = _json_bytes(body)
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, method=row.method, data=data, headers=headers)
        return self._open(request, mutating=mutating, purpose=purpose)

    def request_multipart(
        self,
        row: Operation,
        url: str,
        *,
        filename: str,
        content_type: str,
        chunks: Iterable[bytes],
        size: int,
        fields: Mapping[str, str],
        purpose: str,
    ) -> Response:
        if size < 0 or size > MAX_UPLOAD_BYTES:
            raise ExtensionError(errors.INVALID_PAYLOAD, "The upload exceeds its safe limit")
        boundary = f"----FlowSteward{secrets.token_hex(16)}"
        prologue, epilogue = _multipart_frame(
            boundary=boundary,
            filename=filename,
            content_type=content_type,
            fields=fields,
        )
        headers = self._headers(row)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        total = len(prologue) + size + len(epilogue)
        headers["Content-Length"] = str(total)
        request = Request(
            url,
            method=row.method,
            data=_multipart_stream(prologue, chunks, epilogue, size),
            headers=headers,
        )
        return self._open(request, mutating=True, purpose=purpose)

    def probe(self, request: Request, *, purpose: str) -> Any:
        """Open one same-site connection-validation request and return its JSON body."""
        _assert_probe_url(request.full_url, self._connection.site_url)
        return self._open(request, mutating=False, purpose=purpose).body

    # -- Internals --------------------------------------------------------

    def _headers(self, row: Operation) -> dict[str, str]:
        if row.namespace == WOOCOMMERCE_NAMESPACE:
            authorization = self._connection.woocommerce_authorization()
        else:
            authorization = self._connection.wordpress_authorization()
        return {
            "Accept": "application/json",
            "Authorization": authorization,
            "User-Agent": _USER_AGENT,
        }

    def _open(self, request: Request, *, mutating: bool, purpose: str) -> Response:
        assert_site_url_allowed(self._connection.site_url)
        try:
            with self._opener(
                request,
                timeout_seconds=self._timeout_seconds,
                purpose=purpose,
            ) as response:
                status = int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)
                raw = read_bounded(response, MAX_RESPONSE_BYTES)
                headers = getattr(response, "headers", None)
        except HTTPError as exc:
            _drain(exc)
            status = int(exc.code)
            code, message = errors.classify_status(status, mutating=mutating)
            raise ExtensionError(
                code,
                message,
                **_http_failure_facts(
                    status=status,
                    mutating=mutating,
                    retry_after=_retry_after_seconds(exc.headers),
                ),
            ) from exc
        except PinnedPeerError as exc:
            raise ExtensionError(
                errors.BLOCKED_ADDRESS,
                "The site address is not reachable under the host policy",
            ) from exc
        except TimeoutError as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.TIMEOUT,
                "The site did not respond in time",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        except OSError as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.CONNECTION_FAILED,
                "The site could not be reached",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        if 300 <= status < 400:
            raise ExtensionError(
                errors.REDIRECT_REJECTED,
                "The site redirected the request and it was not followed",
            )
        if status >= 400:
            code, message = errors.classify_status(status, mutating=mutating)
            raise ExtensionError(
                code,
                message,
                **_http_failure_facts(status=status, mutating=mutating),
            )
        return Response(status=status, headers=headers, body=decode_json(raw))


def operation_timeout_seconds() -> float:
    """Return the extension-owned request deadline bounded by its manifest policy."""
    raw = str(os.getenv("FS_EXTENSION_OPERATION_TIMEOUT_SECONDS") or "300").strip()
    try:
        configured = int(raw)
    except ValueError:
        configured = int(DEFAULT_TIMEOUT_SECONDS)
    return max(MIN_TIMEOUT_SECONDS, min(float(configured), MAX_TIMEOUT_SECONDS))


def read_bounded(response: Any, limit: int) -> bytes:
    buffer = bytearray()
    while True:
        chunk = response.read(min(CHUNK_BYTES, limit + 1 - len(buffer)))
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise ExtensionError(
                errors.RESPONSE_TOO_LARGE, "The site response exceeds its safe limit"
            )
    return bytes(buffer)


def decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", "strict")
        if not text.strip():
            return None
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtensionError(
            errors.INVALID_JSON_RESPONSE, "The site returned a response that is not valid JSON"
        ) from exc


def _drain(exc: HTTPError) -> None:
    try:
        exc.read(MAX_ERROR_BODY_BYTES)
    except Exception:  # pragma: no cover - upstream bodies are never echoed
        return


def _retry_after_seconds(headers: Any) -> float | None:
    if headers is None:
        return None
    try:
        raw = str(headers.get("Retry-After") or "").strip()
    except (AttributeError, TypeError, ValueError):
        return None
    return parse_retry_after(raw)


def _http_failure_facts(
    *,
    status: int,
    mutating: bool,
    retry_after: float | None = None,
) -> dict[str, object]:
    retryable_status = status in {408, 429, 500, 502, 503, 504}
    ambiguous = mutating and status in {408, 500, 502, 503, 504}
    facts: dict[str, object] = {
        "failure_class": "provider",
        "retryable": retryable_status and not ambiguous,
        "definitely_no_external_effect": not ambiguous,
        "external_effect_status": "timeout_unknown" if ambiguous else "failed",
        "http_status": status,
    }
    if retry_after is not None:
        facts["retry_after_seconds"] = retry_after
    return facts


def _transport_failure_facts(*, mutating: bool) -> dict[str, object]:
    return {
        "failure_class": "transient",
        "retryable": not mutating,
        "definitely_no_external_effect": not mutating,
        "external_effect_status": "timeout_unknown" if mutating else "failed",
    }


def _json_bytes(body: Any) -> bytes:
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BODY_BYTES:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The request body exceeds its safe limit")
    return encoded


def _assert_same_site(url: str, site_url: str, namespace: str) -> None:
    parsed = urlsplit(url)
    expected = urlsplit(site_url)
    prefix = f"{expected.path}/wp-json/{namespace}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected.netloc
        or parsed.username
        or parsed.password
        or not parsed.path.startswith(prefix)
        or ".." in parsed.path
        or parsed.fragment
    ):
        raise ExtensionError(errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_ROUTE_IS_NOT_SUPPORTED)


def _assert_probe_url(url: str, site_url: str) -> None:
    parsed = urlsplit(url)
    expected = urlsplit(site_url)
    prefix = f"{expected.path}/wp-json/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected.netloc
        or parsed.username
        or parsed.password
        or not parsed.path.startswith(prefix)
        or ".." in parsed.path
        or parsed.fragment
    ):
        raise ExtensionError(errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_ROUTE_IS_NOT_SUPPORTED)


def _multipart_frame(
    *,
    boundary: str,
    filename: str,
    content_type: str,
    fields: Mapping[str, str],
) -> tuple[bytes, bytes]:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{_quoted(name)}"\r\n'
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{_quoted(filename)}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    return b"".join(parts), f"\r\n--{boundary}--\r\n".encode()


def _multipart_stream(
    prologue: bytes, chunks: Iterable[bytes], epilogue: bytes, size: int
) -> Iterable[bytes]:
    def generate() -> Iterable[bytes]:
        yield prologue
        written = 0
        for chunk in chunks:
            written += len(chunk)
            if written > size:
                raise ExtensionError(
                    errors.INVALID_PAYLOAD, "The upload is larger than its declared size"
                )
            yield bytes(chunk)
        if written != size:
            raise ExtensionError(
                errors.INVALID_PAYLOAD, "The upload is smaller than its declared size"
            )
        yield epilogue

    return generate()


def _quoted(value: str) -> str:
    if any(character in value for character in ('"', "\\", "\r", "\n")):
        raise ExtensionError(errors.INVALID_PAYLOAD, "The multipart field name is not usable")
    return value


__all__ = [
    "MAX_QUERY_BYTES",
    "MAX_QUERY_PAIRS",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BYTES",
    "MAX_UPLOAD_BYTES",
    "Response",
    "RestTransport",
    "decode_json",
    "read_bounded",
]
