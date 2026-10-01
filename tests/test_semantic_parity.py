"""Semantic parity: the published contract and the runtime must mean the same thing.

The earlier suites checked that field *names* matched across the manifest, the
step forms, the UI actions and the runtime. That is not enough: a field can be
declared an array of objects and still accept integers, or declared a string and
be enforced as anything. These tests drive real values through the runtime and
compare the outcome with what each published schema promises, for every
operation and every field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import connection_payload, json_response
from runtime import errors
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID, operation
from runtime.io_shapes import (
    KIND_BATCH_GROUPS,
    KIND_KEYED_MAP,
    KIND_OBJECT,
    KIND_OBJECT_LIST,
    KIND_PRIMITIVE_LIST,
    batch_item_fields,
    batch_members,
    operation_inputs,
    operation_outputs,
    response_kind,
)
from runtime.operations import handle_runtime
from runtime.parameters import RESPONSE_FIELDS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
WOO = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret

#: A value that is valid for one JSON type and invalid for every other.
_WITNESS: dict[str, Any] = {
    "string": "sample",
    "integer": 7,
    "number": 1.5,
    "boolean": True,
    "object": {},
    "array": [],
}
#: For each declared type, a value of a different type that must be refused.
_COUNTEREXAMPLE: dict[str, Any] = {
    "string": 7,
    "integer": "7",
    "number": "1.5",
    "boolean": "true",
    "object": [],
    "array": {},
}


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


def _declared_type(schema: dict[str, Any]) -> str | None:
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared
    return None  # a union accepts several shapes; not a single-type promise


def _sample_for(schema: dict[str, Any]) -> Any:
    """A value the published schema says is acceptable."""
    if schema.get("examples"):
        return schema["examples"][0]
    declared = _declared_type(schema)
    if declared is None:
        return "sample"
    if declared == "string" and schema.get("enum"):
        return schema["enum"][0]
    if declared == "array":
        items = schema.get("items") or {}
        return [_sample_for(items)] if items else []
    if declared == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        return {name: _sample_for(properties.get(name) or {}) for name in required}
    return _WITNESS[declared]


def _minimum_input(row: Any) -> dict[str, Any]:
    """Just the required inputs, each carrying a schema-valid value."""
    operation_input: dict[str, Any] = {}
    for field in operation_inputs(row):
        name = field["name"]
        if name == "connection_ref" or not field.get("required"):
            continue
        if name == "artifact_handle":
            operation_input[name] = "artifact-1"
        elif name == "filename":
            operation_input[name] = "sample.png"
        else:
            operation_input[name] = _sample_for(field.get("schema") or {})
    if row.shape == "batch":
        member = batch_members(row)[0]
        entry = {
            item["name"]: _sample_for(
                next(
                    field for field in operation_inputs(row) if field["name"] == f"{member}_items"
                )["schema"]["items"]["properties"][item["name"]]
            )
            for item in batch_item_fields(row, member)
            if item.get("required")
        }
        operation_input[f"{member}_items"] = [entry or {}]
    return operation_input


# -- Every declared field is enforced as declared -------------------------


@pytest.mark.parametrize("row", REST_OPERATIONS, ids=lambda row: row.operation_id)
def test_every_declared_field_accepts_a_schema_valid_value(http, transport_factory, row) -> None:
    """What the manifest says is acceptable, the runtime accepts."""
    if row.shape == "media_create":
        pytest.skip("needs an artifact grant; covered by the media suite")
    operation_input = _minimum_input(row)
    for field in operation_inputs(row):
        name = field["name"]
        if name == "connection_ref" or name in operation_input or name.endswith("_items"):
            continue
        operation_input[name] = _sample_for(field.get("schema") or {})
    http.responses.clear()
    http.queue(
        json_response([] if response_kind(row) in {KIND_OBJECT_LIST, KIND_PRIMITIVE_LIST} else {})
    )
    response = _run(row.operation_id, operation_input, transport_factory, **WOO)
    assert response["ok"] is True, (row.operation_id, response.get("error"))


@pytest.mark.parametrize("row", REST_OPERATIONS, ids=lambda row: row.operation_id)
def test_every_declared_field_refuses_a_value_of_the_wrong_type(
    http, transport_factory, row
) -> None:
    """What the manifest says is unacceptable, the runtime refuses."""
    if row.shape == "media_create":
        pytest.skip("needs an artifact grant; covered by the media suite")
    checked = 0
    for field in operation_inputs(row):
        name = field["name"]
        schema = field.get("schema") or {}
        declared = _declared_type(schema)
        if name == "connection_ref" or declared is None or name.endswith("_items"):
            continue
        wrong = _COUNTEREXAMPLE[declared]
        operation_input = {**_minimum_input(row), name: wrong}
        http.responses.clear()
        http.queue(json_response({}))
        response = _run(row.operation_id, operation_input, transport_factory, **WOO)
        assert response["ok"] is False, (row.operation_id, name, wrong)
        assert response["error_code"] == errors.INVALID_PAYLOAD, (row.operation_id, name)
        assert http.requests == [], (row.operation_id, name)
        checked += 1
    assert checked >= 1 or not row.path_params


# -- Array element types are enforced, not merely declared ----------------


@pytest.mark.parametrize("row", REST_OPERATIONS, ids=lambda row: row.operation_id)
def test_array_element_types_are_enforced(http, transport_factory, row) -> None:
    if row.shape in {"media_create", "batch"}:
        pytest.skip("covered by the media and batch suites")
    for field in operation_inputs(row):
        schema = field.get("schema") or {}
        if schema.get("type") != "array":
            continue
        items = schema.get("items") or {}
        item_type = _declared_type(items)
        if item_type is None or items.get("enum"):
            continue
        wrong = _COUNTEREXAMPLE[item_type]
        operation_input = {**_minimum_input(row), field["name"]: [wrong]}
        http.responses.clear()
        http.queue(json_response({}))
        response = _run(row.operation_id, operation_input, transport_factory, **WOO)
        assert response["error_code"] == errors.INVALID_PAYLOAD, (
            row.operation_id,
            field["name"],
            item_type,
            wrong,
        )
        assert http.requests == []


def test_an_object_array_refuses_scalars(http, transport_factory) -> None:
    for operation_id, name, extra in (
        ("wc_create_product", "categories", {"name": "W"}),
        ("wc_create_order", "line_items", {}),
        ("wc_create_product", "images", {"name": "W"}),
    ):
        for wrong in (1, "text", True):
            http.responses.clear()
            http.queue(json_response({}))
            response = _run(operation_id, {**extra, name: [wrong]}, transport_factory, **WOO)
            assert response["error_code"] == errors.INVALID_PAYLOAD, (operation_id, name, wrong)
            assert http.requests == []


# -- Nested structures are typed all the way down -------------------------


def test_no_declared_array_is_missing_its_element_schema() -> None:
    def _walk(schema: dict[str, Any], path: str) -> None:
        if schema.get("type") == "array":
            assert schema.get("items"), path
            _walk(schema["items"], f"{path}[]")
        for name, child in (schema.get("properties") or {}).items():
            _walk(child, f"{path}.{name}")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            _walk(extra, f"{path}.*")

    for row in REST_OPERATIONS:
        for field in operation_inputs(row) + operation_outputs(row):
            schema = field.get("schema")
            if isinstance(schema, dict):
                _walk(schema, f"{row.operation_id}.{field['name']}")


def test_a_native_mixed_value_accepts_every_json_shape(http, transport_factory) -> None:
    """WooCommerce meta values are string, number, boolean, object or array."""
    for value in ("text", 7, 1.5, True, {"nested": 1}, [1, 2], None):
        http.responses.clear()
        http.queue(json_response({"id": 1}, status=201))
        response = _run(
            "wc_create_product",
            {"name": "Widget", "meta_data": [{"key": "k", "value": value}]},
            transport_factory,
            **WOO,
        )
        assert response["ok"] is True, value
        assert http.json_body()["meta_data"] == [{"key": "k", "value": value}]


def test_a_mixed_value_is_published_as_a_union() -> None:
    field = next(
        entry
        for entry in operation_inputs(operation("wc_create_product"))
        if entry["name"] == "meta_data"
    )
    value_schema = field["schema"]["items"]["properties"]["value"]
    assert set(value_schema["type"]) >= {"string", "number", "boolean", "object", "array"}


# -- Response contracts describe the real answer --------------------------


@pytest.mark.parametrize("row", REST_OPERATIONS, ids=lambda row: row.operation_id)
def test_the_declared_response_shape_matches_what_the_runtime_returns(
    http, transport_factory, row
) -> None:
    if row.shape == "media_create":
        pytest.skip("covered by the media suite")
    kind = response_kind(row)
    upstream: Any = {"id": 1}
    if kind == KIND_OBJECT_LIST:
        upstream = [{"id": 1}]
    elif kind == KIND_PRIMITIVE_LIST:
        upstream = ["Custom field 1"]
    elif kind == KIND_KEYED_MAP:
        upstream = {"post": {"slug": "post"}}
    elif kind == KIND_BATCH_GROUPS:
        upstream = {member: [{"id": 1}] for member in batch_members(row)}

    http.responses.clear()
    http.queue(json_response(upstream))
    response = _run(row.operation_id, _minimum_input(row), transport_factory, **WOO)
    assert response["ok"] is True, (row.operation_id, response.get("error"))

    declared = {field["name"] for field in operation_outputs(row)}
    assert set(response["result"]) >= declared - {
        "external_effect_status",
        "definitely_no_external_effect",
    }
    if kind in {KIND_OBJECT_LIST, KIND_PRIMITIVE_LIST}:
        assert isinstance(response["result"]["items"], list)
    else:
        assert "data" in response["result"]


def test_keyed_map_endpoints_are_not_described_as_a_single_record() -> None:
    for operation_id in (
        "wp_get_post_types",
        "wp_get_post_statuses",
        "wp_get_taxonomies",
        "wp_get_menu_locations",
    ):
        row = REST_OPERATIONS_BY_ID[operation_id]
        assert response_kind(row) == KIND_KEYED_MAP, operation_id
        data = next(field for field in operation_outputs(row) if field["name"] == "data")
        assert data["schema"]["type"] == "object"
        assert isinstance(data["schema"].get("additionalProperties"), dict), operation_id


def test_a_primitive_list_is_not_described_as_objects() -> None:
    row = REST_OPERATIONS_BY_ID["wc_list_product_custom_field_names"]
    assert response_kind(row) == KIND_PRIMITIVE_LIST
    items = next(field for field in operation_outputs(row) if field["name"] == "items")
    assert items["schema"]["items"]["type"] == "string"


def test_pages_with_several_record_tables_do_not_share_one_model() -> None:
    """Each report and store-data endpoint describes its own answer."""
    groups = [
        [
            "wc_get_sales_report",
            "wc_get_top_sellers_report",
            "wc_get_coupons_totals_report",
        ],
        ["wc_list_countries", "wc_list_currencies", "wc_list_continents"],
    ]
    for group in groups:
        models = [tuple(f["name"] for f in RESPONSE_FIELDS[oid]) for oid in group]
        assert len(set(models)) == len(models), group


def test_a_batch_response_names_only_the_supported_members() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "batch":
            continue
        data = next(field for field in operation_outputs(row) if field["name"] == "data")
        assert set(data["schema"]["properties"]) == set(batch_members(row)), row.operation_id


# -- Batch capabilities are per endpoint ----------------------------------


def test_setting_options_batch_is_update_only_with_a_slug_id(http, transport_factory) -> None:
    row = REST_OPERATIONS_BY_ID["wc_batch_setting_options"]
    assert batch_members(row) == ["update"]
    names = {field["name"] for field in operation_inputs(row)}
    assert "create_items" not in names
    assert "update_items" in names

    http.queue(json_response({"update": []}))
    accepted = _run(
        "wc_batch_setting_options",
        {"group_id": "general", "update_items": [{"id": "woocommerce_currency", "value": "GBP"}]},
        transport_factory,
        **WOO,
    )
    assert accepted["ok"] is True, accepted.get("error")
    assert http.json_body() == {"update": [{"id": "woocommerce_currency", "value": "GBP"}]}

    refused = _run(
        "wc_batch_setting_options",
        {"group_id": "general", "update_items": [{"id": 7, "value": "GBP"}]},
        transport_factory,
        **WOO,
    )
    assert refused["error_code"] == errors.INVALID_PAYLOAD


def test_a_batch_endpoint_refuses_a_member_it_does_not_support(http, transport_factory) -> None:
    response = _run(
        "wc_batch_setting_options",
        {"group_id": "general", "create_items": [{"value": "x"}]},
        transport_factory,
        **WOO,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


# -- Manifest, forms, actions and runtime stay one contract ---------------


def test_the_published_schemas_are_byte_identical_across_surfaces() -> None:
    operations = {
        row["operation_id"]: row
        for row in yaml.safe_load((BUNDLE_ROOT / "contracts/operation_manifest.yaml").read_text())[
            "operations"
        ]
    }
    forms = {
        row["operation_id"]: row
        for row in yaml.safe_load((BUNDLE_ROOT / "contracts/step_ui_manifest.yaml").read_text())[
            "forms"
        ]
    }
    actions = {
        row["action_id"]: row
        for row in yaml.safe_load((BUNDLE_ROOT / "ui/actions/actions.yaml").read_text())["actions"]
    }
    for row in REST_OPERATIONS:
        assert operations[row.operation_id]["inputs"] == operation_inputs(row)
        assert operations[row.operation_id]["outputs"] == operation_outputs(row)
        runtime_names = [field["name"] for field in operation_inputs(row)]
        assert [p["name"] for p in actions[row.operation_id]["parameters"]] == runtime_names
        assert [f["name"] for f in forms[row.operation_id]["fields"]] == runtime_names[1:]


def test_every_operation_declares_a_known_response_kind() -> None:
    known = {
        KIND_OBJECT,
        KIND_OBJECT_LIST,
        KIND_PRIMITIVE_LIST,
        KIND_KEYED_MAP,
        KIND_BATCH_GROUPS,
    }
    for row in REST_OPERATIONS:
        assert response_kind(row) in known, row.operation_id
