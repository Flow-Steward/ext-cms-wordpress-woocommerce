"""Typed input validation, applied before any outbound I/O.

Every operation accepts exactly the parameters the official reference documents
for its route. An undocumented top-level field — ``acf``, ``lang``, a custom
post type key, anything a plugin might add — is refused here, before a request
is built, and the same rule is applied to each item of a batch payload.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import errors
from .catalog import Operation
from .errors import ExtensionError
from .io_shapes import (
    MAX_ARRAY_ITEMS,
    MAX_BATCH_ITEMS,
    MAX_PATH_SEGMENT_LENGTH,
    MAX_QUERY_TEXT_LENGTH,
    MAX_RECORD_ID,
    MODE_CREATE,
    MODE_READ,
    MODE_UPDATE,
    batch_item_fields,
    body_field_names,
    documented_field,
    input_field_names,
    query_field_names,
    required_input_field_names,
    write_mode,
)
from .parameters import NESTED_CREATE_MODELS, NESTED_MODELS, NESTED_UPDATE_MODELS
from .transport import MAX_QUERY_BYTES, MAX_QUERY_PAIRS

#: Whole-request ceiling. Individual text fields are not capped: WordPress
#: post content and WooCommerce product descriptions are legitimately long.
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_DEPTH = 12
MAX_OBJECT_KEYS = 500
MAX_CONNECTION_REF_LENGTH = 256
MAX_FILENAME_BYTES = 255

#: Batch bodies may only ever carry these members. ``delete`` is never built.
ALLOWED_BATCH_MEMBERS: frozenset[str] = frozenset({"create", "update"})
FORBIDDEN_BATCH_MEMBERS: frozenset[str] = frozenset({"delete"})

#: Writing one of these moves a record to the trash. Destructiveness is judged
#: by outcome rather than by HTTP method, so a write carrying it is refused even
#: though the route itself is a documented POST or PUT. Reading and filtering
#: trashed records remain available.
DESTRUCTIVE_STATUS_VALUES: frozenset[str] = frozenset({"trash"})

_CONTENT_TYPE_RE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]{1,127}/[A-Za-z0-9!#$&^_.+-]{1,127}$")


def connection_ref(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > MAX_CONNECTION_REF_LENGTH or "/" in text:
        raise ExtensionError(errors.INVALID_PAYLOAD, "connection_ref is required")
    return text


def path_value(name: str, kind: str, value: Any) -> str:
    """Validate a path parameter against exactly what the manifest publishes.

    The published schema is a bounded string, because the executable schema
    subset cannot express a segment pattern. Enforcing a stricter regex here
    would mean the contract and the runtime disagree, so the check is the
    published one. Safety does not rest on the shape: the transport
    percent-encodes the segment and then refuses any URL that leaves the
    connection's site or contains a traversal.
    """
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_RECORD_ID:
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a non-negative integer")
        return str(value)
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_PATH_SEGMENT_LENGTH:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} is not a valid path segment")
    return value


# -- Typed value checking -------------------------------------------------


def _bounded_json(value: Any, *, field: str, depth: int = 0) -> Any:
    if depth > MAX_PAYLOAD_DEPTH:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} is nested too deeply")
    if isinstance(value, Mapping):
        if len(value) > MAX_OBJECT_KEYS:
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} has too many entries")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} has an invalid key")
            _bounded_json(item, field=field, depth=depth + 1)
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} has too many items")
        return [_bounded_json(item, field=field, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} is not JSON serializable")


def _text_value(value: Any, field: dict[str, Any], *, in_query: bool = False) -> str:
    name = field["name"]
    if isinstance(value, bool) or not isinstance(value, str):
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a string")
    if in_query and len(value) > MAX_QUERY_TEXT_LENGTH:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} is too long for a query parameter")
    # No character filter here: the manifest cannot express one, and a string
    # is carried safely by JSON encoding. The whole-request size limit bounds it.
    enum = field.get("enum")
    if enum and value not in enum:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be one of the documented values")
    return value


def _nested_object(
    value: Mapping[str, Any], field: dict[str, Any], *, mode: str = MODE_READ
) -> dict[str, Any]:
    """Check a sub-structure against its documented model.

    A request is checked against the write model, which omits the members the
    API computes: ``categories[].name`` and ``line_items[].price`` are returned
    by WooCommerce, never sent to it.
    """
    source = {
        MODE_CREATE: NESTED_CREATE_MODELS,
        MODE_UPDATE: NESTED_UPDATE_MODELS,
    }.get(mode, NESTED_MODELS)
    model = source.get(str(field.get("nested") or ""))
    if model is None:
        return _bounded_json(value, field=field["name"])
    allowed = {entry["name"] for entry in model}
    if set(value) - allowed:
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            f"{field['name']} does not accept the supplied field",
        )
    required = {entry["name"] for entry in model if entry.get("required")}
    if required - set(value):
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            f"{field['name']} entries are missing a required field",
        )
    by_name = {entry["name"]: entry for entry in model}
    return {key: typed_value(item, by_name[key], mode=mode) for key, item in value.items()}


_UNION_CHECKS = {
    "null": lambda value: value is None,
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, Mapping),
}


def typed_value(
    value: Any, field: dict[str, Any], *, in_query: bool = False, mode: str = MODE_READ
) -> Any:
    """Check one supplied value against its documented type.

    A documented union such as "string or null" accepts any of its members: the
    WordPress reference allows clearing a post date by sending null, and a
    WooCommerce setting value is documented as mixed.
    """
    name = field["name"]
    value_type = str(field["value_type"])
    union = field.get("union_types") or []
    if len(union) > 1:
        for word in union:
            check = _UNION_CHECKS.get(word)
            if check and check(value):
                if word == "object":
                    return _nested_object(value, field, mode=mode)
                if word == "array":
                    return _typed_array(value, field, in_query=in_query, mode=mode)
                return (
                    _bounded_json(value, field=name)
                    if word != "string"
                    else _text_value(value, {**field, "enum": field.get("enum")}, in_query=in_query)
                )
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            f"{name} must be one of the documented types: {', '.join(union)}",
        )
    if field.get("rendered"):
        if isinstance(value, str):
            return _text_value(value, {**field, "enum": None}, in_query=in_query)
        if isinstance(value, Mapping):
            return _bounded_json(value, field=name)
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a string or an object")
    if value_type == "json":
        # A native mixed value: any bounded JSON is legitimate here.
        return _bounded_json(value, field=name)
    if value_type == "text":
        return _text_value(value, field, in_query=in_query)
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be an integer")
        return value
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a number")
        return value
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a boolean")
        return value
    if value_type == "array":
        return _typed_array(value, field, in_query=in_query, mode=mode)
    if value_type == "object":
        if not isinstance(value, Mapping):
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be an object")
        return _nested_object(value, field, mode=mode)
    raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} has an unsupported type")


# -- Query and body assembly ---------------------------------------------


def _query_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return str(value)


def query_pairs(values: Mapping[str, Any], fields: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Flatten validated query values into ordered, encodable pairs.

    An array is serialized as ``name[]=a&name[]=b``. Repeating the bare key
    instead would lose every value but the last: WordPress and WooCommerce parse
    query strings with PHP, and ``include=4&include=9`` arrives as ``"9"``.
    """
    pairs: list[tuple[str, str]] = []
    for field in fields:
        name = field["name"]
        if name not in values:
            continue
        value = values[name]
        if isinstance(value, list):
            pairs.extend((f"{name}[]", _query_scalar(item)) for item in value)
        else:
            pairs.append((name, _query_scalar(value)))
    if len(pairs) > MAX_QUERY_PAIRS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The query has too many values")
    if sum(len(key) + len(item) + 2 for key, item in pairs) > MAX_QUERY_BYTES:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The query is too long")
    return pairs


