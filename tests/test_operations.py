"""Executing declared operations issues exactly the native request, and nothing more."""

from __future__ import annotations

import pytest
from conftest import connection_payload, json_response, sample_input
from runtime import errors
from runtime.catalog import REST_OPERATIONS, operation
from runtime.io_shapes import result_field_names
from runtime.operations import handle_runtime

WOO = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret


def _run(operation_id, operation_input, transport_factory, **kwargs):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=transport_factory,
    )


def test_a_read_returns_the_declared_result_fields(http, transport_factory) -> None:
    http.queue(json_response({"id": 12, "title": {"rendered": "Hello"}}))
    response = _run("wp_get_post", {"id": 12}, transport_factory)

    assert response["ok"] is True
    assert set(response["result"]) == set(result_field_names(operation("wp_get_post")))
    assert response["result"]["data"]["id"] == 12
    assert response["result"]["http_status"] == 200
    assert http.last["method"] == "GET"
    assert http.last["url"] == "https://shop.example/wp-json/wp/v2/posts/12"
    assert http.last["body"] is None


def test_a_list_returns_items_and_pagination(http, transport_factory) -> None:
    http.queue(
        json_response(
            [{"id": 1}, {"id": 2}],
            headers={
                "X-WP-Total": "42",
                "X-WP-TotalPages": "3",
                "Link": '<https://shop.example/wp-json/wp/v2/posts?page=3>; rel="next"',
            },
        )
    )
    response = _run("wp_list_posts", {"page": 2, "per_page": 20}, transport_factory)
    result = response["result"]

    assert result["items"] == [{"id": 1}, {"id": 2}]
    assert result["pagination"] == {
        "total": 42,
        "total_pages": 3,
        "page": 2,
        "per_page": 20,
        "next_link": "https://shop.example/wp-json/wp/v2/posts?page=3",
        "previous_link": None,
        "has_more": True,
    }
    assert "page=2" in http.last["url"]
    assert "per_page=20" in http.last["url"]


def test_a_list_that_does_not_return_an_array_is_reported_as_upstream_failure(
    http, transport_factory
) -> None:
    http.queue(json_response({"unexpected": True}))
    response = _run("wp_list_posts", {}, transport_factory)
    assert response["ok"] is False
    assert response["error_code"] == "upstream_failure"


def test_a_create_sends_the_documented_fields_verbatim_and_reports_the_effect(
    http, transport_factory
) -> None:
    payload = {"title": "Launch", "status": "draft", "meta": {"campaign": "spring"}}
    http.queue(json_response({"id": 99}, status=201))
    response = _run("wp_create_post", dict(payload), transport_factory)

    assert response["ok"] is True
    assert response["external_effect_status"] == "succeeded"
    assert response["result"]["http_status"] == 201
    assert http.last["method"] == "POST"
    assert http.last["url"] == "https://shop.example/wp-json/wp/v2/posts"
    assert http.json_body() == payload
    assert http.last["headers"]["content-type"].startswith("application/json")


def test_an_update_uses_the_documented_method_per_provider(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}), json_response({"id": 1}))
    _run("wp_update_post", {"id": 1, "title": "x"}, transport_factory)
    _run("wc_update_product", {"id": 1, "name": "x"}, transport_factory, **WOO)

    assert http.requests[0]["method"] == "POST"
    assert http.requests[1]["method"] == "PUT"


def test_a_stock_update_issues_only_the_requested_native_request(http, transport_factory) -> None:
    http.queue(json_response({"id": 55, "stock_quantity": 7}))
    response = _run(
        "wc_update_product",
        {"id": 55, "stock_quantity": 7, "manage_stock": True},
        transport_factory,
        **WOO,
    )

    assert response["ok"] is True
    assert len(http.requests) == 1
    assert http.last["method"] == "PUT"
    assert http.last["url"] == "https://shop.example/wp-json/wc/v3/products/55"
    assert http.json_body() == {"stock_quantity": 7, "manage_stock": True}


def test_a_price_update_on_a_variation_issues_only_that_request(http, transport_factory) -> None:
    http.queue(json_response({"id": 9, "regular_price": "19.00"}))
    _run(
        "wc_update_product_variation",
        {"product_id": 3, "id": 9, "regular_price": "19.00"},
        transport_factory,
        **WOO,
    )

    assert len(http.requests) == 1
    assert http.last["url"] == "https://shop.example/wp-json/wc/v3/products/3/variations/9"
    assert http.json_body() == {"regular_price": "19.00"}


