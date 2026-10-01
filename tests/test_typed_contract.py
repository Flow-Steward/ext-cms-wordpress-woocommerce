"""The operations are typed contracts, not route-bound passthroughs."""

from __future__ import annotations

import pytest
from conftest import connection_payload, json_response, php_parse_str, sample_input
from runtime import errors
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID, operation
from runtime.io_shapes import body_field_names, input_field_names, query_field_names
from runtime.operations import handle_runtime
from runtime.parameters import BODY_FIELDS, NESTED_MODELS, QUERY_FIELDS, RESPONSE_FIELDS

WOO = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret

#: Fields a WordPress or WooCommerce plugin adds. None is part of the documented
#: Core or WooCommerce surface, so none may reach a site through this extension.
PLUGIN_FIELDS = (
    "acf",
    "lang",
    "wpml_language",
    "polylang",
    "yoast_head",
    "_yoast_wpseo_title",
    "rank_math_title",
    "elementor_data",
    "meta_box",
    "custom_field",
)


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


# -- No free-form envelopes remain ---------------------------------------


def test_no_operation_exposes_a_free_form_query_or_payload_input() -> None:
    for row in REST_OPERATIONS:
        names = input_field_names(row)
        assert "query" not in names, row.operation_id
        assert "payload" not in names, row.operation_id
        assert "body" not in names, row.operation_id


def test_every_mutation_declares_its_documented_write_fields() -> None:
    for row in REST_OPERATIONS:
        if row.shape not in {"create", "update", "batch", "media_create"}:
            continue
        assert BODY_FIELDS[row.operation_id], row.operation_id


def test_every_declared_field_carries_a_concrete_type() -> None:
    # "json" is the documented mixed type: WooCommerce declares setting values
    # as mixed, and some arrays have no stated element type.
    allowed = {"text", "integer", "number", "boolean", "array", "object", "json"}
    for operation_id, fields in list(QUERY_FIELDS.items()) + list(BODY_FIELDS.items()):
        for field in fields:
            assert field["value_type"] in allowed, (operation_id, field)
            if field["value_type"] == "array":
                assert field.get("item_type"), (operation_id, field)


def test_enumerations_reach_the_declared_contract() -> None:
    context = next(field for field in QUERY_FIELDS["wp_list_posts"] if field["name"] == "context")
    assert context["enum"] == ["view", "embed", "edit"]
    status = next(field for field in BODY_FIELDS["wp_create_post"] if field["name"] == "status")
    assert status["enum"] == ["publish", "future", "draft", "pending", "private"]


def test_required_fields_come_from_the_documentation() -> None:
    """Both providers' required markers reach the generated tables.

    WooCommerce tags a mandatory field ``MANDATORY``; WordPress appends
    ``Required: 1``. Only the first was ever read, so every WordPress required
    field was published as optional.
    """
    assert {
        field["name"] for field in BODY_FIELDS["wc_create_coupon"] if field.get("required")
    } == {"code"}
    assert {
        field["name"] for field in BODY_FIELDS["wc_create_customer"] if field.get("required")
    } == {"email"}
    assert {
        field["name"] for field in BODY_FIELDS["wp_create_category"] if field.get("required")
    } == {"name"}
    assert {field["name"] for field in BODY_FIELDS["wp_create_tag"] if field.get("required")} == {
        "name"
    }
    assert {
        field["name"] for field in BODY_FIELDS["wp_create_widget"] if field.get("required")
    } == {"sidebar"}


def test_nested_structures_are_modelled() -> None:
    billing = next(field for field in BODY_FIELDS["wc_create_order"] if field["name"] == "billing")
    assert billing["value_type"] == "object"
    model = NESTED_MODELS[billing["nested"]]
    assert {entry["name"] for entry in model} >= {"first_name", "last_name", "email", "country"}


def test_responses_are_modelled_from_the_documented_schema() -> None:
    fields = {entry["name"] for entry in RESPONSE_FIELDS["wp_get_post"]}
    assert {"id", "date", "slug", "status", "title", "content", "author"} <= fields
    order = {entry["name"] for entry in RESPONSE_FIELDS["wc_get_order"]}
    assert {"id", "status", "currency", "total", "billing", "line_items"} <= order


# -- Undocumented fields are refused before I/O --------------------------