def batch_items(value: Any, *, field: str, row: Operation) -> list[dict[str, Any]]:
    """Validate every batch entry against that member's documented write fields.

    ``create_items`` and ``update_items`` are checked against different closed
    schemas: an update entry must carry the ID of the record it changes, and a
    create entry must carry whatever the reference marks mandatory.
    """
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_BATCH_ITEMS:
        raise ExtensionError(
            errors.INVALID_PAYLOAD, f"{field} must be a list of at most {MAX_BATCH_ITEMS} items"
        )
    member = "update" if field == "update_items" else "create"
    fields = batch_item_fields(row, member)
    documented = {entry["name"]: entry for entry in fields}
    required = {entry["name"] for entry in fields if entry.get("required")}
    items: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} entries must be objects")
        if set(entry) - set(documented):
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"{field} entries do not accept the supplied field",
            )
        if required - set(entry):
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"{field} entries are missing a required field",
            )
        items.append(
            {key: _write_value(item, documented[key], mode=member) for key, item in entry.items()}
        )
    return items


def _typed_array(value: Any, field: dict[str, Any], *, in_query: bool, mode: str) -> list[Any]:
    """Check every element of an array against its documented element type."""
    name = field["name"]
    if not isinstance(value, list) or len(value) > MAX_ARRAY_ITEMS:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} must be a bounded list")
    item_type = str(field.get("item_type") or "text")
    item_field = {
        "name": name,
        "value_type": item_type,
        "enum": field.get("enum"),
        "nested": field.get("nested", ""),
    }
    if item_type == "object":
        entries = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ExtensionError(errors.INVALID_PAYLOAD, f"{name} entries must be objects")
            entries.append(_nested_object(item, item_field, mode=mode))
        return entries
    return [typed_value(item, item_field, in_query=in_query, mode=mode) for item in value]


