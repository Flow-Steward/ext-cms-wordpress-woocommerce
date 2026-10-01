"""Everything the extension must refuse, and refuse before any outbound I/O."""

from __future__ import annotations

import pytest
from conftest import connection_payload, json_response
from dispatcher import OPERATION_REGISTRY, dispatch_runtime
from runtime import errors
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID, operation
from runtime.catalog_export import EXPORT_PRODUCTS_OPERATION_ID
from runtime.connection import Connection
from runtime.errors import ExtensionError
from runtime.operations import handle_runtime
from runtime.transport import RestTransport
from runtime.validation import assert_no_delete_member, batch_body

WOO_CREDENTIALS = {
    "consumer_key": "ck",
    "consumer_secret": "cs",  # pragma: allowlist secret
}

CONNECTION = Connection(
    connection_id="conn-1",
    site_url="https://shop.example",
    wordpress_username="svc",
    _wordpress_application_password="pw",  # pragma: allowlist secret
    _woocommerce_consumer_key="ck",
    _woocommerce_consumer_secret="cs",  # pragma: allowlist secret
)


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


# -- Unknown operations ---------------------------------------------------


@pytest.mark.parametrize(
    "operation_id",
    [
        "wp_delete_post",
        "wc_delete_order",
        "generic_request",
        "raw_request",
        "custom_endpoint",
        "api_explorer",
        "wp_list_menus",
        "wp_list_templates",
        "wp_get_global_styles",
        "acf_get_fields",
        "wpml_list_translations",
        "yoast_get_seo",
        "",
        "   ",
    ],
)
def test_unknown_operation_ids_are_refused_before_io(
    http, transport_factory, operation_id: str
) -> None:
    response = _run(operation_id, {}, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] in {errors.UNSUPPORTED_OPERATION, errors.INVALID_PAYLOAD}
    assert http.requests == []


def test_the_dispatcher_refuses_an_unknown_operation_without_touching_the_runtime(http) -> None:
    response = dispatch_runtime(connection_payload("wp_delete_post", {}))
    assert response["ok"] is False
    assert response["error_code"] == errors.UNSUPPORTED_OPERATION
    assert http.requests == []


def test_no_registry_entry_exists_for_any_destructive_or_lifecycle_operation() -> None:
    for operation_id in (
        "wp_delete_post",
        "wp_delete_media",
        "wp_install_plugin",
        "wp_activate_plugin",
        "wp_install_theme",
        "wp_create_application_password",
        "wp_rotate_application_password",
        "wc_delete_order",
        "wc_create_refund",
        "wc_update_refund",
        "wc_run_system_status_tool",
    ):
        assert operation(operation_id) is None


def test_the_registry_declares_no_delete_method_anywhere() -> None:
    assert {row.method for row in REST_OPERATIONS} == {"GET", "POST", "PUT"}


# -- Envelope shape -------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mode": "query", "query": {"query_id": "anything"}},
        {"mode": "action"},
        {"mode": "action", "action": []},
        {"mode": "action", "action": {"action_id": "wp_list_posts", "smuggled": 1}},
    ],
)
def test_malformed_envelopes_are_refused(http, transport_factory, payload: dict) -> None:
    response = handle_runtime(payload, transport_factory=transport_factory)

    assert response["ok"] is False
    assert response["error_code"] in {errors.INVALID_PAYLOAD, errors.UNSUPPORTED_OPERATION}
    assert http.requests == []


