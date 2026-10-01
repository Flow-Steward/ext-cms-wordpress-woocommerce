"""Golden fixtures: the contract matches the official APIs, not just itself.

Every other suite compares generated artifacts with each other, so a generator
that distorts the official contract passes them all. The expectations here are
written by hand from the published WordPress and WooCommerce documentation and
never read the generator's own tables, so a generator change that drifts from
the official types fails here.

Sources:
  https://developer.wordpress.org/rest-api/reference/
  https://developer.wordpress.org/reference/classes/wp_rest_block_types_controller/
  https://developer.woocommerce.com/docs/apis/rest-api/v3/
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import connection_payload, json_response
from runtime.operations import handle_runtime

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
WOO = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret


def _manifest() -> dict[str, Any]:
    operations = yaml.safe_load((BUNDLE_ROOT / "contracts/operation_manifest.yaml").read_text())[
        "operations"
    ]
    return {row["operation_id"]: row for row in operations}


def _input(operation_id: str, name: str) -> dict[str, Any]:
    row = _manifest()[operation_id]
    return next(field for field in row["inputs"] if field["name"] == name)


def _output(operation_id: str, name: str) -> dict[str, Any]:
    row = _manifest()[operation_id]
    return next(field for field in row["outputs"] if field["name"] == name)


def _record_schema(operation_id: str) -> dict[str, Any]:
    """The record an operation returns, whether alone or inside a list."""
    row = _manifest()[operation_id]
    output = next(f for f in row["outputs"] if f["name"] in {"data", "items"})
    schema = output["schema"]
    return schema["items"] if output["name"] == "items" else schema


def _record_property(operation_id: str, name: str) -> dict[str, Any]:
    return _record_schema(operation_id)["properties"][name]


def _declared_types(schema: dict[str, Any]) -> set[str]:
    """The JSON types a schema accepts, whether one or a documented union."""
    declared = schema.get("type")
    if isinstance(declared, list):
        return {str(item) for item in declared}
    return {str(declared)}


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


# -- Nullable and union types --------------------------------------------


@pytest.mark.parametrize(
    ("operation_id", "field", "expected"),
    [
        # WordPress documents these as "string or null".
        ("wp_update_post", "date", ["string", "null"]),
        ("wp_update_post", "date_gmt", ["string", "null"]),
        ("wp_update_page", "date", ["string", "null"]),
        ("wp_update_media", "date", ["string", "null"]),
    ],
)
def test_nullable_fields_publish_both_documented_types(
    operation_id: str, field: str, expected: list[str]
) -> None:
    assert _input(operation_id, field)["schema"]["type"] == expected


def test_a_documented_null_is_accepted_at_runtime(http, transport_factory) -> None:
    """WordPress clears a post's date by sending null."""
    http.queue(json_response({"id": 1}))
    response = _run("wp_update_post", {"id": 1, "date": None}, transport_factory)
    assert response["ok"] is True
    assert http.json_body() == {"date": None}


def test_a_woocommerce_mixed_field_is_published_and_enforced_as_mixed(
    http, transport_factory
) -> None:
    """WooCommerce documents a setting's value and default as `mixed`."""
    declared = _input("wc_update_setting_option", "value")["schema"]["type"]
    assert isinstance(declared, list)
    assert {"string", "number", "boolean", "object", "array"} <= set(declared)

    for value in ("all", 7, True, ["US", "CA"], {"a": 1}):
        http.responses.clear()
        http.queue(json_response({"id": "x"}))
        response = _run(
            "wc_update_setting_option",
            {"group_id": "general", "id": "woocommerce_allowed_countries", "value": value},
            transport_factory,
            **WOO,
        )
        assert response["ok"] is True, value
        assert http.json_body()["value"] == value


# -- Array element types, from the official schemas -----------------------


@pytest.mark.parametrize(
    ("operation_id", "field", "expected_item_type"),
    [
        # WP_REST_Block_Types_Controller: parent and ancestor are block names.
        ("wp_get_block_type", "parent", "string"),
        ("wp_get_block_type", "keywords", "string"),
        # ...and styles and variations are objects, not names.
        ("wp_get_block_type", "styles", "object"),
        ("wp_get_block_type", "variations", "object"),
        # Block patterns carry category slugs, not term IDs.
        ("wp_list_block_patterns", "categories", "string"),
        ("wp_list_block_patterns", "keywords", "string"),
    ],
)
def test_wordpress_response_arrays_carry_their_official_element_type(
    operation_id: str, field: str, expected_item_type: str
) -> None:
    schema = _record_property(operation_id, field)
    # `parent` is documented "array or null", so accept the union.
    assert "array" in _declared_types(schema), (operation_id, field, schema.get("type"))
    assert schema["items"]["type"] == expected_item_type, (operation_id, field)


