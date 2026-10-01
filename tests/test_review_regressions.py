"""Regression cover for the defects found in review.

Each test here pins behaviour that was previously wrong, so the same mistake
cannot come back through the generators.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import connection_payload, json_response, php_parse_str
from runtime import errors
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID, operation
from runtime.io_shapes import batch_item_fields, operation_inputs, operation_outputs
from runtime.operations import handle_runtime
from runtime.parameters import BATCH_ITEM_FIELDS, BODY_FIELDS, QUERY_FIELDS, RESPONSE_FIELDS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
WOO = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


# -- 1. Array element types are real -------------------------------------


def test_id_arrays_are_typed_as_integers_not_strings() -> None:
    for operation_id, name in (
        ("wp_create_post", "categories"),
        ("wp_create_post", "tags"),
        ("wp_list_posts", "include"),
        ("wp_list_posts", "exclude"),
        ("wc_list_products", "include"),
        ("wc_list_orders", "exclude"),
        ("wc_create_product", "cross_sell_ids"),
        ("wc_create_product", "upsell_ids"),
    ):
        table = BODY_FIELDS if name not in {"include", "exclude"} else QUERY_FIELDS
        field = next(entry for entry in table[operation_id] if entry["name"] == name)
        assert field["item_type"] == "integer", (operation_id, name)


def test_integer_ids_are_accepted_and_strings_refused(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201))
    accepted = _run("wp_create_post", {"categories": [1, 2]}, transport_factory)
    assert accepted["ok"] is True
    assert http.json_body()["categories"] == [1, 2]

    refused = _run("wp_create_post", {"categories": ["1", "2"]}, transport_factory)
    assert refused["error_code"] == errors.INVALID_PAYLOAD


def test_object_arrays_are_typed_as_objects() -> None:
    for operation_id, name in (
        ("wc_create_product", "images"),
        ("wc_create_product", "categories"),
        ("wc_create_order", "line_items"),
    ):
        field = next(entry for entry in BODY_FIELDS[operation_id] if entry["name"] == name)
        assert field["item_type"] == "object", (operation_id, name)


def test_no_array_field_is_left_without_an_element_type() -> None:
    for table in (QUERY_FIELDS, BODY_FIELDS):
        for operation_id, fields in table.items():
            for field in fields:
                if field["value_type"] == "array":
                    # "json" means the reference does not state an element type;
                    # it is declared honestly rather than guessed.
                    assert field.get("item_type") in {
                        "integer",
                        "text",
                        "object",
                        "number",
                        "boolean",
                        "json",
                    }, (operation_id, field["name"])


def test_the_manifest_element_type_matches_what_the_runtime_accepts() -> None:
    """The published item type and the enforced item type are the same."""
    for row in REST_OPERATIONS:
        if row.shape == "batch":
            continue  # a batch exposes item lists; their schemas are checked separately
        declared = {field["name"]: field for field in operation_inputs(row)}
        for source in (QUERY_FIELDS[row.operation_id], BODY_FIELDS[row.operation_id]):
            for field in source:
                if field["value_type"] != "array":
                    continue
                schema = declared[field["name"]]["schema"]
                published = schema["items"].get("type")
                if field["item_type"] == "json":
                    # No stated element type: published as the mixed union.
                    assert isinstance(published, list), (row.operation_id, field["name"])
                    continue
                expected = {
                    "integer": "integer",
                    "text": "string",
                    "object": "object",
                    "number": "number",
                }[field["item_type"]]
                assert published == expected, (row.operation_id, field["name"])


def test_every_operation_has_a_documented_response_model() -> None:
    missing = [row.operation_id for row in REST_OPERATIONS if not RESPONSE_FIELDS[row.operation_id]]
    assert missing == []


def test_a_batch_response_is_grouped_not_a_single_record() -> None:
    outputs = {field["name"]: field for field in operation_outputs(operation("wc_batch_products"))}
    schema = outputs["data"]["schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"create", "update"}
    assert schema["properties"]["create"]["type"] == "array"
    assert schema["properties"]["update"]["items"]["type"] == "object"


def test_product_batch_output_publishes_the_compact_receipt_contract() -> None:
    outputs = {field["name"]: field for field in operation_outputs(operation("wc_batch_products"))}
    receipt = outputs["data"]["schema"]["properties"]["update"]["items"]

    assert set(receipt["properties"]) == {
        "id",
        "sku",
        "status",
        "stock_status",
        "stock_quantity",
        "regular_price",
        "price",
        "error",
    }
    assert "description" not in receipt["properties"]
    assert "images" not in receipt["properties"]


# -- 2. Query arrays survive PHP parsing ---------------------------------


def test_repeated_bare_keys_are_never_emitted(http, transport_factory) -> None:
    http.queue(json_response([]))
    _run("wc_list_products", {"include": [11, 22, 33]}, transport_factory, **WOO)
    query = http.last["url"].split("?", 1)[1]

    assert php_parse_str(query)["include"] == ["11", "22", "33"]
    assert "include=11&include=22" not in query


# -- 3. Long content is not truncated by a global cap ---------------------


@pytest.mark.parametrize(
    ("operation_id", "field", "extra"),
    [
        ("wp_create_post", "content", {}),
        ("wp_update_post", "content", {"id": 1}),
        ("wp_create_page", "content", {}),
        ("wc_create_product", "description", {"name": "Widget"}),
        ("wc_update_product", "description", {"id": 1}),
    ],
)
def test_long_content_reaches_the_site(
    http, transport_factory, operation_id: str, field: str, extra: dict
) -> None:
    body = "<p>" + ("word " * 4000) + "</p>"
    http.queue(json_response({"id": 1}, status=201))
    response = _run(operation_id, {**extra, field: body}, transport_factory, **WOO)

    assert response["ok"] is True, response.get("error")
    assert http.json_body()[field] == body


def test_a_query_parameter_stays_bounded(http, transport_factory) -> None:
    """A query string still cannot grow without limit."""
    response = _run("wp_list_posts", {"search": "x" * 5000}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_an_oversized_request_body_is_still_refused(http, transport_factory) -> None:
    response = _run("wp_create_post", {"content": "x" * (3 * 1024 * 1024)}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


# -- 4. Batch members are separate closed schemas ------------------------


def test_create_and_update_batch_members_have_different_schemas() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "batch":
            continue
        create = {field["name"] for field in batch_item_fields(row, "create")}
        update = {field["name"] for field in batch_item_fields(row, "update")}
        assert "id" not in create, row.operation_id
        assert "id" in update, row.operation_id
        required_update = {
            field["name"] for field in batch_item_fields(row, "update") if field.get("required")
        }
        assert required_update == {"id"}, row.operation_id


def test_batch_item_schemas_are_published_closed_with_required_fields() -> None:
    inputs = {field["name"]: field for field in operation_inputs(operation("wc_batch_coupons"))}
    create_schema = inputs["create_items"]["schema"]["items"]
    update_schema = inputs["update_items"]["schema"]["items"]

    assert create_schema["additionalProperties"] is False
    assert update_schema["additionalProperties"] is False
    assert create_schema["required"] == ["code"]
    assert update_schema["required"] == ["id"]


def test_a_create_item_missing_a_required_field_is_refused(http, transport_factory) -> None:
    response = _run("wc_batch_coupons", {"create_items": [{}]}, transport_factory, **WOO)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_an_update_item_without_an_id_is_refused(http, transport_factory) -> None:
    response = _run(
        "wc_batch_coupons", {"update_items": [{"amount": "5"}]}, transport_factory, **WOO
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_valid_batch_members_reach_the_native_body(http, transport_factory) -> None:
    http.queue(json_response({"create": [], "update": []}))
    response = _run(
        "wc_batch_coupons",
        {"create_items": [{"code": "SAVE10"}], "update_items": [{"id": 7, "amount": "5"}]},
        transport_factory,
        **WOO,
    )
    assert response["ok"] is True
    assert http.json_body() == {
        "create": [{"code": "SAVE10"}],
        "update": [{"id": 7, "amount": "5"}],
    }


# -- 6. Trash is destructive by outcome ----------------------------------


def test_no_write_contract_offers_a_trash_status() -> None:
    for table in (BODY_FIELDS,):
        for operation_id, fields in table.items():
            for field in fields:
                values = {str(value).lower() for value in (field.get("enum") or [])}
                assert "trash" not in values, (operation_id, field["name"])
    for operation_id, members in BATCH_ITEM_FIELDS.items():
        for member, fields in members.items():
            for field in fields:
                values = {str(value).lower() for value in (field.get("enum") or [])}
                assert "trash" not in values, (operation_id, member, field["name"])


@pytest.mark.parametrize(
    ("operation_id", "operation_input"),
    [
        ("wc_update_order", {"id": 1, "status": "trash"}),
        ("wc_create_order", {"status": "trash"}),
        ("wc_update_product_review", {"id": 1, "status": "trash"}),
        ("wc_batch_orders", {"update_items": [{"id": 1, "status": "trash"}]}),
        ("wc_batch_product_reviews", {"create_items": [{"status": "trash"}]}),
    ],
)
def test_writing_a_trash_status_is_refused_before_io(
    http, transport_factory, operation_id: str, operation_input: dict
) -> None:
    response = _run(operation_id, operation_input, transport_factory, **WOO)

    assert response["ok"] is False
    assert response["error_code"] == errors.UNSUPPORTED_OPERATION
    assert http.requests == []


def test_reading_trashed_records_is_still_available(http, transport_factory) -> None:
    """Filtering for trashed records is a read and stays supported."""
    http.queue(json_response([]))
    response = _run("wc_list_orders", {"status": ["trash"]}, transport_factory, **WOO)

    assert response["ok"] is True
    assert php_parse_str(http.last["url"].split("?", 1)[1])["status"] == ["trash"]


# -- 7. The bundle has no trailing blank lines ---------------------------


def test_no_bundle_file_ends_with_a_blank_line() -> None:
    """`git diff --check` fails on a blank line at end of file."""
    offenders = []
    for path in sorted(BUNDLE_ROOT.rglob("*")):
        if not path.is_file() or "dev-wheels" in path.parts or path.suffix == ".whl":
            continue
        if path.suffix not in {".py", ".yaml", ".yml", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        if text.endswith("\n\n") or (text and not text.endswith("\n")):
            offenders.append(str(path.relative_to(BUNDLE_ROOT)))
    assert offenders == []


def test_the_operation_and_batch_registries_agree() -> None:
    batch_ops = {row.operation_id for row in REST_OPERATIONS if row.shape == "batch"}
    assert set(BATCH_ITEM_FIELDS) == batch_ops
    for operation_id in batch_ops:
        assert REST_OPERATIONS_BY_ID[operation_id].method == "POST"
