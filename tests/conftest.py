from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))
# The offline generators live beside the tests that cover them.
GENERATOR_ROOT = BUNDLE_ROOT / "tests" / "reference"
if str(GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATOR_ROOT))

from runtime import connection as connection_module  # noqa: E402
from runtime.transport import RestTransport  # noqa: E402

SITE_URL = "https://shop.example"
CONNECTION_ID = "conn-1"


class FakeResponse:
    """A deterministic stand-in for one urllib response."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.code = status
        self.headers = _Headers(headers)
        self._buffer = body

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._buffer = self._buffer, b""
            return chunk
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = {key.lower(): value for key, value in values.items()}

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(name.lower(), default)


class FakeHttp:
    """Records every outbound request and replays scripted responses."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[Any] = []
        self.default: Any = FakeResponse(200, {}, b"{}")

    def queue(self, *responses: Any) -> None:
        self.responses.extend(responses)

    def __call__(self, request: Any, *, timeout_seconds: float, purpose: str) -> Any:
        data = request.data
        if data is not None and not isinstance(data, (bytes, bytearray)):
            data = b"".join(bytes(chunk) for chunk in data)
        self.requests.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "body": bytes(data) if data is not None else None,
                "timeout_seconds": timeout_seconds,
                "purpose": purpose,
            }
        )
        response = self.responses.pop(0) if self.responses else self.default
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def last(self) -> dict[str, Any]:
        return self.requests[-1]

    def json_body(self, index: int = -1) -> Any:
        raw = self.requests[index]["body"]
        return json.loads(raw.decode("utf-8")) if raw else None


def json_response(
    payload: Any, *, status: int = 200, headers: dict[str, str] | None = None
) -> FakeResponse:
    return FakeResponse(
        status,
        {"Content-Type": "application/json", **(headers or {})},
        json.dumps(payload).encode("utf-8"),
    )


@pytest.fixture(autouse=True)
def offline_host_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite offline without weakening the shipped host policy.

    The runtime always calls the SDK guard; only the test double is swapped, and
    ``test_security_boundaries.py`` exercises the real guard against a loopback
    address, which needs no name resolution.
    """
    monkeypatch.setattr(
        connection_module, "assert_safe_remote_http_url", lambda url, purpose="": url
    )


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def transport_factory(http: FakeHttp):
    def factory(connection: Any) -> RestTransport:
        return RestTransport(connection, opener=http)

    return factory


def connection_payload(
    operation_id: str,
    operation_input: dict[str, Any],
    *,
    site_url: str = SITE_URL,
    username: str = "svc-flowsteward",
    application_password: str = "abcd EFGH ijkl MNOP",
    consumer_key: str = "",
    consumer_secret: str = "",
    connection_id: str = CONNECTION_ID,
    connection_type_id: str = "wordpress_site",
    runtime_context: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    secrets: dict[str, str] = {"wordpress_application_password": application_password}
    if consumer_key:
        secrets["woocommerce_consumer_key"] = consumer_key
    if consumer_secret:
        secrets["woocommerce_consumer_secret"] = consumer_secret
    payload: dict[str, Any] = {
        "mode": "action",
        "action": {
            "action_id": operation_id,
            "input": {"connection_ref": connection_id, **operation_input},
            "target": {
                "connection": {
                    "connection_id": connection_id,
                    "connection_type_id": connection_type_id,
                    "config": {"site_url": site_url, "wordpress_username": username},
                    "secrets": secrets,
                }
            },
        },
    }
    if runtime_context is not None:
        payload["runtime_context"] = runtime_context
    if extra:
        payload.update(extra)
    return payload


WOO_CREDENTIALS = {
    "consumer_key": "ck_0123456789abcdef",
    "consumer_secret": "cs_0123456789abcdef",  # pragma: allowlist secret
}


def _mapping(value: Any) -> dict[str, Any]:
    """The value as a mapping, or an empty one. Keeps call sites free of guards."""
    return dict(value) if isinstance(value, dict) else {}


def _sample_scalar(schema: dict[str, Any]) -> Any:
    """A valid value for one JSON-schema property."""
    declared = schema.get("type")
    enum = schema.get("enum")
    if enum:
        return enum[0]
    if declared == "integer":
        return 1
    if declared == "number":
        return 1.5
    if declared == "boolean":
        return True
    if declared == "array":
        return []
    if declared == "object":
        return _sample_object(schema)
    return "sample"


def _sample_object(schema: dict[str, Any]) -> dict[str, Any]:
    """One object carrying exactly the properties its schema requires."""
    properties = _mapping(schema.get("properties"))
    required = schema.get("required")
    if not properties or not isinstance(required, list):
        return {}
    return {
        str(name): _sample_scalar(_mapping(properties.get(name)))
        for name in required
        if str(name) in properties
    }


def sample_value(field: dict[str, Any]) -> Any:
    """A valid value for one manifest input, used to exercise every operation."""
    schema = _mapping(field.get("schema"))
    declared = schema.get("type")
    if isinstance(declared, list):
        return "sample"  # a rendered field accepts the plain string form
    enum = field.get("enum") or schema.get("enum")
    value_type = field["value_type"]
    if value_type == "text":
        return enum[0] if enum else "sample"
    if value_type == "integer":
        return 1
    if value_type == "number":
        return 1.5
    if value_type == "boolean":
        return True
    if value_type == "array":
        items = _mapping(schema.get("items"))
        item_type = items.get("type", "string")
        item_enum = items.get("enum")
        if item_type == "object":
            return [_sample_object(items)]
        if item_type == "string":
            return [item_enum[0] if item_enum else "sample"]
        if item_type == "integer":
            return [1]
        if item_type == "number":
            return [1.5]
        if item_type == "boolean":
            return [True]
        return ["sample"]
    return {}


def sample_input(row: Any, *, include_optional: bool = False) -> dict[str, Any]:
    """Minimal valid typed input for one declared operation."""
    from runtime.io_shapes import operation_inputs

    operation_input: dict[str, Any] = {}
    for field in operation_inputs(row):
        name = field["name"]
        if name == "connection_ref":
            continue
        if row.shape == "batch" and name.endswith("_items"):
            continue
        if not field.get("required") and not include_optional:
            continue
        if name == "artifact_handle":
            operation_input[name] = "artifact-1"
        elif name == "filename":
            operation_input[name] = "sample.png"
        elif name in {name for name, _kind in row.path_params}:
            kind = dict(row.path_params)[name]
            operation_input[name] = (
                1 if kind == "integer" else "a/b" if kind == "namespaced_slug" else "slug"
            )
        else:
            operation_input[name] = sample_value(field)
    if row.shape == "batch":
        from runtime.io_shapes import batch_item_fields, batch_members

        member = batch_members(row)[0]
        fields = batch_item_fields(row, member)
        entry = {field["name"]: sample_value(field) for field in fields if field.get("required")}
        operation_input[f"{member}_items"] = [entry or {}]
    return operation_input


def php_parse_str(query: str) -> dict[str, Any]:
    """Emulate how PHP (and therefore WordPress) parses a query string.

    A repeated bare key keeps only its last value; only ``name[]`` accumulates
    into an array. This is what makes bracket syntax necessary for list filters.
    """
    from urllib.parse import unquote, unquote_plus

    parsed: dict[str, Any] = {}
    for part in query.split("&"):
        if not part:
            continue
        raw_key, _, raw_value = part.partition("=")
        key = unquote(raw_key)
        value = unquote_plus(raw_value)
        if key.endswith("[]"):
            parsed.setdefault(key[:-2], []).append(value)
        else:
            parsed[key] = value
    return parsed