@pytest.mark.parametrize(
    ("operation_id", "field"),
    [
        # WooCommerce Data API: a country carries state records {code, name}.
        ("wc_list_countries", "states"),
        # System status lists plugin records, not plugin names.
        ("wc_get_system_status", "active_plugins"),
    ],
)
def test_woocommerce_composite_arrays_are_objects_not_strings(
    operation_id: str, field: str
) -> None:
    record = _record_schema(operation_id)
    assert record["properties"][field]["items"]["type"] == "object", (operation_id, field)


def test_post_term_assignments_are_integer_ids() -> None:
    """WordPress assigns terms by ID, so categories and tags are integers."""
    for field in ("categories", "tags"):
        schema = _input("wp_create_post", field)["schema"]
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "integer", field


def test_integer_ids_are_accepted_and_strings_refused(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201))
    assert _run("wp_create_post", {"categories": [1, 2]}, transport_factory)["ok"] is True
    refused = _run("wp_create_post", {"categories": ["1"]}, transport_factory)
    assert refused["error_code"] == "invalid_payload"


# -- Read-only members are not writable ----------------------------------


@pytest.mark.parametrize(
    ("operation_id", "field", "read_only_member", "writable_member"),
    [
        # WooCommerce returns the category name; a request sends only the ID.
        ("wc_create_product", "categories", "name", "id"),
        # A line item's price and sku are computed from the product.
        ("wc_create_order", "line_items", "price", "product_id"),
        ("wc_create_order", "line_items", "sku", "quantity"),
    ],
)
def test_a_read_only_sub_field_is_absent_from_the_write_contract(
    http,
    transport_factory,
    operation_id: str,
    field: str,
    read_only_member: str,
    writable_member: str,
) -> None:
    published = _input(operation_id, field)["schema"]["items"]["properties"]
    assert read_only_member not in published, (operation_id, field, read_only_member)
    assert writable_member in published, (operation_id, field, writable_member)

    refused = _run(operation_id, {field: [{read_only_member: "x"}]}, transport_factory, **WOO)
    assert refused["error_code"] == "invalid_payload"
    assert http.requests == []


def test_the_same_sub_structure_is_richer_when_read_than_when_written() -> None:
    write = set(_input("wc_create_order", "line_items")["schema"]["items"]["properties"])
    read = set(_record_property("wc_get_order", "line_items")["items"]["properties"])
    assert write < read
    assert {"price", "sku", "total_tax"} <= read - write


# -- The published path contract is the enforced one ----------------------


@pytest.mark.parametrize(
    ("operation_id", "field"),
    [
        ("wp_render_block", "name"),
        ("wp_get_post_type", "type"),
        ("wp_get_plugin", "plugin"),
        ("wp_get_theme", "stylesheet"),
    ],
)
def test_a_path_parameter_enforces_exactly_what_it_publishes(
    http, transport_factory, operation_id: str, field: str
) -> None:
    """The schema subset has no `pattern`, so neither side may assume one."""
    schema = _input(operation_id, field)["schema"]
    assert schema["type"] == "string"
    assert "examples" not in schema  # an annotation constrains nothing

    longest = "x" * schema["maxLength"]
    http.responses.clear()
    http.queue(json_response({}))
    accepted = _run(
        operation_id,
        {field: longest, **({"attributes": {}} if operation_id == "wp_render_block" else {})},
        transport_factory,
    )
    assert accepted["ok"] is True, (operation_id, accepted.get("error"))

    too_long = "x" * (schema["maxLength"] + 1)
    refused = _run(
        operation_id,
        {field: too_long, **({"attributes": {}} if operation_id == "wp_render_block" else {})},
        transport_factory,
    )
    assert refused["error_code"] == "invalid_payload"


def test_a_path_segment_cannot_change_the_url_structure(http, transport_factory) -> None:
    """Safety rests on encoding and the same-site check, not on a shape regex."""
    http.queue(json_response({}))
    _run("wp_get_post_type", {"type": "a?b=c#d"}, transport_factory)
    url = http.last["url"]
    assert url == "https://shop.example/wp-json/wp/v2/types/a%3Fb%3Dc%23d"
    assert "?" not in url
    assert "#" not in url


@pytest.mark.parametrize("traversal", ["../x", "a/../../etc", ".."])
def test_a_traversal_is_refused(http, transport_factory, traversal: str) -> None:
    response = _run("wp_get_plugin", {"plugin": traversal}, transport_factory)
    assert response["error_code"] == "unsupported_operation"
    assert http.requests == []


def test_a_route_that_is_itself_a_path_keeps_its_separator(http, transport_factory) -> None:
    http.queue(json_response({}), json_response({}))
    _run("wp_render_block", {"name": "core/paragraph", "attributes": {}}, transport_factory)
    assert http.last["url"].endswith("/block-renderer/core/paragraph")
    _run("wp_get_plugin", {"plugin": "akismet/akismet"}, transport_factory)
    assert http.last["url"].endswith("/plugins/akismet/akismet")


def test_a_non_path_segment_has_its_separator_encoded(http, transport_factory) -> None:
    http.queue(json_response({}))
    _run("wp_get_post_type", {"type": "a/b"}, transport_factory)
    assert http.last["url"].endswith("/types/a%2Fb")
