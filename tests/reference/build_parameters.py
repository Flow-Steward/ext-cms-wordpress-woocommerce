#!/usr/bin/env python3
"""Derive the typed parameter tables from the committed documentation snapshot.

Reads ``contracts/rest_reference.yaml`` (produced by ``refresh_reference.py``)
and writes ``runtime/parameters.py``: for every declared operation, the exact
documented query fields, body fields, and response fields, with their types,
enumerations, and required flags.

    python tests/reference/build_parameters.py            # rewrite the tables
    python tests/reference/build_parameters.py --check    # fail if they drifted

The chain is docs -> snapshot -> typed tables -> manifests, and each link has a
test. This script is never imported by the runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BUNDLE_ROOT))

SNAPSHOT = BUNDLE_ROOT / "contracts" / "rest_reference.yaml"
TARGET = BUNDLE_ROOT / "runtime" / "parameters.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from markers import is_required, is_response_suppressed  # noqa: E402
from runtime import field_policy  # noqa: E402
from runtime.catalog import REST_OPERATIONS, WORDPRESS  # noqa: E402

TEXT, INTEGER, NUMBER, BOOLEAN, ARRAY, OBJECT, JSON = (
    "text",
    "integer",
    "number",
    "boolean",
    "array",
    "object",
    "json",
)

#: Fields the native API defines as carrying any JSON value. A WooCommerce
#: meta value is a string, number, boolean, object or array depending on what
#: wrote it, so pinning it to string would be wrong.
MIXED_VALUE_FIELDS: frozenset[str] = frozenset({"value"})

#: How the top level of a response is shaped. The record fields alone do not say
#: this: a list of records, an object keyed by slug and a bare list of strings
#: are all built from the same table.
KIND_OBJECT = "object"
KIND_OBJECT_LIST = "object_list"
KIND_PRIMITIVE_LIST = "primitive_list"
KIND_KEYED_MAP = "keyed_map"
KIND_BATCH_GROUPS = "batch_groups"

#: WordPress endpoints that answer with an object keyed by slug rather than a
#: list, e.g. {"post": {...}, "page": {...}}.
KEYED_MAP_OPERATIONS: frozenset[str] = frozenset(
    {
        "wp_get_post_types",
        "wp_get_post_statuses",
        "wp_get_taxonomies",
        "wp_get_menu_locations",
    }
)

#: Endpoints that answer with a bare list of scalars.
PRIMITIVE_LIST_OPERATIONS: dict[str, str] = {
    "wc_list_product_custom_field_names": TEXT,
}

#: Pages that publish several record tables. Without this the first table on the
#: page would be handed to every operation on it, so each report would claim the
#: sales-report shape.
RESPONSE_TABLE_BY_OPERATION: dict[str, str] = {
    "wc_get_sales_report": "sales_report",
    "wc_get_top_sellers_report": "top_sellers_report",
    "wc_get_coupons_totals_report": "coupons_totals",
    "wc_get_customers_totals_report": "customers_totals",
    "wc_get_orders_totals_report": "orders_totals",
    "wc_get_products_totals_report": "products_totals",
    "wc_get_reviews_totals_report": "reviews_totals",
    "wc_list_reports": "data",
    "wc_list_data_resources": "data",
    "wc_list_continents": "continents",
    "wc_get_continent": "continents",
    "wc_list_countries": "countries",
    "wc_get_country": "countries",
    "wc_list_currencies": "currencies",
    "wc_get_currency": "currencies",
    "wc_get_current_currency": "currencies",
    # Two endpoints share a page with a different record, and the page's first
    # property table describes that other record. Reading it publishes the wrong
    # contract entirely: customer fields for a downloads listing, and the
    # created-refund record for a refund preview.
    "wc_list_customer_downloads": "customer_downloads",
    "wc_preview_order_refund": "preview_response",
}

#: Query fields the reference documents in prose for a sub-resource route that
#: has no section of its own. Without this the generator falls back to the parent
#: resource's "List all" section and publishes customer-collection filters such
#: as ``search`` and ``role`` on a downloads listing.
DOCUMENTED_QUERY_FIELDS: dict[str, list[dict[str, Any]]] = {
    "wc_list_customer_downloads": [
        {
            "name": "context",
            "type": "string",
            "description": (
                "Scope under which the request is made; determines fields present in response."
            ),
            # The route's own schema documents `view` alone, unlike the customer
            # collection, which also offers `edit`.
            "options": ["view"],
            "default": "view",
        }
    ],
}

#: The section that describes one entry of a documented request array, for an
#: endpoint whose body is not the resource's own writable properties.
BODY_ITEM_SECTION: dict[str, tuple[str, str, str]] = {
    # (section heading, body field name, model key)
    "wc_preview_order_refund": (
        "preview line item parameters",
        "line_items",
        "preview_line_item",
    ),
}

#: Entries of a documented request array that the reference marks optional in
#: prose. Everything else in such a section is required to identify the line.
OPTIONAL_BODY_ITEM_FIELDS: frozenset[str] = frozenset({"refund_total"})

#: ``breakdown`` is described in prose rather than in a table of its own:
#: "Refund breakdown by item type: products, shipping, and fees, each with
#: items, subtotal, tax, and total."
PREVIEW_BREAKDOWN_SECTION: list[dict[str, Any]] = [
    {"name": "items", "value_type": ARRAY, "item_type": JSON},
    {"name": "subtotal", "value_type": TEXT},
    {"name": "tax", "value_type": TEXT},
    {"name": "total", "value_type": TEXT},
]
PREVIEW_BREAKDOWN: list[dict[str, Any]] = [
    {"name": "products", "value_type": OBJECT, "nested": "order-refunds.preview_breakdown_section"},
    {"name": "shipping", "value_type": OBJECT, "nested": "order-refunds.preview_breakdown_section"},
    {"name": "fees", "value_type": OBJECT, "nested": "order-refunds.preview_breakdown_section"},
]


#: What each batch endpoint actually supports. The default is create plus
#: update with an integer record ID, but setting options are keyed by a string
#: slug such as "woocommerce_currency" and the documented payload only updates.
#: https://developer.woocommerce.com/docs/apis/rest-api/v3/setting-options/
BATCH_CAPABILITIES: dict[str, dict[str, Any]] = {
    "wc_batch_setting_options": {"members": ["update"], "id_type": TEXT},
}
DEFAULT_BATCH_CAPABILITY: dict[str, Any] = {"members": ["create", "update"], "id_type": INTEGER}


def _batch_capability(operation_id: str) -> dict[str, Any]:
    return BATCH_CAPABILITIES.get(operation_id, DEFAULT_BATCH_CAPABILITY)


def _response_kind(row: Any) -> str:
    if row.operation_id in KEYED_MAP_OPERATIONS:
        return KIND_KEYED_MAP
    if row.operation_id in PRIMITIVE_LIST_OPERATIONS:
        return KIND_PRIMITIVE_LIST
    if row.shape == "batch":
        return KIND_BATCH_GROUPS
    if row.shape == "list":
        return KIND_OBJECT_LIST
    return KIND_OBJECT


#: WordPress documents collection arguments without a JSON type. These are the
#: Core-wide collection parameters, whose types are stable across controllers.
WORDPRESS_QUERY_TYPES: dict[str, tuple[str, str]] = {
    "context": (TEXT, ""),
    "page": (INTEGER, ""),
    "per_page": (INTEGER, ""),
    "offset": (INTEGER, ""),
    "search": (TEXT, ""),
    "after": (TEXT, ""),
    "before": (TEXT, ""),
    "modified_after": (TEXT, ""),
    "modified_before": (TEXT, ""),
    "exclude": (ARRAY, INTEGER),
    "include": (ARRAY, INTEGER),
    "order": (TEXT, ""),
    "orderby": (TEXT, ""),
    "slug": (ARRAY, TEXT),
    "status": (ARRAY, TEXT),
    "parent": (ARRAY, INTEGER),
    "parent_exclude": (ARRAY, INTEGER),
    "author": (ARRAY, INTEGER),
    "author_exclude": (ARRAY, INTEGER),
    "author_email": (TEXT, ""),
    "categories": (ARRAY, INTEGER),
    "categories_exclude": (ARRAY, INTEGER),
    "tags": (ARRAY, INTEGER),
    "tags_exclude": (ARRAY, INTEGER),
    "sticky": (BOOLEAN, ""),
    "hide_empty": (BOOLEAN, ""),
    "post": (INTEGER, ""),
    "type": (TEXT, ""),
    "subtype": (TEXT, ""),
    "search_columns": (ARRAY, TEXT),
    "roles": (ARRAY, TEXT),
    "capabilities": (ARRAY, TEXT),
    "who": (TEXT, ""),
    "has_published_posts": (ARRAY, TEXT),
    "media_type": (TEXT, ""),
    "mime_type": (TEXT, ""),
    "password": (TEXT, ""),
    "excerpt_length": (INTEGER, ""),
    "term": (TEXT, ""),
    "taxonomy": (TEXT, ""),
    "keyword": (TEXT, ""),
    "category": (INTEGER, ""),
    "number": (INTEGER, ""),
    "post_status": (TEXT, ""),
    "sidebar": (TEXT, ""),
    "status_exclude": (ARRAY, TEXT),
    "subtypes": (ARRAY, TEXT),
    # Documented arguments WordPress lists without a JSON type and which do not
    # appear in the page's own schema table. Typed here so nothing falls back.
    "meta": (OBJECT, ""),
    "template": (TEXT, ""),
    "namespace": (TEXT, ""),
    "comment_status": (TEXT, ""),
    "ping_status": (TEXT, ""),
    "format": (TEXT, ""),
    "featured_media": (INTEGER, ""),
    "menu_order": (INTEGER, ""),
    "tax_relation": (TEXT, ""),
    "attributes": (OBJECT, ""),
    "post_id": (INTEGER, ""),
}

#: Documented WooCommerce type words mapped onto the platform value types.
WOOCOMMERCE_TYPES: dict[str, str] = {
    "integer": INTEGER,
    "string": TEXT,
    "date-time": TEXT,
    "boolean": BOOLEAN,
    "array": ARRAY,
    "object": OBJECT,
    "number": NUMBER,
    "float": NUMBER,
    "mixed": JSON,
    "null": TEXT,
}

#: WooCommerce documents these action payloads only in its request examples,
#: not in a parameter table. Sourced from
#: https://developer.woocommerce.com/docs/apis/rest-api/v3/order-actions/
DOCUMENTED_ACTION_BODIES: dict[str, list[dict[str, Any]]] = {
    "wc_send_order_details": [],
    "wc_send_order_email": [
        {"name": "template_id", "type": "string", "mandatory": True},
        {"name": "email", "type": "string"},
        {"name": "force_email_update", "type": "boolean"},
    ],
    "wc_duplicate_product": [],
}

#: Responses WooCommerce documents in its examples rather than in a properties
#: table. Sourced from the order-actions and product-custom-fields pages.
DOCUMENTED_ACTION_RESPONSES: dict[str, list[dict[str, Any]]] = {
    "wc_send_order_details": [{"name": "message", "type": "string"}],
    "wc_send_order_email": [{"name": "message", "type": "string"}],
    "wc_list_order_email_templates": [
        {"name": "id", "type": "string"},
        {"name": "title", "type": "string"},
        {"name": "description", "type": "string"},
    ],
    # GET /products/custom-fields/names returns a bare array of field names.
    "wc_list_product_custom_field_names": [{"name": "name", "type": "string"}],
}

_SPLIT_RE = re.compile(r"[^a-z0-9]+")

#: A documented description that names IDs identifies an array of integers.
_ID_LIST_RE = re.compile(r"\bids?\b", re.I)

#: Status values that destroy or hide a record. "Destructive" is judged by
#: outcome, not by HTTP method, so these are removed from every write enum.
#: Reading a trashed record, and filtering for one, stay available.
DESTRUCTIVE_STATUS_VALUES: frozenset[str] = frozenset({"trash"})

#: Element types the references do not state, resolved from the controller
#: schemas that WordPress and WooCommerce publish alongside them. Keyed by
#: (provider, page slug, field). A guess by field name is what previously
#: published `block-patterns.categories` as integers when it carries slugs.
#:
#: WordPress: https://developer.wordpress.org/reference/classes/wp_rest_block_types_controller/
#: WooCommerce: https://developer.woocommerce.com/docs/apis/rest-api/v3/system-status/
ARRAY_ITEM_OVERRIDES: dict[tuple[str, str, str], str] = {
    # Term assignments carry term IDs.
    ("wordpress", "posts", "categories"): INTEGER,
    ("wordpress", "posts", "tags"): INTEGER,
    ("wordpress", "post-revisions", "categories"): INTEGER,
    ("wordpress", "post-revisions", "tags"): INTEGER,
    # Block types: parent and ancestor are block names, styles and variations
    # are objects, keywords are plain strings.
    ("wordpress", "block-types", "parent"): TEXT,
    ("wordpress", "block-types", "ancestor"): TEXT,
    ("wordpress", "block-types", "keywords"): TEXT,
    ("wordpress", "block-types", "styles"): OBJECT,
    ("wordpress", "block-types", "variations"): OBJECT,
    ("wordpress", "block-types", "parent_blocks"): TEXT,
    # Pattern categories are slugs, not IDs.
    ("wordpress", "block-patterns", "categories"): TEXT,
    ("wordpress", "block-patterns", "keywords"): TEXT,
    ("wordpress", "block-patterns", "block_types"): TEXT,
    ("wordpress", "block-patterns", "post_types"): TEXT,
    ("wordpress", "pattern-directory-items", "categories"): TEXT,
    ("wordpress", "pattern-directory-items", "keywords"): TEXT,
    # WooCommerce system status lists plugin records, not names.
    ("woocommerce", "system-status", "active_plugins"): OBJECT,
    ("woocommerce", "system-status", "inactive_plugins"): OBJECT,
    ("woocommerce", "system-status", "dropins_mu_plugins"): OBJECT,
    ("woocommerce", "system-status", "pages"): OBJECT,
    ("woocommerce", "system-status", "post_type_counts"): OBJECT,
}

#: A description that names slugs or codes identifies an array of strings.
_SLUG_LIST_RE = re.compile(r"\bslugs?\b|\bcodes?\b|\bkeywords?\b|\bnames?\b", re.I)


def _array_item_type(
    name: str,
    description: str,
    *,
    nested: bool,
    provider: str = "",
    slug: str = "",
) -> str:
    """Element type for a documented array field.

    The references declare ``array`` without an element type. In order: an
    explicit entry sourced from the controller schema, a sub-structure table,
    then what the field's own description says. When none of those settle it the
    element type is genuinely unstated, and the honest declaration is a bounded
    JSON value rather than a guess.
    """
    override = ARRAY_ITEM_OVERRIDES.get((provider, slug, name))
    if override:
        return override
    if nested:
        return OBJECT
    text = description or ""
    if _ID_LIST_RE.search(text):
        return INTEGER
    if _SLUG_LIST_RE.search(text):
        return TEXT
    return JSON


def _norm_route(route: str) -> str:
    stripped = route.replace("/wp-json", "")
    return re.sub(r"[<{][^>}]*[>}]", "{}", stripped)


#: WordPress accepts either the raw string or the {raw, rendered} object for
#: these fields on write, and always returns the object on read.
WORDPRESS_RENDERED_FIELDS: frozenset[str] = frozenset(
    {"title", "content", "excerpt", "caption", "description"}
)


_JSON_WORD_TO_VALUE_TYPE = {
    "string": TEXT,
    "integer": INTEGER,
    "number": NUMBER,
    "boolean": BOOLEAN,
    "array": ARRAY,
    "object": OBJECT,
    "null": "null",
}


def _type_words(declared: Any) -> list[str]:
    """Split a documented type such as "string or null" into its members."""
    parts = re.split(r"\s+or\s+|\s*,\s*|\s*\|\s*", str(declared or "").strip().lower())
    words: list[str] = []
    for part in parts:
        word = part.strip().removesuffix("[]").strip()
        if word in _JSON_WORD_TO_VALUE_TYPE and word not in words:
            words.append(word)
    return words


def _schema_type(name: str, schema: dict[str, dict[str, Any]]) -> tuple[str, str, list[str]] | None:
    """Primary value type, array element type, and the full documented union.

    WordPress writes "string or null" and "integer or string". Collapsing those
    to the first word makes the contract reject values the API accepts, such as
    clearing a post date by sending null.
    """
    entry = schema.get(name)
    if not entry:
        return None
    words = _type_words(entry.get("json_type"))
    primary = next((word for word in words if word != "null"), "")
    mapped = _JSON_WORD_TO_VALUE_TYPE.get(primary)
    if mapped is None:
        return None
    return mapped, TEXT if mapped == ARRAY else "", words


def _wordpress_type(
    name: str, schema: dict[str, dict[str, Any]], *, in_body: bool = False
) -> tuple[str, str, list[str]]:
    """Resolve a documented WordPress argument's type.

    A collection query and a write body disagree about several Core arguments:
    ``slug`` and ``status`` are arrays when filtering a collection and scalars
    when writing a record. The record schema is authoritative for a body, the
    Core-wide collection table for a query.
    """
    if in_body:
        resolved = _schema_type(name, schema)
        if resolved:
            return resolved
        curated = WORDPRESS_QUERY_TYPES.get(name)
        return (*curated, []) if curated else (TEXT, "", [])
    if name in WORDPRESS_QUERY_TYPES:
        return (*WORDPRESS_QUERY_TYPES[name], [])
    resolved = _schema_type(name, schema)
    return resolved if resolved else (TEXT, "", [])


def _woocommerce_type(raw: str) -> tuple[str, str, list[str]]:
    """Primary value type, array element type, and the documented union.

    WooCommerce writes plain words, but also "mixed", "string[]",
    "string or null" and "boolean, string".
    """
    declared = str(raw or "").strip().lower()
    if declared.endswith("[]"):
        element = _JSON_WORD_TO_VALUE_TYPE.get(declared[:-2].strip(), TEXT)
        return ARRAY, element, []
    if "mixed" in declared:
        return JSON, "", []
    words = _type_words(declared)
    if not words:
        for word in _SPLIT_RE.split(declared):
            if word in WOOCOMMERCE_TYPES:
                return WOOCOMMERCE_TYPES[word], "", []
        return TEXT, "", []
    primary = next((word for word in words if word != "null"), "")
    mapped = _JSON_WORD_TO_VALUE_TYPE.get(primary, TEXT)
    if declared in WOOCOMMERCE_TYPES:
        mapped = WOOCOMMERCE_TYPES[declared]
    return mapped, "", words


_SEE_RE = re.compile(r"See\s+(.+?)\s+properties", re.I)


def _referenced_model(description: str) -> str:
    """Sub-structure a field's description points at, as a model slug.

    WooCommerce writes "Line taxes. See Order - Tax lines properties", which
    names the table to use. Guessing from the field name instead misses it:
    the field is ``taxes`` and the table is ``tax_lines``.
    """
    match = _SEE_RE.search(description or "")
    return _slug(match.group(1)) if match else ""


def _slug(heading: str) -> str:
    tail = heading.split(" - ", 1)[-1]
    tail = re.sub(r"\bproperties\b", "", tail, flags=re.I)
    return "_".join(part for part in _SPLIT_RE.split(tail.strip().lower()) if part)


def _typed_default(raw: Any, value_type: str) -> Any:
    """Coerce a documented default onto the field's own type."""
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if value_type == "boolean":
        lowered = text.lower()
        return True if lowered == "true" else False if lowered == "false" else None
    if value_type == "integer":
        return int(text) if text.lstrip("-").isdigit() else None
    if value_type == "number":
        try:
            return float(text)
        except ValueError:
            return None
    if value_type in {"array", "object"}:
        return None
    return text


