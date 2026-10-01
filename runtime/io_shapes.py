"""Typed input/output contracts for every declared operation.

Each operation exposes exactly the parameters the official reference documents
for its route, as individually typed fields. There is no free-form ``query`` or
``payload`` object: a field that is not documented for that operation does not
exist in its contract and is refused before outbound I/O.

The published manifests, the declarative step forms, the UI action manifest, and
the runtime validator all read their field lists from this one module, so a
field cannot appear in one surface and be missing from another.
"""

from __future__ import annotations

from typing import Any

from .catalog import Operation
from .parameters import (
    BATCH_CAPABILITIES,
    BATCH_ITEM_FIELDS,
    BODY_FIELDS,
    NESTED_CREATE_MODELS,
    NESTED_MODELS,
    NESTED_UPDATE_MODELS,
    QUERY_FIELDS,
    RESPONSE_FIELDS,
    RESPONSE_KINDS,
)

#: Which model a schema is built from. A create cannot name a sub-entry that
#: does not exist yet; an update must.
MODE_READ = "read"
MODE_CREATE = "create"
MODE_UPDATE = "update"

KIND_OBJECT = "object"
KIND_OBJECT_LIST = "object_list"
KIND_PRIMITIVE_LIST = "primitive_list"
KIND_KEYED_MAP = "keyed_map"
KIND_BATCH_GROUPS = "batch_groups"

CONNECTION_REF_FIELD: dict[str, Any] = {
    "name": "connection_ref",
    "value_type": "connection_ref",
    "required": True,
}

#: A query string has to stay short enough to send; a request body does not.
#: Post content, page content and product descriptions are routinely tens of
#: thousands of characters, so body text carries no per-field character cap and
#: is bounded by the whole-request limit instead.
MAX_QUERY_TEXT_LENGTH = 2048
MAX_ARRAY_ITEMS = 200
MAX_BATCH_ITEMS = 100

#: Native pagination inputs, when the documented route supports them.
PAGINATION_FIELDS: frozenset[str] = frozenset({"page", "per_page", "offset"})

PAGINATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "total": {"type": ["integer", "null"]},
        "total_pages": {"type": ["integer", "null"]},
        "page": {"type": ["integer", "null"]},
        "per_page": {"type": ["integer", "null"]},
        "next_link": {"type": ["string", "null"]},
        "previous_link": {"type": ["string", "null"]},
        "has_more": {"type": "boolean"},
    },
}

EFFECT_OUTPUTS: tuple[dict[str, Any], ...] = (
    {"name": "external_effect_status", "value_type": "text"},
    {"name": "definitely_no_external_effect", "value_type": "boolean"},
)

_PATH_PARAM_VALUE_TYPES = {
    "integer": "integer",
    "slug": "text",
    "namespaced_slug": "text",
    "plugin_file": "text",
}

_JSON_TYPES = {
    "text": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}

#: A field the native API leaves as any JSON value. Declared as an explicit
#: union so the published contract and the runtime agree on what is accepted.
MIXED_JSON_TYPES: list[str] = [
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "null",
]

_WIDGET_TYPES = {
    "text": "text",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "object": "json",
    "array": "json",
    "json": "json",
    "artifact_handle": "artifact_picker",
}

_ACTION_PARAMETER_TYPES = {
    "text": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "object": "object",
    "array": "array",
    "json": "json",
    "connection_ref": "connection_ref",
    "artifact_handle": "artifact_handle",
}


#: Longest path segment accepted, in characters.
MAX_PATH_SEGMENT_LENGTH = 200

#: Largest record identifier accepted. Published as well as enforced: a bound
#: the runtime applies but the manifest omits is a contract the caller cannot
#: see. 2**53 is the largest integer a JSON number represents exactly.
MAX_RECORD_ID = 2**53

_PRODUCT_BATCH_OPERATION_ID = "wc_batch_products"
_PRODUCT_BATCH_RECEIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "sku": {"type": "string"},
        "status": {"type": "string"},
        "stock_status": {"type": "string"},
        "stock_quantity": {"type": ["integer", "null"]},
        "regular_price": {"type": "string"},
        "price": {"type": "string"},
        "error": {"type": "object"},
    },
}


def path_param_field(name: str, kind: str) -> dict[str, Any]:
    """Manifest entry for one path parameter.

    The platform's executable schema subset has no ``pattern``, so a route's
    segment shape cannot be published as a constraint. Rather than publish a
    looser contract than the runtime enforces, the runtime enforces exactly what
    is published here: a bounded string. What keeps the request safe is not a
    shape regex but the transport, which percent-encodes each segment and then
    refuses any URL that leaves the connection's own site or contains a
    traversal.
    """
    field: dict[str, Any] = {
        "name": name,
        "value_type": _PATH_PARAM_VALUE_TYPES[kind],
        "required": True,
    }
    if kind == "integer":
        field["schema"] = {"type": "integer", "minimum": 0, "maximum": MAX_RECORD_ID}
    else:
        field["schema"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PATH_SEGMENT_LENGTH,
        }
    return field