def test_a_documented_batch_price_update_issues_one_batch_request(http, transport_factory) -> None:
    http.queue(json_response({"update": [{"id": 1}, {"id": 2}]}))
    _run(
        "wc_batch_products",
        {"update_items": [{"id": 1, "regular_price": "5"}, {"id": 2, "regular_price": "6"}]},
        transport_factory,
        **WOO,
    )

    assert len(http.requests) == 1
    assert http.last["url"] == "https://shop.example/wp-json/wc/v3/products/batch"
    assert http.json_body() == {
        "update": [{"id": 1, "regular_price": "5"}, {"id": 2, "regular_price": "6"}]
    }


def test_a_product_batch_returns_compact_receipts_instead_of_full_catalog_records(
    http, transport_factory
) -> None:
    """A bulk mutation must not copy full product bodies into every workflow checkpoint."""
    http.queue(
        json_response(
            {
                "update": [
                    {
                        "id": 1,
                        "sku": "SKU-1",
                        "status": "publish",
                        "stock_status": "instock",
                        "stock_quantity": 7,
                        "regular_price": "5.00",
                        "price": "5.00",
                        "description": "x" * 100_000,
                        "images": [{"src": "https://cdn.example/large.jpg"}],
                    }
                ]
            }
        )
    )

    response = _run(
        "wc_batch_products",
        {"update_items": [{"id": 1, "stock_quantity": 7}]},
        transport_factory,
        **WOO,
    )

    assert response["ok"] is True
    assert response["result"]["data"] == {
        "update": [
            {
                "id": 1,
                "sku": "SKU-1",
                "status": "publish",
                "stock_status": "instock",
                "stock_quantity": 7,
                "regular_price": "5.00",
                "price": "5.00",
            }
        ]
    }


def test_a_batch_with_only_rejected_items_fails_instead_of_reporting_success(
    http, transport_factory
) -> None:
    rejected = {
        "create": [
            {
                "id": 0,
                "error": {
                    "code": "product_invalid_sku",
                    "message": "Invalid or duplicated SKU.",
                    "data": {"status": 400, "resource_id": 15},
                },
            }
        ]
    }
    http.queue(json_response(rejected))

    response = _run(
        "wc_batch_products",
        {"create_items": [{"name": "Duplicate", "sku": "DUPLICATE"}]},
        transport_factory,
        **WOO,
    )

    assert response["ok"] is False
    assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED
    assert response["external_effect_status"] == "failed"
    assert response["definitely_no_external_effect"] is True
    assert response["result"]["data"] == rejected


def test_a_mixed_batch_fails_but_preserves_the_known_partial_effect(
    http, transport_factory
) -> None:
    mixed = {
        "create": [
            {"id": 91, "name": "Created"},
            {
                "id": 0,
                "error": {
                    "code": "product_invalid_sku",
                    "message": "Invalid or duplicated SKU.",
                    "data": {"status": 400, "resource_id": 15},
                },
            },
        ]
    }
    http.queue(json_response(mixed))

    response = _run(
        "wc_batch_products",
        {
            "create_items": [
                {"name": "Created", "sku": "NEW"},
                {"name": "Duplicate", "sku": "DUPLICATE"},
            ]
        },
        transport_factory,
        **WOO,
    )

    assert response["ok"] is False
    assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED
    assert response["external_effect_status"] == "failed"
    assert response["definitely_no_external_effect"] is False
    assert response["result"] == {
        "data": {
            "create": [
                {"id": 91},
                {
                    "id": 0,
                    "error": {
                        "code": "product_invalid_sku",
                        "message": "Invalid or duplicated SKU.",
                        "data": {"status": 400, "resource_id": 15},
                    },
                },
            ]
        },
        "http_status": 200,
        "external_effect_status": "failed",
        "definitely_no_external_effect": False,
    }


@pytest.mark.parametrize(
    "operation_id",
    [
        "wc_list_webhooks",
        "wc_get_webhook",
        "wc_create_webhook",
        "wc_update_webhook",
        "wc_batch_webhooks",
        "wp_create_user",
        "wp_update_user",
        "wp_update_current_user",
    ],
)
def test_a_withdrawn_operation_is_refused_before_any_request(
    operation_id: str, http, transport_factory
) -> None:
    """Withdrawn operations are gone, not hidden.

    Nothing is dispatched and no transport is built: the runtime refuses the
    identifier itself, so there is no alias or stub left to call.
    """
    response = _run(operation_id, {"topic": "order.created"}, transport_factory, **WOO)

    assert response["ok"] is False
    assert response["error_code"] == errors.UNSUPPORTED_OPERATION
    assert http.requests == []