def _field(
    name: str,
    value_type: str,
    *,
    item_type: str = "",
    required: bool = False,
    enum: list[str] | None = None,
    default: Any = None,
    nested: str = "",
    rendered: bool = False,
    for_write_enum: bool = False,
    union: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "value_type": value_type}
    if union and len(union) > 1:
        row["union_types"] = list(union)
    if item_type:
        row["item_type"] = item_type
    if required:
        row["required"] = True
    # An enumerated array enumerates strings, whatever the description says.
    if value_type == ARRAY and enum and item_type in {"", JSON}:
        item_type = TEXT
        row["item_type"] = TEXT
    if for_write_enum and enum:
        stripped = [value for value in enum if str(value).lower() in DESTRUCTIVE_STATUS_VALUES]
        if stripped:
            # Remember which values were removed so the runtime guards this one
            # field rather than every string in the request.
            row["destructive_values"] = sorted({str(value).lower() for value in stripped})
        enum = [value for value in enum if str(value).lower() not in DESTRUCTIVE_STATUS_VALUES]
    if enum:
        row["enum"] = list(dict.fromkeys(enum))
    typed_default = _typed_default(default, value_type)
    if typed_default is not None:
        row["default"] = typed_default
    if nested:
        row["nested"] = nested
    if rendered:
        row["rendered"] = True
    return row