def _with_union(schema: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
    """Widen a schema to the full documented union, e.g. "string or null"."""
    union = field.get("union_types") or []
    if len(union) > 1:
        schema = dict(schema)
        schema["type"] = list(union)
    return schema


def field_schema(
    field: dict[str, Any],
    *,
    closed: bool = True,
    in_query: bool = False,
    mode: str = MODE_READ,
) -> dict[str, Any]:
    """JSON Schema for one documented parameter.

    ``closed`` marks a documented nested structure as rejecting unknown keys,
    which is what the runtime enforces on input. Response schemas are built with
    ``closed=False``: they describe the documented record without refusing extra
    fields a site or a future release may add.
    """
    value_type = str(field["value_type"])
    if field.get("rendered"):
        # WordPress accepts the raw string or the {raw, rendered} object here.
        return {"type": ["string", "object"]}
    if value_type == "json":
        return {"type": list(MIXED_JSON_TYPES)}
    if value_type == "text":
        if field.get("enum"):
            return _with_union({"type": "string", "enum": list(field["enum"])}, field)
        schema: dict[str, Any] = {"type": "string"}
        if in_query:
            schema["maxLength"] = MAX_QUERY_TEXT_LENGTH
        return _with_union(schema, field)
    if value_type == "array":
        declared_item = str(field.get("item_type") or "text")
        item_type = "json" if declared_item == "json" else _JSON_TYPES.get(declared_item, "string")
        items: dict[str, Any] = {"type": item_type}
        if field.get("enum") and item_type == "string":
            items = {"type": "string", "enum": list(field["enum"])}
        elif item_type == "object":
            items = _nested_schema(field, closed=closed, mode=mode) or {"type": "object"}
        elif item_type == "json":
            items = {"type": list(MIXED_JSON_TYPES)}
        elif item_type == "string" and in_query:
            items = {"type": "string", "maxLength": MAX_QUERY_TEXT_LENGTH}
        return _with_union({"type": "array", "maxItems": MAX_ARRAY_ITEMS, "items": items}, field)
    if value_type == "object":
        nested = _nested_schema(field, closed=closed, mode=mode)
        return _with_union(nested or {"type": "object"}, field)
    return _with_union({"type": _JSON_TYPES[value_type]}, field)


def _nested_schema(
    field: dict[str, Any], *, closed: bool, mode: str = MODE_READ
) -> dict[str, Any] | None:
    """Schema for a documented sub-structure, or None when the API leaves it open.

    A container the official API defines as open-ended — WordPress ``meta``,
    WooCommerce ``meta_data`` entries' ``value`` — has no documented model and
    stays open.
    """
    source = {
        MODE_CREATE: NESTED_CREATE_MODELS,
        MODE_UPDATE: NESTED_UPDATE_MODELS,
    }.get(mode, NESTED_MODELS)
    nested = source.get(str(field.get("nested") or ""))
    if not nested:
        return None
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            entry["name"]: field_schema(entry, closed=closed, mode=mode) for entry in nested
        },
    }
    # A member the model marks required is required in the entry too. Without
    # this the published schema accepts `[{}]` for a documented line item.
    required = [entry["name"] for entry in nested if entry.get("required")]
    if required:
        schema["required"] = required
    if closed:
        schema["additionalProperties"] = False
    return schema


def documented_input(
    field: dict[str, Any], *, in_query: bool = False, mode: str = MODE_READ
) -> dict[str, Any]:
    """Manifest input entry for one documented parameter."""
    entry: dict[str, Any] = {
        "name": field["name"],
        "value_type": field["value_type"],
        "required": bool(field.get("required")),
        "schema": field_schema(field, closed=True, in_query=in_query, mode=mode),
    }
    if "default" in field:
        entry["schema"]["default"] = field["default"]
    return entry


def batch_members(row: Operation) -> list[str]:
    """Members this batch endpoint documents, in payload order.

    Not every batch endpoint offers both: WooCommerce setting options are keyed
    by slug and can only be updated.
    """
    declared = BATCH_CAPABILITIES.get(row.operation_id, {}).get("members")
    return list(declared) if declared else ["create", "update"]


def batch_item_fields(row: Operation, member: str) -> list[dict[str, Any]]:
    """Documented write fields for one member of a batch payload."""
    return BATCH_ITEM_FIELDS.get(row.operation_id, {}).get(member, [])