@pytest.mark.parametrize("field", PLUGIN_FIELDS)
def test_plugin_specific_fields_are_refused_on_a_read(http, transport_factory, field: str) -> None:
    response = _run("wp_list_posts", {field: "value"}, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize("field", PLUGIN_FIELDS)
def test_plugin_specific_fields_are_refused_on_a_write(http, transport_factory, field: str) -> None:
    response = _run("wp_create_post", {"title": "x", field: "value"}, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize("field", PLUGIN_FIELDS)
def test_plugin_specific_fields_are_refused_inside_a_batch_item(
    http, transport_factory, field: str
) -> None:
    response = _run(
        "wc_batch_products",
        {"create_items": [{"name": "Widget", field: "value"}]},
        transport_factory,
        **WOO,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize("field", ["acf", "lang", "unknown_child"])
def test_plugin_specific_fields_are_refused_inside_a_nested_object(
    http, transport_factory, field: str
) -> None:
    response = _run(
        "wc_create_order",
        {"billing": {"first_name": "Ada", field: "value"}},
        transport_factory,
        **WOO,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_field_documented_for_another_operation_is_still_refused(http, transport_factory) -> None:
    """`sticky` is documented for posts, not for pages."""
    assert "sticky" in body_field_names(operation("wp_create_post"))
    assert "sticky" not in body_field_names(operation("wp_create_page"))
    response = _run("wp_create_page", {"title": "x", "sticky": True}, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_query_parameter_documented_for_another_provider_is_refused(
    http, transport_factory
) -> None:
    assert "dates_are_gmt" in query_field_names(operation("wc_list_orders"))
    assert "dates_are_gmt" not in query_field_names(operation("wp_list_posts"))
    response = _run("wp_list_posts", {"dates_are_gmt": True}, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


# -- Values are checked against their documented type --------------------


@pytest.mark.parametrize(
    ("operation_id", "operation_input"),
    [
        ("wp_list_posts", {"context": "superuser"}),
        ("wp_list_posts", {"page": "first"}),
        ("wp_list_posts", {"sticky": "yes"}),
        ("wp_list_posts", {"include": "1,2,3"}),
        ("wp_list_posts", {"include": [{"nested": True}]}),
        ("wp_create_post", {"status": "archived"}),
        ("wp_create_post", {"author": "ada"}),
        ("wp_create_post", {"title": 42}),
        ("wp_create_post", {"meta": []}),
    ],
)
def test_values_that_contradict_the_documented_type_are_refused(
    http, transport_factory, operation_id: str, operation_input: dict
) -> None:
    response = _run(operation_id, operation_input, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_rendered_field_accepts_both_documented_forms(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201), json_response({"id": 2}, status=201))
    _run("wp_create_post", {"title": "plain"}, transport_factory)
    _run("wp_create_post", {"title": {"raw": "structured"}}, transport_factory)

    assert http.requests[0]["body"] == b'{"title":"plain"}'
    assert http.json_body(1) == {"title": {"raw": "structured"}}


def test_array_query_parameters_survive_php_parsing(http, transport_factory) -> None:
    """A repeated bare key would arrive at WordPress as its last value only."""
    http.queue(json_response([]))
    _run("wp_list_posts", {"include": [4, 9], "status": ["publish", "draft"]}, transport_factory)
    parsed = php_parse_str(http.last["url"].split("?", 1)[1])

    assert parsed["include"] == ["4", "9"]
    assert parsed["status"] == ["publish", "draft"]


def test_a_single_valued_filter_is_not_sent_as_an_array(http, transport_factory) -> None:
    http.queue(json_response([]))
    _run("wp_list_posts", {"search": "widget", "page": 2}, transport_factory)
    parsed = php_parse_str(http.last["url"].split("?", 1)[1])

    assert parsed["search"] == "widget"
    assert parsed["page"] == "2"


def test_every_array_filter_uses_bracket_syntax(http, transport_factory) -> None:
    """No list filter may be emitted in the lossy repeated-key form."""
    from runtime.parameters import QUERY_FIELDS

    checked = 0
    for row in REST_OPERATIONS:
        arrays = [f for f in QUERY_FIELDS[row.operation_id] if f["value_type"] == "array"]
        if not arrays:
            continue
        operation_input = sample_input(row)
        for field in arrays:
            item = (
                1 if field.get("item_type") == "integer" else ((field.get("enum") or ["sample"])[0])
            )
            operation_input[field["name"]] = [item, item]
        http.responses.clear()
        http.queue(json_response([] if row.shape == "list" else {}))
        response = _run(row.operation_id, operation_input, transport_factory, **WOO)
        assert response["ok"] is True, (row.operation_id, response.get("error"))
        parsed = php_parse_str(http.last["url"].split("?", 1)[1])
        for field in arrays:
            assert isinstance(parsed.get(field["name"]), list), (row.operation_id, field["name"])
            assert len(parsed[field["name"]]) == 2
            checked += 1
    assert checked > 20


def test_every_operation_accepts_its_full_documented_surface(http, transport_factory) -> None:
    """Nothing the reference documents for a route is rejected by the runtime."""
    for row in REST_OPERATIONS:
        if row.shape == "media_create":
            continue  # exercised by the media suite, which needs an artifact grant
        http.responses.clear()
        http.queue(json_response([] if row.shape == "list" else {"ok": True}))
        response = _run(
            row.operation_id, sample_input(row, include_optional=True), transport_factory, **WOO
        )
        assert response["ok"] is True, (row.operation_id, response.get("error"))


def test_documented_query_values_reach_the_native_request(http, transport_factory) -> None:
    http.queue(json_response([]))
    _run(
        "wc_list_products",
        {"status": "publish", "per_page": 25, "featured": True},
        transport_factory,
        **WOO,
    )
    query = http.last["url"].split("?", 1)[1]
    assert "status=publish" in query
    assert "per_page=25" in query
    assert "featured=true" in query


def test_the_registry_and_the_parameter_tables_cover_the_same_operations() -> None:
    assert set(QUERY_FIELDS) == set(REST_OPERATIONS_BY_ID)
    assert set(BODY_FIELDS) == set(REST_OPERATIONS_BY_ID)
    assert set(RESPONSE_FIELDS) == set(REST_OPERATIONS_BY_ID)


# -- Closed schemas and native open containers ---------------------------


def test_closed_request_schemas_are_published_as_closed() -> None:
    """A documented nested structure declares itself closed in the manifest."""
    from runtime.io_shapes import field_schema

    billing = next(field for field in BODY_FIELDS["wc_create_order"] if field["name"] == "billing")
    schema = field_schema(billing)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "first_name" in schema["properties"]


def test_native_open_containers_stay_open() -> None:
    """WordPress `meta` and WooCommerce `meta_data` are open by design."""
    from runtime.io_shapes import field_schema

    meta = next(field for field in BODY_FIELDS["wp_create_post"] if field["name"] == "meta")
    assert field_schema(meta) == {"type": "object"}
    assert "nested" not in meta or not meta["nested"]


def test_a_native_meta_container_accepts_site_registered_keys(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201))
    response = _run(
        "wp_create_post",
        {"title": "x", "meta": {"campaign_id": "spring", "priority": 3}},
        transport_factory,
    )
    assert response["ok"] is True
    assert http.json_body()["meta"] == {"campaign_id": "spring", "priority": 3}


def test_woocommerce_meta_data_accepts_the_documented_entry_shape(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201))
    response = _run(
        "wc_create_product",
        {"name": "Widget", "meta_data": [{"key": "warehouse", "value": "north"}]},
        transport_factory,
        **WOO,
    )
    assert response["ok"] is True
    assert http.json_body()["meta_data"] == [{"key": "warehouse", "value": "north"}]


def test_a_meta_container_does_not_become_a_plugin_field(http, transport_factory) -> None:
    """Supporting native meta must not make `acf` a top-level field."""
    response = _run("wp_create_post", {"title": "x", "acf": {"hero": "value"}}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_every_operation_declares_the_version_it_arrived_in() -> None:
    from runtime.descriptions import INITIAL_VERSION, OPERATION_DOCS

    for row in REST_OPERATIONS:
        assert OPERATION_DOCS[row.operation_id].introduced_in == INITIAL_VERSION


def test_runtime_dispatch_accepts_nothing_the_manifest_omits() -> None:
    """The published contract and the runtime contract are the same set."""
    from pathlib import Path

    import yaml

    bundle = Path(__file__).resolve().parents[1]
    operations = {
        row["operation_id"]: row
        for row in yaml.safe_load((bundle / "contracts/operation_manifest.yaml").read_text())[
            "operations"
        ]
    }
    forms = {
        row["operation_id"]: row
        for row in yaml.safe_load((bundle / "contracts/step_ui_manifest.yaml").read_text())["forms"]
    }
    actions = {
        row["action_id"]: row
        for row in yaml.safe_load((bundle / "ui/actions/actions.yaml").read_text())["actions"]
    }
    for row in REST_OPERATIONS:
        published = {field["name"] for field in operations[row.operation_id]["inputs"]}
        runtime = set(input_field_names(row))
        assert published == runtime, row.operation_id
        assert {f["name"] for f in forms[row.operation_id]["fields"]} == runtime - {
            "connection_ref"
        }
        assert {p["name"] for p in actions[row.operation_id]["parameters"]} == runtime