def _drop(rows: list[dict[str, Any]], names: frozenset[str]) -> list[dict[str, Any]]:
    """Remove the named fields from one generated table."""
    if not names:
        return rows
    return [row for row in rows if row["name"] not in names]


def build() -> dict[str, Any]:
    import yaml

    snapshot = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))
    pages = {(page["provider"], page["slug"]): page for page in snapshot["pages"]}

    query: dict[str, list[dict[str, Any]]] = {}
    body: dict[str, list[dict[str, Any]]] = {}
    response: dict[str, list[dict[str, Any]]] = {}
    nested_models: dict[str, list[dict[str, Any]]] = {}
    nested_create_models: dict[str, list[dict[str, Any]]] = {}
    nested_update_models: dict[str, list[dict[str, Any]]] = {}
    batch_items: dict[str, dict[str, list[dict[str, Any]]]] = {}
    response_kinds: dict[str, str] = {}
    capabilities: dict[str, dict[str, Any]] = {}
    untyped: list[str] = []

    for row in REST_OPERATIONS:
        page = pages[(row.provider, row.doc_slug)]
        path_names = {name for name, _kind in row.path_params}
        if row.provider == WORDPRESS:
            q, b, r = _wordpress_operation(row, page, path_names, untyped)
        else:
            q, b, r = _woocommerce_operation(
                row,
                page,
                path_names,
                nested_models,
                nested_create_models,
                nested_update_models,
                batch_items,
            )
        # One policy decides which documented fields this version carries, so a
        # field cannot be published here and refused by the runtime.
        query[row.operation_id] = _drop(q, field_policy.excluded_query_fields(row.operation_id))
        body[row.operation_id] = _drop(b, field_policy.excluded_body_fields(row.operation_id))
        response[row.operation_id] = _drop(r, field_policy.excluded_response_fields(row))
        response_kinds[row.operation_id] = _response_kind(row)
        if row.shape == "batch":
            capabilities[row.operation_id] = dict(_batch_capability(row.operation_id))

    for operation_id, members in batch_items.items():
        for member, rows in members.items():
            members[member] = _drop(
                rows, field_policy.excluded_batch_item_fields(operation_id, member)
            )

    return {
        "query": query,
        "body": body,
        "response": response,
        "nested": nested_models,
        "nested_create": nested_create_models,
        "nested_update": nested_update_models,
        "batch": batch_items,
        "response_kinds": response_kinds,
        "capabilities": capabilities,
        "untyped": sorted(set(untyped)),
    }