@pytest.mark.parametrize(
    "operation_input",
    [
        {"unexpected_field": 1},
        {"method": "DELETE"},
        {"path": "/wp-json/wp/v2/posts/1"},
        {"url": "https://attacker.example"},
        {"namespace": "acf/v3"},
    ],
)
def test_undeclared_input_fields_are_refused(
    http, transport_factory, operation_input: dict
) -> None:
    response = _run("wp_list_posts", operation_input, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_missing_required_input_is_refused(http, transport_factory) -> None:
    response = _run("wp_get_post", {}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


# -- Path and query injection --------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["1/../../wp-json/wp/v2/users", "1?force=true", -1, "abc", True, None, 1.5, "1 2"],
)
def test_path_parameters_cannot_be_used_to_reach_another_route(
    http, transport_factory, value: object
) -> None:
    response = _run("wp_get_post", {"id": value}, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize("value", ["x" * 300, "", 5, True, 1.5, None, ["a"]])
def test_a_path_segment_outside_the_published_schema_is_refused(
    http, transport_factory, value: object
) -> None:
    """The published schema is a bounded string; the runtime enforces that."""
    response = _run("wp_get_post_type", {"type": value}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize("value", ["../../etc", "a/../b", ".."])
def test_a_path_segment_that_traverses_is_refused(http, transport_factory, value: str) -> None:
    """Traversal is refused by the transport, whatever the segment looks like."""
    response = _run("wp_get_post_type", {"type": value}, transport_factory)
    assert response["error_code"] == errors.UNSUPPORTED_OPERATION
    assert http.requests == []


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ("a/b/c", "a%2Fb%2Fc"),
        ("a b", "a%20b"),
        ("-leading", "-leading"),
        ("a?b", "a%3Fb"),
        ("with\x00null", "with%00null"),
    ],
)
def test_an_unusual_path_segment_is_contained_by_encoding(
    http, transport_factory, value: str, encoded: str
) -> None:
    """A segment the schema allows is sent, encoded so it cannot alter the URL."""
    http.queue(json_response({}))
    response = _run("wp_get_post_type", {"type": value}, transport_factory)

    assert response["ok"] is True
    assert http.last["url"] == f"https://shop.example/wp-json/wp/v2/types/{encoded}"


@pytest.mark.parametrize(
    "query",
    [
        {"force": {"nested": True}},
        {"bad key": 1},
        {"ok": [object()]},
        {"x": "line\nbreak"},
        "not-an-object",
        [("a", "b")],
    ],
)
def test_the_query_object_is_bounded_and_scalar_only(
    http, transport_factory, query: object
) -> None:
    response = _run("wp_list_posts", {"query": query}, transport_factory)
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_query_cannot_smuggle_a_second_host(http, transport_factory) -> None:
    http.queue(json_response([]))
    _run("wp_list_posts", {"search": "https://attacker.example/x"}, transport_factory)
    assert http.last["url"].startswith("https://shop.example/wp-json/wp/v2/posts?")
    origin, _, query = http.last["url"].partition("?")
    assert origin == "https://shop.example/wp-json/wp/v2/posts"
    assert query == "search=https%3A%2F%2Fattacker.example%2Fx"
    assert http.last["url"].count("://") == 1


# -- Namespace, method, and route guards ---------------------------------


def test_the_transport_refuses_an_unsupported_namespace() -> None:
    row = operation("wp_list_posts")
    forged = type(row)(**{**row.__dict__, "namespace": "acf/v3"})
    _raises_callable_234_1 = RestTransport(CONNECTION).build_url
    with pytest.raises(ExtensionError) as raised:
        _raises_callable_234_1(forged, {})
    assert raised.value.code == errors.UNSUPPORTED_OPERATION


def test_the_transport_refuses_an_unsupported_method() -> None:
    row = operation("wp_list_posts")
    forged = type(row)(**{**row.__dict__, "method": "DELETE"})
    _raises_callable_242_1 = RestTransport(CONNECTION).build_url
    with pytest.raises(ExtensionError) as raised:
        _raises_callable_242_1(forged, {})
    assert raised.value.code == errors.UNSUPPORTED_OPERATION


def test_the_transport_refuses_a_route_that_escapes_the_namespace() -> None:
    row = operation("wp_list_posts")
    for route in ("/../../wp-json/acf/v3/options", "/posts/{unbound}"):
        forged = type(row)(**{**row.__dict__, "route": route})
        _raises_callable_251_1 = RestTransport(CONNECTION).build_url
        with pytest.raises(ExtensionError) as raised:
            _raises_callable_251_1(forged, {})
        assert raised.value.code in {
            errors.UNSUPPORTED_OPERATION,
            errors.INVALID_PAYLOAD,
        }


def test_every_built_url_stays_under_the_connection_site(http, transport_factory) -> None:
    transport = RestTransport(CONNECTION, opener=http)
    for row in REST_OPERATIONS:
        values = {
            name: ("1" if kind == "integer" else "a/b" if kind == "namespaced_slug" else "slug")
            for name, kind in row.path_params
        }
        url = transport.build_url(row, values)
        assert url.startswith(f"https://shop.example/wp-json/{row.namespace}/")
        assert ".." not in url


# -- WooCommerce gating ---------------------------------------------------


def test_a_woocommerce_operation_without_keys_is_refused_before_io(http, transport_factory) -> None:
    response = _run("wc_list_orders", {}, transport_factory)

    assert response["error_code"] == errors.WOOCOMMERCE_NOT_CONFIGURED
    assert http.requests == []


def test_a_wordpress_operation_still_works_without_woocommerce_keys(
    http, transport_factory
) -> None:
    http.queue(json_response([{"id": 1}]))
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["ok"] is True


# -- Batch delete ---------------------------------------------------------


def test_a_batch_body_can_only_carry_create_and_update() -> None:
    body = batch_body({"create": [{"name": "a"}], "update": [{"id": 1}]})
    assert set(body) == {"create", "update"}
    with pytest.raises(ExtensionError) as raised:
        assert_no_delete_member({"create": [], "delete": [1]})
    assert raised.value.code == errors.UNSUPPORTED_OPERATION


def test_a_batch_operation_exposes_no_way_to_ask_for_a_delete(http, transport_factory) -> None:
    response = _run(
        "wc_batch_products",
        {"delete_items": [1, 2]},
        transport_factory,
        **WOO_CREDENTIALS,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_delete_key_inside_a_batch_item_is_refused_before_io(http, transport_factory) -> None:
    response = _run(
        "wc_batch_products",
        {"update_items": [{"id": 1, "delete": True}]},
        transport_factory,
        **WOO_CREDENTIALS,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_documented_batch_item_reaches_the_native_batch_body(http, transport_factory) -> None:
    http.queue(json_response({"update": [{"id": 1}]}))
    _run(
        "wc_batch_products",
        {"update_items": [{"id": 1, "regular_price": "9.99"}]},
        transport_factory,
        **WOO_CREDENTIALS,
    )
    body = http.json_body()
    assert set(body) == {"update"}
    assert body["update"] == [{"id": 1, "regular_price": "9.99"}]


@pytest.mark.parametrize(
    "operation_input",
    [
        {},
        {"create_items": [], "update_items": []},
        {"create_items": []},
        {"update_items": []},
    ],
)
def test_an_empty_batch_is_a_successful_no_op(http, transport_factory, operation_input) -> None:
    """A sync with nothing to push this run is correct, not an error.

    An idempotent catalogue sync legitimately computes an empty create and update
    array — nothing changed since the last run. Refusing that failed the whole
    workflow on the ordinary case, so an all-empty batch is now a no-op that
    performs no request at all and reports that nothing was sent.
    """
    response = _run(
        "wc_batch_products",
        operation_input,
        transport_factory,
        **WOO_CREDENTIALS,
    )
    assert response["ok"] is True, response
    result = response["result"]
    assert result["data"] == {"create": [], "update": []}
    assert result["definitely_no_external_effect"] is True
    assert http.requests == [], "an empty batch must not reach the site"


def test_a_batch_with_one_item_still_performs_the_request(http, transport_factory) -> None:
    """The no-op must not swallow a batch that does have work."""
    http.queue(json_response({"update": [{"id": 1}]}))
    response = _run(
        "wc_batch_products",
        {"create_items": [], "update_items": [{"id": 1, "regular_price": "9.99"}]},
        transport_factory,
        **WOO_CREDENTIALS,
    )
    assert response["ok"] is True, response
    assert response["result"]["definitely_no_external_effect"] is False
    assert len(http.requests) == 1


def test_batch_items_are_bounded(http, transport_factory) -> None:
    response = _run(
        "wc_batch_products",
        {"create_items": [{"name": str(index)} for index in range(101)]},
        transport_factory,
        **WOO_CREDENTIALS,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


@pytest.mark.parametrize(("key", "value"), [("page", "two"), ("per_page", 1.5)])
def test_pagination_inputs_are_typed(http, transport_factory, key: str, value: object) -> None:
    response = _run("wp_list_posts", {key: value}, transport_factory)

    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_single_resource_read_accepts_its_documented_query_parameters(
    http, transport_factory
) -> None:
    http.queue(json_response({"id": 1}))
    _run("wp_get_post", {"id": 1, "context": "edit"}, transport_factory)
    assert http.last["url"].endswith("/posts/1?context=edit")


def test_the_password_of_a_protected_record_is_refused_before_any_request(
    http, transport_factory
) -> None:
    """A content credential is not something a workflow sends.

    The field is documented, so refusing it has to be explicit rather than a
    silent drop, and it has to happen before anything reaches the network.
    """
    response = _run("wp_get_post", {"id": 1, "context": "edit", "password": "x"}, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []
    assert "x" not in str(response)


def test_discovery_never_adds_an_operation_to_the_catalog(http, transport_factory) -> None:
    """A site advertising extra namespaces and routes changes nothing."""
    before = dict(REST_OPERATIONS_BY_ID)
    http.queue(
        json_response(
            {
                "name": "Example",
                "namespaces": ["wp/v2", "wc/v3", "acf/v3", "wpml/v1", "yoast/v1", "custom/v9"],
                "routes": {
                    "/acf/v3/options": {"methods": ["GET", "POST"]},
                    "/wp/v2/product": {"methods": ["GET", "POST", "DELETE"]},
                },
            }
        ),
        json_response({"id": 1, "slug": "svc"}),
        json_response({"environment": {}}),
    )
    response = _run("test_connection", {}, transport_factory, **WOO_CREDENTIALS)

    assert response["ok"] is True
    assert dict(REST_OPERATIONS_BY_ID) == before
    assert set(OPERATION_REGISTRY) == set(before) | {
        "test_connection",
        "validate_connection_settings",
        EXPORT_PRODUCTS_OPERATION_ID,
    }
    # The advertised namespaces are reported as data, never turned into routes.
    assert "acf/v3" in response["result"]["namespaces"]
    for advertised in ("acf_get_options", "wp_list_product", "custom_v9"):
        assert operation(advertised) is None
        follow_up = _run(advertised, {}, transport_factory)
        assert follow_up["error_code"] in {
            errors.UNSUPPORTED_OPERATION,
            errors.INVALID_PAYLOAD,
        }


def test_the_registry_is_fixed_at_import_time() -> None:
    import runtime.catalog as catalog

    assert isinstance(catalog.REST_OPERATIONS, tuple)
    assert isinstance(catalog.OPERATION_IDS, frozenset)
    assert isinstance(catalog.SUPPORTED_NAMESPACES, frozenset)
    assert isinstance(catalog.SUPPORTED_METHODS, frozenset)
    for row in catalog.REST_OPERATIONS:
        with pytest.raises((AttributeError, TypeError)):
            row.route = "/anything-else"