def test_a_native_order_action_posts_to_the_documented_action_route(
    http, transport_factory
) -> None:
    http.queue(json_response({"message": "sent"}))
    response = _run("wc_send_order_details", {"id": 21}, transport_factory, **WOO)

    assert response["ok"] is True
    assert http.last["url"] == (
        "https://shop.example/wp-json/wc/v3/orders/21/actions/send_order_details"
    )
    assert response["external_effect_status"] == "succeeded"


def test_a_read_shaped_post_carries_no_external_effect(http, transport_factory) -> None:
    http.queue(json_response({"rendered": "<p>hi</p>"}))
    response = _run(
        "wp_render_block",
        {"name": "core/paragraph", "attributes": {}},
        transport_factory,
    )

    assert response["ok"] is True
    assert "external_effect_status" not in response
    assert http.last["url"] == "https://shop.example/wp-json/wp/v2/block-renderer/core/paragraph"


def test_test_mode_suppresses_every_mutation_before_io(http, transport_factory) -> None:
    for row in REST_OPERATIONS:
        if not row.has_external_effect:
            continue
        operation_input = sample_input(row)
        response = handle_runtime(
            connection_payload(
                row.operation_id,
                operation_input,
                runtime_context={"test_mode": True},
                **WOO,
            ),
            transport_factory=transport_factory,
        )
        assert response["ok"] is True, row.operation_id
        assert response["external_effect_status"] == "suppressed", row.operation_id
        assert response["definitely_no_external_effect"] is True, row.operation_id
    assert http.requests == []


def test_reads_are_never_suppressed_in_test_mode(http, transport_factory) -> None:
    http.queue(json_response([{"id": 1}]))
    response = handle_runtime(
        connection_payload("wp_list_posts", {}, runtime_context={"test_mode": True}),
        transport_factory=transport_factory,
    )
    assert response["result"]["items"] == [{"id": 1}]
    assert len(http.requests) == 1


@pytest.mark.parametrize(
    ("operation_id", "operation_input", "expected_url"),
    [
        (
            "wp_get_theme",
            {"stylesheet": "twentytwentyfour"},
            "https://shop.example/wp-json/wp/v2/themes/twentytwentyfour",
        ),
        (
            "wp_get_plugin",
            {"plugin": "akismet/akismet"},
            "https://shop.example/wp-json/wp/v2/plugins/akismet/akismet",
        ),
        (
            "wp_get_block_type",
            {"namespace": "core", "name": "paragraph"},
            "https://shop.example/wp-json/wp/v2/block-types/core/paragraph",
        ),
        ("wp_get_current_user", {}, "https://shop.example/wp-json/wp/v2/users/me"),
        (
            "wp_get_post_revision",
            {"parent": 4, "id": 9},
            "https://shop.example/wp-json/wp/v2/posts/4/revisions/9",
        ),
        (
            "wc_get_order_note",
            {"id": 3, "note_id": 8},
            "https://shop.example/wp-json/wc/v3/orders/3/notes/8",
        ),
        (
            "wc_get_setting_option",
            {"group_id": "general", "id": "woocommerce_currency"},
            "https://shop.example/wp-json/wc/v3/settings/general/woocommerce_currency",
        ),
        (
            "wc_get_current_currency",
            {},
            "https://shop.example/wp-json/wc/v3/data/currencies/current",
        ),
    ],
)
def test_documented_routes_are_built_exactly(
    http, transport_factory, operation_id: str, operation_input: dict, expected_url: str
) -> None:
    row = operation(operation_id)
    http.queue(json_response({} if row.shape != "list" else []))
    _run(operation_id, operation_input, transport_factory, **WOO)
    assert http.last["url"] == expected_url


def test_every_declared_operation_round_trips_through_the_runtime(http, transport_factory) -> None:
    """No declared operation is missing a runtime handler."""
    for row in REST_OPERATIONS:
        if row.shape == "media_create":
            continue  # covered by the media suite, which needs an artifact grant
        operation_input = sample_input(row)
        http.responses.clear()
        http.queue(json_response([] if row.shape == "list" else {"ok": True}))
        response = _run(row.operation_id, operation_input, transport_factory, **WOO)
        assert response["ok"] is True, (row.operation_id, response.get("error_code"))
        assert set(response["result"]) >= set(result_field_names(row)), row.operation_id