def _wordpress_operation(
    row: Any, page: dict[str, Any], path_names: set[str], untyped: list[str]
) -> tuple[list, list, list]:
    schema = {entry["name"]: entry for entry in page.get("schema", [])}
    routes = [_norm_route(route) for _method, route in page["routes"]]
    methods = [method for method, _route in page["routes"]]
    target = _norm_route(row.route_pattern)
    section = None
    sections = page.get("sections", [])
    if len(sections) == len(routes):
        for index, (method, route) in enumerate(zip(methods, routes, strict=True)):
            if method == row.method and route == target:
                section = sections[index]
                break
    elif page["slug"] == "settings" and row.method == "POST":
        section = sections[0]

    documented = [
        entry for entry in (section or {}).get("fields", []) if entry["name"] not in path_names
    ]
    in_body = row.shape not in {"list", "get"}
    fields: list[dict[str, Any]] = []
    for entry in documented:
        name = entry["name"]
        value_type, item_type, union = _wordpress_type(name, schema, in_body=in_body)
        if value_type == ARRAY and (in_body or name not in WORDPRESS_QUERY_TYPES):
            item_type = _array_item_type(
                name,
                entry.get("description", ""),
                nested=False,
                provider="wordpress",
                slug=page["slug"],
            )
        if name not in WORDPRESS_QUERY_TYPES and name not in schema:
            untyped.append(f"{page['slug']}:{name}")
        fields.append(
            _field(
                name,
                value_type,
                item_type=item_type,
                required=is_required(entry.get("description", "")),
                enum=entry.get("options") or None,
                default=entry.get("default"),
                rendered=bool(
                    in_body and value_type == OBJECT and name in WORDPRESS_RENDERED_FIELDS
                ),
                for_write_enum=in_body,
                union=union,
            )
        )
    response_fields = []
    for entry in page.get("schema", []):
        if is_response_suppressed(entry.get("description", "")):
            continue
        resolved = _schema_type(entry["name"], schema)
        value_type = resolved[0] if resolved else TEXT
        union = resolved[2] if resolved else []
        item_type = ""
        if value_type == ARRAY:
            item_type = _array_item_type(
                entry["name"],
                entry.get("description", ""),
                nested=False,
                provider="wordpress",
                slug=page["slug"],
            )
        response_fields.append(_field(entry["name"], value_type, item_type=item_type, union=union))
    if row.shape in {"list", "get"}:
        return fields, [], response_fields
    return [], fields, response_fields