def write_mode(row: Operation) -> str:
    """Which nested model a request body for this operation is built from."""
    return MODE_UPDATE if row.shape == "update" else MODE_CREATE


def _batch_item_schema(row: Operation, member: str) -> dict[str, Any]:
    """Closed array schema for the create or update member of a batch payload.

    The two members are not the same shape: an update entry must name the record
    it changes, and a field that is mandatory when creating is optional when
    updating.
    """
    fields = batch_item_fields(row, member)
    item: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            entry["name"]: field_schema(entry, closed=True, mode=member) for entry in fields
        },
    }
    required = [entry["name"] for entry in fields if entry.get("required")]
    if required:
        item["required"] = required
    return {"type": "array", "maxItems": MAX_BATCH_ITEMS, "items": item}


def operation_inputs(row: Operation) -> list[dict[str, Any]]:
    """Every declared input field for one operation, connection first."""
    fields: list[dict[str, Any]] = [dict(CONNECTION_REF_FIELD)]
    fields.extend(path_param_field(name, kind) for name, kind in row.path_params)
    if row.shape == "media_create":
        fields.append(
            {"name": "artifact_handle", "value_type": "artifact_handle", "required": True}
        )
        fields.append(
            {
                "name": "filename",
                "value_type": "text",
                "required": True,
                "schema": {"type": "string", "minLength": 1, "maxLength": 255},
            }
        )
        fields.append(
            {
                "name": "content_type",
                "value_type": "text",
                "required": False,
                "schema": {"type": "string", "minLength": 3, "maxLength": 255},
            }
        )
    if row.shape == "batch":
        for member in batch_members(row):
            fields.append(
                {
                    "name": f"{member}_items",
                    "value_type": "array",
                    "required": False,
                    "schema": _batch_item_schema(row, member),
                }
            )
        return fields
    fields.extend(
        documented_input(entry, in_query=True, mode=MODE_READ)
        for entry in QUERY_FIELDS.get(row.operation_id, [])
    )
    fields.extend(
        documented_input(entry, mode=write_mode(row))
        for entry in BODY_FIELDS.get(row.operation_id, [])
    )
    return fields


def _record_schema(row: Operation) -> dict[str, Any] | None:
    """Documented response record shape, or None when the docs publish none."""
    documented = RESPONSE_FIELDS.get(row.operation_id, [])
    if not documented:
        return None
    # Deliberately not closed: a site may add fields, and this describes the
    # documented record rather than rejecting an upstream response.
    return {
        "type": "object",
        "properties": {entry["name"]: field_schema(entry, closed=False) for entry in documented},
    }


def response_kind(row: Operation) -> str:
    """How the top level of this operation's response is shaped."""
    return RESPONSE_KINDS.get(row.operation_id, KIND_OBJECT)


def operation_outputs(row: Operation) -> list[dict[str, Any]]:
    """Every declared output field for one operation.

    The record fields alone do not describe a response: the same table backs a
    single record, a list of records, an object keyed by slug and the grouped
    answer to a batch. The declared kind decides the top-level shape.
    """
    record = _record_schema(row)
    kind = response_kind(row)

    if kind == KIND_OBJECT_LIST:
        items = record if record is not None else {"type": "object"}
        outputs: list[dict[str, Any]] = [
            {
                "name": "items",
                "value_type": "array",
                "schema": {"type": "array", "items": items},
            },
            {"name": "pagination", "value_type": "object", "schema": dict(PAGINATION_SCHEMA)},
            {"name": "http_status", "value_type": "integer"},
        ]
    elif kind == KIND_PRIMITIVE_LIST:
        documented = RESPONSE_FIELDS.get(row.operation_id) or [
            {"name": "value", "value_type": "text"}
        ]
        outputs = [
            {
                "name": "items",
                "value_type": "array",
                "schema": {
                    "type": "array",
                    "items": field_schema(documented[0], closed=False),
                },
            },
            {"name": "pagination", "value_type": "object", "schema": dict(PAGINATION_SCHEMA)},
            {"name": "http_status", "value_type": "integer"},
        ]
    elif kind == KIND_KEYED_MAP:
        # WordPress answers with {"post": {...}, "page": {...}}: the record is
        # the value of every key, and the keys are site-defined slugs.
        schema: dict[str, Any] = {"type": "object"}
        if record is not None:
            schema["additionalProperties"] = record
        outputs = [
            {"name": "data", "value_type": "object", "schema": schema},
            {"name": "http_status", "value_type": "integer"},
        ]
    elif kind == KIND_BATCH_GROUPS:
        grouped: dict[str, Any] = {"type": "object", "properties": {}}
        batch_record = (
            _PRODUCT_BATCH_RECEIPT_SCHEMA
            if row.operation_id == _PRODUCT_BATCH_OPERATION_ID
            else record
        )
        for member in batch_members(row):
            grouped["properties"][member] = (
                {"type": "array", "items": batch_record} if batch_record else {"type": "array"}
            )
        outputs = [
            {"name": "data", "value_type": "object", "schema": grouped},
            {"name": "http_status", "value_type": "integer"},
        ]
    else:
        data_field: dict[str, Any] = {"name": "data", "value_type": "json"}
        if record is not None:
            data_field = {"name": "data", "value_type": "object", "schema": record}
        outputs = [data_field, {"name": "http_status", "value_type": "integer"}]

    if row.has_external_effect:
        outputs.extend(dict(field) for field in EFFECT_OUTPUTS)
    return outputs


