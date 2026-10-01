"""Execute exactly one declared operation, or refuse before any outbound I/O."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from . import errors, validation
from .catalog import (
    TEST_CONNECTION_OPERATION_ID,
    VALIDATE_SETTINGS_OPERATION_ID,
    WOOCOMMERCE_NAMESPACE,
    Operation,
    operation,
)
from .catalog_export import EXPORT_PRODUCTS_OPERATION_ID, export_products
from .connection import connection_from_payload, normalize_site_url
from .connection_test import test_connection
from .errors import ExtensionError, error_response
from .field_policy import sanitized_response_body
from .io_shapes import batch_members
from .media import media_upload_source
from .pagination import pagination_from_headers
from .transport import RestTransport

#: Exactly the keys the host puts in an action envelope. Rejecting the ones it
#: adds for provenance — which page and component invoked the action, and the
#: host context — made every operation fail with `invalid_payload` when it was
#: called through the platform rather than in a test.
_ALLOWED_ACTION_KEYS = frozenset(
    {
        "action_id",
        "operation_id",
        "page_id",
        "component_id",
        "context",
        "input",
        "target",
    }
)

TEST_CONNECTION_INPUT_FIELDS: frozenset[str] = frozenset({"connection_ref"})

VALIDATE_SETTINGS_INPUT_FIELDS: frozenset[str] = frozenset({"check", "site_url"})
VALIDATE_SETTINGS_RESULT_FIELDS: tuple[str, ...] = ("valid", "check", "normalized_site_url")
VALIDATE_SETTINGS_CHECKS: tuple[str, ...] = ("site_url", "woocommerce_pair")
TEST_CONNECTION_RESULT_FIELDS: tuple[str, ...] = (
    "site_url",
    "site_name",
    "namespaces",
    "wordpress_state",
    "woocommerce_state",
    "wordpress_available",
    "woocommerce_available",
    "wordpress_user_id",
    "wordpress_user_slug",
)

_PRODUCT_BATCH_OPERATION_ID = "wc_batch_products"
_PRODUCT_BATCH_RECEIPT_FIELDS: tuple[str, ...] = (
    "id",
    "sku",
    "status",
    "stock_status",
    "stock_quantity",
    "regular_price",
    "price",
)


def handle_runtime(
    payload: Mapping[str, Any],
    *,
    transport_factory: Any = RestTransport,
    artifact_streamer: Any = None,
    artifact_writer: Any = None,
) -> dict[str, Any]:
    """Dispatch one runtime invocation through the closed registry."""
    try:
        operation_id, raw_input = _envelope(payload)
        if operation_id == TEST_CONNECTION_OPERATION_ID:
            return _run_test_connection(payload, raw_input, transport_factory)
        if operation_id == VALIDATE_SETTINGS_OPERATION_ID:
            return _run_validate_settings(raw_input)
        if operation_id == EXPORT_PRODUCTS_OPERATION_ID:
            kwargs = {"transport_factory": transport_factory}
            if artifact_writer is not None:
                kwargs["artifact_writer"] = artifact_writer
            return _ok(export_products(payload, raw_input, **kwargs))
        row = operation(operation_id)
        if row is None:
            raise ExtensionError(
                errors.UNSUPPORTED_OPERATION, "That operation is not part of this extension"
            )
        return _run_rest_operation(payload, row, raw_input, transport_factory, artifact_streamer)
    except ExtensionError as exc:
        return error_response(exc.code, exc.message, retry_facts=exc.retry_facts())
    except Exception:
        return error_response(errors.INTERNAL_ERROR, "The operation could not be completed")


def _envelope(payload: Mapping[str, Any]) -> tuple[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("mode") != "action":
        raise ExtensionError(errors.INVALID_PAYLOAD, "Request mode must be action")
    action = payload.get("action")
    if not isinstance(action, Mapping) or set(action) - _ALLOWED_ACTION_KEYS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The action envelope is invalid")
    operation_id = action.get("action_id") or action.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise ExtensionError(errors.INVALID_PAYLOAD, "An operation id is required")
    return operation_id.strip(), action.get("input")


def _run_validate_settings(raw_input: Any) -> dict[str, Any]:
    """Check what the connection form cannot check for itself, before it saves.

    Runs entirely in-process: no request is made and no secret is received. The
    WooCommerce pairing rule is triggered by the form's own conditions, so this
    only has to report it.
    """
    if not isinstance(raw_input, Mapping) or set(raw_input) - VALIDATE_SETTINGS_INPUT_FIELDS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The operation input contract is invalid")
    check = raw_input.get("check")
    if check not in VALIDATE_SETTINGS_CHECKS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "check must be one of the documented values")
    if check == "woocommerce_pair":
        raise ExtensionError(
            errors.WOOCOMMERCE_CREDENTIALS_INCOMPLETE,
            "WooCommerce needs both a consumer key and a consumer secret, or neither",
        )
    normalized = normalize_site_url(raw_input.get("site_url"))
    return _ok({"valid": True, "check": check, "normalized_site_url": normalized})


def _run_test_connection(
    payload: Mapping[str, Any], raw_input: Any, transport_factory: Any
) -> dict[str, Any]:
    if not isinstance(raw_input, Mapping) or set(raw_input) - TEST_CONNECTION_INPUT_FIELDS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The operation input contract is invalid")
    connection_ref = validation.connection_ref(raw_input.get("connection_ref"))
    connection = connection_from_payload(payload, connection_ref=connection_ref)
    transport = transport_factory(connection)
    return _ok(test_connection(connection, transport))


def _run_rest_operation(
    payload: Mapping[str, Any],
    row: Operation,
    raw_input: Any,
    transport_factory: Any,
    artifact_streamer: Any = None,
) -> dict[str, Any]:
    operation_input = validation.validated_input(row, raw_input)
    connection = connection_from_payload(payload, connection_ref=operation_input["connection_ref"])
    if row.namespace == WOOCOMMERCE_NAMESPACE and not connection.has_woocommerce_credentials:
        raise ExtensionError(
            errors.WOOCOMMERCE_NOT_CONFIGURED,
            "This connection has no WooCommerce API credentials",
        )
    if row.has_external_effect and _test_mode(payload):
        return _suppressed()

    transport = transport_factory(connection)
    query = list(operation_input.get("query") or [])
    page, per_page = _requested_page(query)
    url = transport.build_url(row, operation_input["path_values"], query)
    purpose = f"{row.provider} REST {row.operation_id}"

    if row.shape == "media_create":
        streamer_kwargs = (
            {"artifact_streamer": artifact_streamer} if artifact_streamer is not None else {}
        )
        chunks, size, artifact_content_type = media_upload_source(
            payload, operation_input["artifact_handle"], **streamer_kwargs
        )
        content_type = operation_input["content_type"]
        if content_type == "application/octet-stream" and artifact_content_type:
            content_type = artifact_content_type
        fields = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in (operation_input.get("body") or {}).items()
        }
        response = transport.request_multipart(
            row,
            url,
            filename=operation_input["filename"],
            content_type=content_type,
            chunks=chunks,
            size=size,
            fields=fields,
            purpose=purpose,
        )
    else:
        body: Any = None
        if row.shape == "batch":
            members = batch_members(row)
            body = validation.batch_body(
                {member: operation_input.get(f"{member}_items") or [] for member in members}
            )
            if not body:
                # Nothing to push this run. Sending an empty batch would only make
                # the site reject it, so report the no-op instead of failing the
                # workflow on the ordinary idempotent case.
                return _ok(
                    {
                        "data": {member: [] for member in members},
                        "http_status": 200,
                        "external_effect_status": "succeeded",
                        "definitely_no_external_effect": True,
                    }
                )
        elif row.shape in {"create", "update", "action", "read_post"}:
            body = operation_input.get("body")
        response = transport.request_json(
            row,
            url,
            body=body,
            mutating=row.has_external_effect,
            purpose=purpose,
        )

    # The site's record is forwarded to the workflow as-is, so a property this
    # version never returns is dropped here, before anything is serialised.
    body = sanitized_response_body(row, response.body)
    if row.shape == "batch":
        body = _compact_product_batch_body(row, body, members=batch_members(row))
        rejected = _batch_rejection_response(
            body,
            members=batch_members(row),
            http_status=response.status,
        )
        if rejected is not None:
            return rejected
    if row.shape == "list":
        if not isinstance(body, list):
            raise ExtensionError(
                errors.UPSTREAM_FAILURE, "The site returned an unexpected response shape"
            )
        result: dict[str, Any] = {
            "items": body,
            "pagination": pagination_from_headers(response.headers, page=page, per_page=per_page),
            "http_status": response.status,
        }
    else:
        result = {"data": body, "http_status": response.status}
    if row.has_external_effect:
        result["external_effect_status"] = "succeeded"
        result["definitely_no_external_effect"] = False
    return _ok(result)


def _compact_product_batch_body(
    row: Operation,
    body: Any,
    *,
    members: list[str],
) -> Any:
    """Return bounded command receipts for bulk product mutations.

    WooCommerce answers a stock-only batch with complete catalogue records,
    including descriptions, media and attributes. Repeating those records in
    workflow checkpoints makes a 10,000-item update consume gigabytes of worker
    memory. Callers of the batch command need stable identifiers, the changed
    commercial fields and per-item errors; full records remain available from
    the dedicated get/list operations.
    """
    if row.operation_id != _PRODUCT_BATCH_OPERATION_ID or not isinstance(body, Mapping):
        return body

    compact: dict[str, list[Any]] = {}
    for member in members:
        entries = body.get(member)
        if not isinstance(entries, list):
            continue
        receipts: list[Any] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                receipts.append(entry)
                continue
            receipt: dict[str, Any] = {}
            for field in _PRODUCT_BATCH_RECEIPT_FIELDS:
                value = entry.get(field)
                if field not in entry:
                    continue
                if isinstance(value, str):
                    receipt[field] = value[:512]
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    receipt[field] = value
                elif value is None:
                    receipt[field] = None
            error = entry.get("error")
            if isinstance(error, Mapping):
                error_receipt: dict[str, Any] = {}
                code = error.get("code")
                message = error.get("message")
                if isinstance(code, str):
                    error_receipt["code"] = code[:256]
                if isinstance(message, str):
                    error_receipt["message"] = message[:1024]
                data = error.get("data")
                if isinstance(data, Mapping):
                    error_data = {
                        key: value
                        for key in ("status", "resource_id")
                        if (value := data.get(key)) is None
                        or (isinstance(value, (str, int, float)) and not isinstance(value, bool))
                    }
                    if error_data:
                        error_receipt["data"] = error_data
                receipt["error"] = error_receipt
            receipts.append(receipt)
        compact[member] = receipts
    return compact


def _batch_rejection_response(
    body: Any,
    *,
    members: list[str],
    http_status: int,
) -> dict[str, Any] | None:
    """Fail a native batch when WooCommerce rejected any individual item.

    WooCommerce reports per-item failures inside an HTTP 200 response. Treating
    that envelope as a successful external effect makes an entirely rejected
    import look completed. Keep the provider's bounded result for diagnostics,
    but make the action fail. A mixed result is known (not ambiguous), and its
    successful rows mean the request did have an external effect.
    """
    if not isinstance(body, Mapping):
        return None
    failed_items = 0
    succeeded_items = 0
    for member in members:
        entries = body.get(member)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping) and isinstance(entry.get("error"), Mapping):
                failed_items += 1
            else:
                succeeded_items += 1
    if failed_items == 0:
        return None

    message = "WooCommerce rejected one or more batch items"
    definitely_no_external_effect = succeeded_items == 0
    result = {
        "data": body,
        "http_status": http_status,
        "external_effect_status": "failed",
        "definitely_no_external_effect": definitely_no_external_effect,
    }
    return {
        "ok": False,
        "result": result,
        "error_code": errors.UPSTREAM_VALIDATION_FAILED,
        "error": message,
        "errors": [{"code": errors.UPSTREAM_VALIDATION_FAILED, "message": message}],
        "external_effect_status": "failed",
        "definitely_no_external_effect": definitely_no_external_effect,
    }


def _requested_page(query: list[tuple[str, str]]) -> tuple[int | None, int | None]:
    """Echo back the native pagination the caller asked for, when it did."""
    values = dict(query)

    def _as_int(name: str) -> int | None:
        raw = values.get(name)
        return int(raw) if isinstance(raw, str) and raw.isdigit() else None

    return _as_int("page"), _as_int("per_page")


def _test_mode(payload: Mapping[str, Any]) -> bool:
    runtime_context = payload.get("runtime_context")
    if not isinstance(runtime_context, Mapping):
        return False
    value = runtime_context.get("test_mode", False)
    if not isinstance(value, bool):
        raise ExtensionError(errors.INVALID_PAYLOAD, "runtime_context.test_mode must be boolean")
    return value


def _ok(result: Mapping[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "result": dict(result),
        "error_code": None,
        "error": None,
        "errors": [],
    }
    if "external_effect_status" in result:
        response["external_effect_status"] = result["external_effect_status"]
        response["definitely_no_external_effect"] = result["definitely_no_external_effect"]
    return response


def _suppressed() -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "data": None,
            "http_status": 0,
            "test_mode_status": "suppressed",
            "external_effect_status": "suppressed",
            "definitely_no_external_effect": True,
        },
        "error_code": None,
        "error": None,
        "errors": [],
        "external_effect_status": "suppressed",
        "definitely_no_external_effect": True,
    }


__all__ = [
    "TEST_CONNECTION_INPUT_FIELDS",
    "TEST_CONNECTION_RESULT_FIELDS",
    "VALIDATE_SETTINGS_CHECKS",
    "VALIDATE_SETTINGS_INPUT_FIELDS",
    "VALIDATE_SETTINGS_RESULT_FIELDS",
    "handle_runtime",
]