def _woocommerce_operation(
    row: Any,
    page: dict[str, Any],
    path_names: set[str],
    nested_models: dict[str, Any],
    nested_create_models: dict[str, Any],
    nested_update_models: dict[str, Any],
    batch_items: dict[str, Any] | None = None,
) -> tuple[list, list, list]:
    property_tables = page.get("properties", [])
    wanted = RESPONSE_TABLE_BY_OPERATION.get(row.operation_id, "")
    primary = property_tables[0]["fields"] if property_tables else []
    if wanted:
        for table in property_tables:
            if _slug(table["heading"]) == wanted:
                primary = table["fields"]
                break
    sub_models: dict[str, list[dict[str, Any]]] = {}
    for table in property_tables[1:]:
        key = _slug(table["heading"])
        if key:
            sub_models.setdefault(key, table["fields"])

    def _convert(
        entry: dict[str, Any], *, for_write: bool, in_meta: bool = False
    ) -> dict[str, Any]:
        value_type, declared_item, union = _woocommerce_type(entry.get("type", ""))
        if in_meta and entry["name"] in MIXED_VALUE_FIELDS:
            value_type, union = JSON, []
        nested_key = ""
        referenced = _referenced_model(entry.get("description", ""))
        candidates = [referenced] if referenced else []
        candidates += [entry["name"], f"{entry['name']}s", entry["name"].rstrip("s")]
        # Only a structured value has a sub-model. Matching on the name alone
        # also attaches one to a string that happens to share a table's name —
        # the downloads file URL is called `file`, like its own table, which
        # recurses until the stack gives out.
        if value_type not in {OBJECT, ARRAY}:
            candidates = []
        for candidate in candidates:
            if candidate and candidate in sub_models:
                nested_key = f"{page['slug']}.{candidate}"
                # A meta table's `value` column is any JSON value, not a string.
                in_meta_model = "meta" in candidate
                nested_models.setdefault(
                    nested_key,
                    [
                        _convert(sub, for_write=False, in_meta=in_meta_model)
                        for sub in sub_models[candidate]
                        if not is_response_suppressed(sub.get("description", ""))
                    ],
                )
                # A write model drops the sub-structure's read-only members,
                # so a request cannot offer categories[].name or
                # line_items[].price, which the API computes.
                #
                # `id` splits the two write modes: creating a record cannot name
                # a sub-entry that does not exist yet, while updating one must.
                nested_create_models.setdefault(
                    nested_key,
                    [
                        _convert(sub, for_write=True, in_meta=in_meta_model)
                        for sub in sub_models[candidate]
                        if not sub.get("read_only")
                    ],
                )
                nested_update_models.setdefault(
                    nested_key,
                    [
                        _convert(sub, for_write=True, in_meta=in_meta_model)
                        for sub in sub_models[candidate]
                        if not sub.get("read_only") or sub["name"] == "id"
                    ],
                )
                break
        item_type = ""
        if value_type == ARRAY:
            item_type = declared_item or _array_item_type(
                entry["name"],
                entry.get("description", ""),
                nested=bool(nested_key),
                provider="woocommerce",
                slug=page["slug"],
            )
        return _field(
            entry["name"],
            value_type,
            item_type=item_type,
            required=bool(
                for_write and (entry.get("mandatory") or is_required(entry.get("description", "")))
            ),
            enum=entry.get("options") or None,
            default=entry.get("default"),
            nested=nested_key,
            for_write_enum=for_write,
            union=union,
        )

    if row.operation_id == "wc_preview_order_refund":
        # The preview's breakdown is described in prose, not in a table.
        nested_models.setdefault(
            "order-refunds.preview_breakdown_section", list(PREVIEW_BREAKDOWN_SECTION)
        )
        nested_models.setdefault("order-refunds.preview_breakdown", list(PREVIEW_BREAKDOWN))
    if row.operation_id in PRIMITIVE_LIST_OPERATIONS:
        # A bare list of scalars: there is no record table to read.
        primary = []
    response_fields = [
        _convert(entry, for_write=False)
        for entry in primary
        if not is_response_suppressed(entry.get("description", ""))
    ]
    if row.operation_id == "wc_preview_order_refund":
        response_fields = [
            field | {"nested": "order-refunds.preview_breakdown"}
            if field["name"] == "breakdown"
            else field
            for field in response_fields
        ]
    if row.operation_id in PRIMITIVE_LIST_OPERATIONS:
        response_fields = [_field("value", PRIMITIVE_LIST_OPERATIONS[row.operation_id])]
    elif not response_fields:
        response_fields = [
            _convert(entry, for_write=False)
            for entry in DOCUMENTED_ACTION_RESPONSES.get(row.operation_id, [])
        ]

    def _writable(*, creating: bool) -> list[dict[str, Any]]:
        """Body fields for a create or an update.

        WooCommerce marks two fields both READ-ONLY and MANDATORY
        (``webhooks.delivery_url``, ``shipping-zone-methods.method_id``). Those
        are set once at creation and immutable afterwards, so they belong in a
        create body and not in an update body.
        """
        rows = []
        for entry in primary:
            if entry["name"] in path_names:
                continue
            read_only = bool(entry.get("read_only"))
            mandatory = bool(entry.get("mandatory"))
            if read_only and not (creating and mandatory):
                continue
            rows.append(_convert(entry, for_write=True))
        return rows

    writable_create = _writable(creating=True)
    # An update sends only what changes, so a field that is mandatory when
    # creating the record is optional when changing it.
    writable_update = [
        {key: value for key, value in field.items() if key != "required"}
        for field in _writable(creating=False)
    ]

    heading_by_shape = {"list": ("list all", "list"), "get": ("retrieve",)}
    query_fields: list[dict[str, Any]] = []
    documented_query = DOCUMENTED_QUERY_FIELDS.get(row.operation_id)
    if documented_query is not None:
        return (
            [_convert(entry, for_write=False) for entry in documented_query],
            [],
            response_fields,
        )
    prefixes = heading_by_shape.get(row.shape)
    # Report endpoints document their parameters under the report's own heading
    # ("Sales report", "Top sellers report") rather than a List/Retrieve one.
    route_tail = row.route.rsplit("/", 1)[-1].replace("_", " ").lower()
    for section in page.get("sections", []):
        heading = section["heading"].lower()
        matches_shape = bool(prefixes) and heading.startswith(prefixes)
        matches_route = bool(route_tail) and heading.startswith(route_tail)
        if matches_shape or matches_route:
            query_fields = [
                _convert(entry, for_write=False)
                for entry in section["fields"]
                if entry["name"] not in path_names
            ]
            break
    if row.shape in {"list", "get"}:
        return query_fields, [], response_fields
    item_section = BODY_ITEM_SECTION.get(row.operation_id)
    if item_section is not None:
        heading, body_field, model_name = item_section
        entries = next(
            (
                section["fields"]
                for section in page.get("sections", [])
                if section["heading"].lower().startswith(heading)
            ),
            [],
        )
        model_key = f"{page['slug']}.{model_name}"
        item_model = [
            _convert(entry, for_write=True)
            | ({} if entry["name"] in OPTIONAL_BODY_ITEM_FIELDS else {"required": True})
            for entry in entries
        ]
        nested_models.setdefault(model_key, item_model)
        nested_create_models.setdefault(model_key, item_model)
        nested_update_models.setdefault(model_key, item_model)
        return (
            [],
            [
                _field(
                    body_field,
                    ARRAY,
                    item_type=OBJECT,
                    required=True,
                    nested=model_key,
                )
            ],
            response_fields,
        )
    if row.shape in {"create", "read_post"}:
        return [], writable_create, response_fields
    if row.shape == "update":
        return [], writable_update, response_fields
    if row.shape == "batch":
        # A batch carries two different record shapes. An update entry must name
        # the record it changes; a create entry must not. Which members exist,
        # and how a record is identified, differ per endpoint.
        capability = _batch_capability(row.operation_id)
        identifier = _field("id", capability["id_type"], required=True)
        members: dict[str, list[dict[str, Any]]] = {}
        if "create" in capability["members"]:
            members["create"] = writable_create
        if "update" in capability["members"]:
            members["update"] = [identifier, *writable_update]
        if batch_items is not None:
            batch_items[row.operation_id] = members
        return [], writable_create, response_fields
    documented_action = DOCUMENTED_ACTION_BODIES.get(row.operation_id)
    if documented_action is None:
        raise SystemExit(f"no documented body declared for action {row.operation_id}")
    action_fields = [_convert(entry, for_write=True) for entry in documented_action]
    return [], action_fields, response_fields


