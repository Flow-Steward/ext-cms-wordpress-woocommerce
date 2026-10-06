"""WooCommerce-owned complete product export.

The native list operation intentionally represents one REST request. This
operation owns WooCommerce's page-number protocol inside the extension and
streams the complete matching catalog to an artifact so Core never needs to
know provider-specific pagination rules or retain a large catalog in workflow
state.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from flowsteward_extension_sdk import write_artifact_stream

try:
    from flowsteward_extension_sdk import report_progress
except ImportError:  # a Core with an SDK older than 0.3.0 shows no progress

    def report_progress(
        message: str = "", *, done: int | None = None, total: int | None = None
    ) -> None:
        return None


from . import errors, validation
from .catalog import Operation, operation
from .connection import connection_from_payload
from .errors import ExtensionError
from .field_policy import sanitized_response_body
from .pagination import pagination_from_headers
from .transport import RestTransport, operation_timeout_seconds

EXPORT_PRODUCTS_OPERATION_ID = "wc_export_products"
EXPORT_PRODUCTS_BINDING_KEY = "woocommerce_products_export"
EXPORT_PRODUCTS_FILENAME = "woocommerce-products.jsonl"
EXPORT_PRODUCTS_CONTENT_TYPE = "application/x-ndjson"
MAX_EXPORT_PAGES = 100_000
DEFAULT_PAGE_SIZE = 100
_ARTIFACT_SAVE_ERROR = "The product catalog artifact could not be saved"

_FORBIDDEN_PARTIAL_CONTROLS = frozenset({"page", "offset"})

EXPORT_PRODUCTS_OUTPUTS: tuple[dict[str, Any], ...] = (
    {"name": "artifact_handle", "value_type": "artifact_handle"},
    {"name": "filename", "value_type": "text"},
    {"name": "content_type", "value_type": "text"},
    {"name": "item_count", "value_type": "integer"},
    {"name": "page_count", "value_type": "integer"},
    {"name": "total_reported", "value_type": "integer"},
    {"name": "size_bytes", "value_type": "integer"},
    {"name": "sha256", "value_type": "text"},
    {"name": "artifacts", "value_type": "object"},
)


def export_products_inputs() -> list[dict[str, Any]]:
    """Published inputs: all native product filters, never a partial-page start."""
    from .io_shapes import operation_inputs

    fields: list[dict[str, Any]] = []
    for source in operation_inputs(_list_products_operation()):
        if source["name"] in _FORBIDDEN_PARTIAL_CONTROLS:
            continue
        field = dict(source)
        if source["name"] == "per_page":
            field["schema"] = {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": DEFAULT_PAGE_SIZE,
            }
        fields.append(field)
    return fields


def export_products_action_parameters() -> list[dict[str, Any]]:
    from .io_shapes import action_parameters

    return [
        field
        for field in action_parameters(_list_products_operation())
        if field["name"] not in _FORBIDDEN_PARTIAL_CONTROLS
    ]


def export_products_form_fields() -> list[dict[str, Any]]:
    from .io_shapes import step_form_fields

    return [
        field
        for field in step_form_fields(_list_products_operation())
        if field["name"] not in _FORBIDDEN_PARTIAL_CONTROLS
    ]


def export_products(
    payload: Mapping[str, Any],
    raw_input: Any,
    *,
    transport_factory: Any = RestTransport,
    artifact_writer: Callable[..., dict[str, Any]] = write_artifact_stream,
) -> dict[str, Any]:
    """Write every matching WooCommerce product as one bounded JSONL artifact."""
    if not isinstance(raw_input, Mapping):
        raise ExtensionError(errors.INVALID_PAYLOAD, "action.input must be an object")
    if set(raw_input) & _FORBIDDEN_PARTIAL_CONTROLS:
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            "A complete catalog export does not accept page or offset",
        )

    list_operation = _list_products_operation()
    operation_input = validation.validated_input(list_operation, raw_input)
    page_size = _page_size(raw_input.get("per_page"))
    connection = connection_from_payload(payload, connection_ref=operation_input["connection_ref"])
    if not connection.has_woocommerce_credentials:
        raise ExtensionError(
            errors.WOOCOMMERCE_NOT_CONFIGURED,
            "This connection has no WooCommerce API credentials",
        )
    transport = transport_factory(connection)
    base_query = [
        (key, value)
        for key, value in operation_input.get("query") or []
        if key not in {"page", "per_page", "offset"}
    ]
    if not any(key == "order" for key, _value in base_query):
        base_query.append(("order", "asc"))
    if not any(key == "orderby" for key, _value in base_query):
        base_query.append(("orderby", "id"))

    state = {"item_count": 0, "page_count": 0, "total_reported": None}
    chunks = _product_jsonl_chunks(
        transport,
        list_operation,
        base_query=base_query,
        page_size=page_size,
        state=state,
    )
    try:
        written = artifact_writer(
            dict(payload),
            chunks,
            binding_key=EXPORT_PRODUCTS_BINDING_KEY,
            content_type=EXPORT_PRODUCTS_CONTENT_TYPE,
            timeout_seconds=operation_timeout_seconds(),
        )
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        ) from exc
    if not isinstance(written, Mapping):
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        )
    handle = str(written.get("artifact_handle") or "").strip()
    size_bytes = written.get("size_bytes")
    sha256 = str(written.get("sha256") or "").strip()
    if not handle or isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not sha256:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        )

    total_reported = state["total_reported"]
    if not isinstance(total_reported, int):
        total_reported = state["item_count"]
    artifact = {
        "artifact_handle": handle,
        "mime_type": EXPORT_PRODUCTS_CONTENT_TYPE,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }
    return {
        "artifact_handle": handle,
        "filename": EXPORT_PRODUCTS_FILENAME,
        "content_type": EXPORT_PRODUCTS_CONTENT_TYPE,
        "item_count": state["item_count"],
        "page_count": state["page_count"],
        "total_reported": total_reported,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "artifacts": {EXPORT_PRODUCTS_FILENAME: artifact},
    }


def _product_jsonl_chunks(
    transport: Any,
    row: Operation,
    *,
    base_query: list[tuple[str, str]],
    page_size: int,
    state: dict[str, Any],
) -> Iterable[bytes]:
    page = 1
    while page <= MAX_EXPORT_PAGES:
        query = [("page", str(page)), ("per_page", str(page_size)), *base_query]
        url = transport.build_url(row, {}, query)
        response = transport.request_json(
            row,
            url,
            body=None,
            mutating=False,
            purpose=f"woocommerce REST {EXPORT_PRODUCTS_OPERATION_ID} page {page}",
        )
        body = sanitized_response_body(row, response.body)
        if not isinstance(body, list):
            raise ExtensionError(
                errors.UPSTREAM_FAILURE,
                "The site returned an unexpected response shape",
            )
        pagination = pagination_from_headers(
            response.headers,
            page=page,
            per_page=page_size,
        )
        if state["total_reported"] is None and isinstance(pagination.get("total"), int):
            state["total_reported"] = pagination["total"]
        state["page_count"] += 1
        for item in body:
            if not isinstance(item, Mapping):
                raise ExtensionError(
                    errors.UPSTREAM_FAILURE,
                    "The site returned an unexpected product record",
                )
            state["item_count"] += 1
            yield (
                json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            )
        report_progress(
            "Exporting products", done=state["item_count"], total=state["total_reported"]
        )
        if not body or not pagination["has_more"]:
            return
        page += 1
    raise ExtensionError(
        errors.UPSTREAM_FAILURE,
        "The product catalog exceeded the safe pagination limit",
    )


def _page_size(value: Any) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ExtensionError(errors.INVALID_PAYLOAD, "per_page must be between 1 and 100")
    return value


def _list_products_operation() -> Operation:
    row = operation("wc_list_products")
    if row is None:  # pragma: no cover - guarded by the closed catalog tests
        raise ExtensionError(errors.INTERNAL_ERROR, "The product catalog operation is unavailable")
    return row


__all__ = [
    "EXPORT_PRODUCTS_BINDING_KEY",
    "EXPORT_PRODUCTS_CONTENT_TYPE",
    "EXPORT_PRODUCTS_FILENAME",
    "EXPORT_PRODUCTS_OPERATION_ID",
    "EXPORT_PRODUCTS_OUTPUTS",
    "export_products",
    "export_products_action_parameters",
    "export_products_form_fields",
    "export_products_inputs",
]