def input_field_names(row: Operation) -> frozenset[str]:
    return frozenset(str(field["name"]) for field in operation_inputs(row))


def required_input_field_names(row: Operation) -> frozenset[str]:
    return frozenset(
        str(field["name"]) for field in operation_inputs(row) if field.get("required") is True
    )


def query_field_names(row: Operation) -> frozenset[str]:
    return frozenset(entry["name"] for entry in QUERY_FIELDS.get(row.operation_id, []))


def body_field_names(row: Operation) -> frozenset[str]:
    return frozenset(entry["name"] for entry in BODY_FIELDS.get(row.operation_id, []))


def documented_field(row: Operation, name: str) -> dict[str, Any] | None:
    for entry in QUERY_FIELDS.get(row.operation_id, []):
        if entry["name"] == name:
            return entry
    for entry in BODY_FIELDS.get(row.operation_id, []):
        if entry["name"] == name:
            return entry
    return None


#: Fragments of a field name that are not ordinary words.
_LABEL_WORDS = {
    "api": "API",
    "gmt": "GMT",
    "id": "ID",
    "ids": "IDs",
    "ip": "IP",
    "mime": "MIME",
    "sku": "SKU",
    "url": "URL",
    "urls": "URLs",
    "utc": "UTC",
}


def field_label(name: str) -> str:
    """A readable label for a documented field name.

    The builder shows this instead of the wire name, so ``featured_media``
    reads as "Featured media" and ``parent_id`` as "Parent ID" rather than as
    an identifier the author has to decode.
    """
    words = [word for word in str(name).split("_") if word]
    if not words:
        return str(name)
    rendered = [_LABEL_WORDS.get(word.lower(), word.lower()) for word in words]
    first = rendered[0]
    if first == first.lower():
        first = first[:1].upper() + first[1:]
    return " ".join([first, *rendered[1:]])


def step_form_fields(row: Operation) -> list[dict[str, Any]]:
    """Declarative step-form fields, one typed widget per non-connection input."""
    fields: list[dict[str, Any]] = []
    for field in operation_inputs(row):
        name = str(field["name"])
        if name == "connection_ref":
            continue
        value_type = str(field["value_type"])
        schema = field.get("schema") or {}
        enum = schema.get("enum") if isinstance(schema, dict) else None
        entry: dict[str, Any] = {
            "name": name,
            "label": field_label(name),
            "widget_type": "select" if enum else _WIDGET_TYPES[value_type],
        }
        if enum:
            entry["options"] = [{"label": str(value), "value": str(value)} for value in enum]
        if field.get("required") is True:
            entry["required"] = True
        fields.append(entry)
    return fields


def action_parameters(row: Operation) -> list[dict[str, Any]]:
    """UI action parameters, mirroring the operation inputs exactly."""
    return [
        {
            "name": field["name"],
            "type": _ACTION_PARAMETER_TYPES[str(field["value_type"])],
            "required": bool(field.get("required") is True),
        }
        for field in operation_inputs(row)
    ]


def result_field_names(row: Operation) -> list[str]:
    return [str(field["name"]) for field in operation_outputs(row)]


__all__ = [
    "CONNECTION_REF_FIELD",
    "EFFECT_OUTPUTS",
    "MAX_ARRAY_ITEMS",
    "MAX_BATCH_ITEMS",
    "MAX_PATH_SEGMENT_LENGTH",
    "MAX_QUERY_TEXT_LENGTH",
    "MAX_RECORD_ID",
    "MIXED_JSON_TYPES",
    "PAGINATION_FIELDS",
    "PAGINATION_SCHEMA",
    "action_parameters",
    "batch_item_fields",
    "batch_members",
    "body_field_names",
    "documented_field",
    "documented_input",
    "field_label",
    "field_schema",
    "input_field_names",
    "operation_inputs",
    "operation_outputs",
    "query_field_names",
    "required_input_field_names",
    "response_kind",
    "result_field_names",
    "step_form_fields",
]