HEADER = '''"""Typed parameter tables derived from the official REST references.

Generated by ``tests/reference/build_parameters.py`` from
``contracts/rest_reference.yaml``. Do not edit by hand: an extension-owned test
rebuilds these tables from the committed documentation snapshot and fails on any
difference.

``QUERY_FIELDS`` and ``BODY_FIELDS`` are the closed set of parameters each
operation accepts. The runtime rejects anything else before outbound I/O, so a
plugin-specific field such as ``acf`` or ``lang`` cannot reach the site through
this extension.
"""

from __future__ import annotations

from typing import Any

'''


def _iter_table_strings(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_table_strings(key)
            yield from _iter_table_strings(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_table_strings(item)


def _shared_model_literals(tables: dict[str, Any]) -> list[str]:
    """Return repeated nested-model references that merit named constants."""
    counts = Counter(_iter_table_strings(tables))
    return sorted(
        value
        for value, count in counts.items()
        if count >= 3 and "." in value and not any(character.isspace() for character in value)
    )


def _model_literal_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return f"_TOKEN_{slug}"


def render(tables: dict[str, Any]) -> str:
    shared_literals = _shared_model_literals(tables)
    literal_names = {value: _model_literal_name(value) for value in shared_literals}

    def dump(name: str, payload: Any) -> str:
        # repr() emits valid Python literals directly. Rendering JSON and then
        # substituting true/false/null corrupts any string that merely contains
        # one of those words, such as a documented default of "false".
        rendered = repr(payload)
        for value, constant_name in literal_names.items():
            rendered = rendered.replace(repr(value), constant_name)
        return f"{name} = {rendered}\n\n"

    body = HEADER
    body += "".join(f"{literal_names[value]} = {value!r}\n" for value in shared_literals)
    body += "\n"
    body += dump("QUERY_FIELDS: dict[str, list[dict[str, Any]]]", tables["query"])
    body += dump("BODY_FIELDS: dict[str, list[dict[str, Any]]]", tables["body"])
    body += dump("RESPONSE_FIELDS: dict[str, list[dict[str, Any]]]", tables["response"])
    body += dump("NESTED_MODELS: dict[str, list[dict[str, Any]]]", tables["nested"])
    body += dump("NESTED_CREATE_MODELS: dict[str, list[dict[str, Any]]]", tables["nested_create"])
    body += dump("NESTED_UPDATE_MODELS: dict[str, list[dict[str, Any]]]", tables["nested_update"])
    body += dump("BATCH_ITEM_FIELDS: dict[str, dict[str, list[dict[str, Any]]]]", tables["batch"])
    body += dump("RESPONSE_KINDS: dict[str, str]", tables["response_kinds"])
    body += dump("BATCH_CAPABILITIES: dict[str, dict[str, Any]]", tables["capabilities"])
    exported = sorted(
        [
            "BATCH_CAPABILITIES",
            "BATCH_ITEM_FIELDS",
            "BODY_FIELDS",
            "NESTED_CREATE_MODELS",
            "NESTED_MODELS",
            "NESTED_UPDATE_MODELS",
            "QUERY_FIELDS",
            "RESPONSE_FIELDS",
            "RESPONSE_KINDS",
        ]
    )
    # Sorted so the generated module stays lint-clean (`RUF022`) after a refresh.
    body += "__all__ = [\n" + "".join(f'    "{name}",\n' for name in exported) + "]\n"
    return body


def _ruff_format(path: Path) -> bool:
    """Format the generated module in place.

    ``--check`` compares the parsed tables rather than the rendered text, so
    formatting is not drift — but leaving the file unformatted would fail the
    repository lint gate straight after a refresh.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "ruff", "format", str(path)],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    tables = build()
    rendered = render(tables)
    if arguments.check:
        # Compare the parsed tables, not the rendered text: the file is
        # formatted by ruff after generation, and formatting is not drift.
        from runtime import parameters as current

        expected = {
            "QUERY_FIELDS": tables["query"],
            "BODY_FIELDS": tables["body"],
            "RESPONSE_FIELDS": tables["response"],
            "NESTED_MODELS": tables["nested"],
            "NESTED_CREATE_MODELS": tables["nested_create"],
            "NESTED_UPDATE_MODELS": tables["nested_update"],
            "BATCH_ITEM_FIELDS": tables["batch"],
            "RESPONSE_KINDS": tables["response_kinds"],
            "BATCH_CAPABILITIES": tables["capabilities"],
        }
        for name, payload in expected.items():
            if getattr(current, name) != payload:
                print(f"runtime/parameters.py is out of date: {name}", file=sys.stderr)
                return 1
        print(json.dumps({"status": "current"}))
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    formatted = _ruff_format(TARGET)
    print(
        json.dumps(
            {
                "status": "written",
                "formatted": formatted,
                "operations": len(tables["query"]),
                "nested_models": len(tables["nested"]),
                "untyped_wordpress_arguments": tables["untyped"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