def _write_value(value: Any, field: dict[str, Any], *, mode: str) -> Any:
    """Check a value bound for a request body.

    The destructive check applies only to the fields whose documented status
    enumeration actually offered the value. A product named "Trash" or a post
    titled "Trash" is ordinary content and must go through untouched.
    """
    guarded = {str(item).lower() for item in field.get("destructive_values") or ()}
    if guarded and isinstance(value, str) and value.strip().lower() in guarded:
        raise ExtensionError(
            errors.UNSUPPORTED_OPERATION,
            "Moving a record to the trash is not supported by this extension",
        )
    return typed_value(value, field, mode=mode)


def batch_body(members: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build a batch body that can only ever carry ``create`` and ``update``.

    An all-empty batch returns an empty body rather than raising: an idempotent
    catalogue sync legitimately has nothing to push on a run where nothing
    changed, and the caller turns an empty body into a no-op without contacting
    the site.
    """
    body: dict[str, Any] = {member: entries for member, entries in members.items() if entries}
    if not body:
        return {}
    assert_no_delete_member(body)
    _assert_serialized_size(body)
    return body


def assert_no_delete_member(body: Mapping[str, Any]) -> None:
    """Refuse a batch body that carries a destructive member."""
    members = set(body)
    if members & FORBIDDEN_BATCH_MEMBERS or not members <= ALLOWED_BATCH_MEMBERS:
        raise ExtensionError(
            errors.UNSUPPORTED_OPERATION, "Batch delete payloads are not supported"
        )


def _assert_serialized_size(body: Mapping[str, Any]) -> None:
    if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The request body exceeds its safe limit")


def filename(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    if (
        not text
        or not 1 <= len(text.encode("utf-8")) <= MAX_FILENAME_BYTES
        or text in {".", ".."}
        or "/" in text
        or "\\" in text
        or text != text.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise ExtensionError(errors.INVALID_PAYLOAD, "filename must be a safe basename")
    return text


def content_type(value: Any, *, default: str = "application/octet-stream") -> str:
    if value is None:
        return default
    text = value.strip() if isinstance(value, str) else ""
    if _CONTENT_TYPE_RE.fullmatch(text) is None:
        raise ExtensionError(errors.INVALID_PAYLOAD, "content_type is not a valid media type")
    return text


def validated_input(row: Operation, raw: Any) -> dict[str, Any]:
    """Validate one operation's declared inputs before anything leaves the process."""
    if not isinstance(raw, Mapping):
        raise ExtensionError(errors.INVALID_PAYLOAD, "action.input must be an object")
    declared = input_field_names(row)
    supplied = set(raw)
    if supplied - declared:
        raise ExtensionError(
            errors.INVALID_PAYLOAD, "The operation does not accept the supplied field"
        )
    if required_input_field_names(row) - supplied:
        raise ExtensionError(errors.INVALID_PAYLOAD, "A required field is missing")

    result: dict[str, Any] = {"connection_ref": connection_ref(raw.get("connection_ref"))}
    result["path_values"] = {
        name: path_value(name, kind, raw.get(name)) for name, kind in row.path_params
    }

    if row.shape == "media_create":
        result["artifact_handle"] = connection_ref(raw.get("artifact_handle"))
        result["filename"] = filename(raw.get("filename"))
        result["content_type"] = content_type(raw.get("content_type"))

    if row.shape == "batch":
        result["create_items"] = batch_items(raw.get("create_items"), field="create_items", row=row)
        result["update_items"] = batch_items(raw.get("update_items"), field="update_items", row=row)
        result["query"] = []
        result["body"] = None
        return result

    query_values: dict[str, Any] = {}
    for name in query_field_names(row):
        if name in raw:
            field = documented_field(row, name)
            if field is not None:
                query_values[name] = typed_value(raw[name], field, in_query=True)
    from .parameters import QUERY_FIELDS

    result["query"] = query_pairs(query_values, QUERY_FIELDS.get(row.operation_id, []))

    body: dict[str, Any] = {}
    for name in body_field_names(row):
        if name in raw:
            field = documented_field(row, name)
            if field is not None:
                body[name] = _write_value(raw[name], field, mode=write_mode(row))
    if body:
        _assert_serialized_size(body)
    result["body"] = body or None
    return result


__all__ = [
    "ALLOWED_BATCH_MEMBERS",
    "FORBIDDEN_BATCH_MEMBERS",
    "MAX_PAYLOAD_BYTES",
    "assert_no_delete_member",
    "batch_body",
    "batch_items",
    "connection_ref",
    "content_type",
    "filename",
    "path_value",
    "query_pairs",
    "typed_value",
    "validated_input",
]
