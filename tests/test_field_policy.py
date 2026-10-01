"""What the password policy refuses, and everything it must leave alone.

The policy is narrow on purpose: it names the documented credential fields of
specific operations. A rule that removed every key called ``password`` would
also strip a plugin's own metadata, a setting whose type happens to be
``password``, and ordinary content, so the tests below are as much about what
survives as about what is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import connection_payload, json_response
from runtime import errors
from runtime.catalog import REST_OPERATIONS, operation
from runtime.field_policy import (
    PASSWORD_FIELD,
    PASSWORD_RESPONSE_OPERATIONS,
    POST_PASSWORD_FIELD,
    PRODUCT_POST_PASSWORD_RESPONSE_OPERATIONS,
    sanitized_response_body,
)
from runtime.operations import handle_runtime
from runtime.parameters import (
    BATCH_ITEM_FIELDS,
    BODY_FIELDS,
    NESTED_CREATE_MODELS,
    NESTED_MODELS,
    NESTED_UPDATE_MODELS,
    QUERY_FIELDS,
    RESPONSE_FIELDS,
)

WOO = {"consumer_key": "ck_live", "consumer_secret": "cs_live"}  # pragma: allowlist secret


def _run(operation_id: str, operation_input: dict[str, Any], transport_factory, **extra):
    return handle_runtime(
        connection_payload(operation_id, operation_input, **extra),
        transport_factory=transport_factory,
    )


def test_no_supported_operation_publishes_a_password_anywhere() -> None:
    """The guard that survives new operations being added later."""
    leaks: list[str] = []
    for row in REST_OPERATIONS:
        for label, table in (
            ("query", QUERY_FIELDS),
            ("body", BODY_FIELDS),
            ("response", RESPONSE_FIELDS),
        ):
            if any(f["name"] == PASSWORD_FIELD for f in table.get(row.operation_id) or []):
                leaks.append(f"{label}:{row.operation_id}")
        for member, rows in (BATCH_ITEM_FIELDS.get(row.operation_id) or {}).items():
            if any(f["name"] == PASSWORD_FIELD for f in rows):
                leaks.append(f"batch.{member}:{row.operation_id}")
    for label, table in (
        ("nested", NESTED_MODELS),
        ("nested_create", NESTED_CREATE_MODELS),
        ("nested_update", NESTED_UPDATE_MODELS),
    ):
        for model, rows in table.items():
            if any(f["name"] == PASSWORD_FIELD for f in rows):
                leaks.append(f"{label}:{model}")
    assert leaks == []


@pytest.mark.parametrize(
    ("operation_id", "operation_input"),
    [
        ("wp_get_post", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_get_page", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_get_block", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_list_comments", {"password": "secret"}),  # pragma: allowlist secret
        ("wp_get_comment", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_create_post", {"title": "t", "password": "secret"}),  # pragma: allowlist secret
        ("wp_update_post", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_create_page", {"title": "t", "password": "secret"}),  # pragma: allowlist secret
        ("wp_update_page", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
        ("wp_create_block", {"title": "t", "password": "secret"}),  # pragma: allowlist secret
        ("wp_update_block", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
    ],
)
def test_an_excluded_password_input_is_refused_before_any_request(
    operation_id: str, operation_input: dict[str, Any], http, transport_factory
) -> None:
    response = _run(operation_id, operation_input, transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []
    assert "secret" not in str(response)


@pytest.mark.parametrize(
    ("operation_id", "operation_input"),
    [
        (
            "wc_create_customer",
            {"email": "a@example.com", "password": "secret"},  # pragma: allowlist secret
        ),
        ("wc_update_customer", {"id": 1, "password": "secret"}),  # pragma: allowlist secret
    ],
)
def test_a_customer_password_is_refused_before_any_request(
    operation_id: str, operation_input: dict[str, Any], http, transport_factory
) -> None:
    response = _run(operation_id, operation_input, transport_factory, **WOO)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []
    assert "secret" not in str(response)


@pytest.mark.parametrize("member", ["create", "update"])
def test_a_customer_batch_entry_carrying_a_password_rejects_the_whole_request(
    member: str, http, transport_factory
) -> None:
    entry: dict[str, Any] = {
        "email": "a@example.com",
        "password": "secret",  # pragma: allowlist secret
    }
    if member == "update":
        entry["id"] = 7
    response = _run("wc_batch_customers", {f"{member}_items": [entry]}, transport_factory, **WOO)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []
    assert "secret" not in str(response)


def test_a_returned_record_never_carries_the_excluded_property(http, transport_factory) -> None:
    http.queue(
        json_response(
            {"id": 1, "title": "Hello", "password": "secret"}  # pragma: allowlist secret
        )
    )
    response = _run("wp_get_post", {"id": 1}, transport_factory)

    assert response["ok"] is True
    assert response["result"]["data"] == {"id": 1, "title": "Hello"}
    assert "secret" not in str(response)


def test_a_returned_list_is_cleaned_item_by_item(http, transport_factory) -> None:
    http.queue(
        json_response(
            [
                {"id": 1, "password": "a"},  # pragma: allowlist secret
                {"id": 2, "password": "b"},  # pragma: allowlist secret
            ]
        )
    )
    response = _run("wp_list_posts", {}, transport_factory)

    assert response["result"]["items"] == [{"id": 1}, {"id": 2}]


def test_a_returned_customer_batch_is_cleaned_in_both_groups(http, transport_factory) -> None:
    http.queue(
        json_response(
            {
                "create": [
                    {
                        "id": 1,
                        "email": "a@example.com",
                        "password": "x",  # pragma: allowlist secret
                    }
                ],
                "update": [
                    {
                        "id": 2,
                        "email": "b@example.com",
                        "password": "y",  # pragma: allowlist secret
                    }
                ],
            }
        )
    )
    response = _run(
        "wc_batch_customers",
        {"create_items": [{"email": "a@example.com"}]},
        transport_factory,
        **WOO,
    )

    data = response["result"]["data"]
    assert data["create"] == [{"id": 1, "email": "a@example.com"}]
    assert data["update"] == [{"id": 2, "email": "b@example.com"}]


def test_unrelated_values_named_password_are_left_alone(http, transport_factory) -> None:
    """Nothing recurses, so a plugin's own metadata comes back untouched."""
    http.queue(
        json_response(
            {
                "id": 1,
                "password": "removed",  # pragma: allowlist secret
                "content": {"rendered": "<p>Reset your password here</p>"},
                "meta": {
                    "password": "kept",  # pragma: allowlist secret
                    "acf": {"password": "kept too"},  # pragma: allowlist secret
                },
            }
        )
    )
    response = _run("wp_get_post", {"id": 1}, transport_factory)

    data = response["result"]["data"]
    assert PASSWORD_FIELD not in data
    assert data["meta"] == {
        "password": "kept",  # pragma: allowlist secret
        "acf": {"password": "kept too"},  # pragma: allowlist secret
    }
    assert "Reset your password here" in data["content"]["rendered"]


def test_a_setting_option_whose_type_is_password_is_untouched(http, transport_factory) -> None:
    """WooCommerce describes a setting's own input type; it is not a credential field."""
    body = {"id": "woocommerce_registration_generate_password", "type": "password", "value": "yes"}
    http.queue(json_response(body))
    response = _run(
        "wc_get_setting_option",
        {"group_id": "account", "id": "woocommerce_registration_generate_password"},
        transport_factory,
        **WOO,
    )

    assert response["result"]["data"] == body


def test_an_operation_outside_the_policy_is_not_touched() -> None:
    row = operation("wc_get_order")
    body = {
        "id": 5,
        "password": "not a documented order property",  # pragma: allowlist secret
    }
    assert sanitized_response_body(row, body) == body


@pytest.mark.parametrize("operation_id", sorted(PRODUCT_POST_PASSWORD_RESPONSE_OPERATIONS))
def test_product_operations_remove_woocommerce_post_password(
    operation_id: str,
) -> None:
    """WooCommerce 11 may emit an undocumented post_password credential field."""
    row = operation(operation_id)
    record = {
        "id": 1207,
        "post_password": "must-never-leave-the-extension",  # pragma: allowlist secret
        "name": "Audit vinyl",
        "meta_data": [
            {
                "key": "post_password",
                "value": "ordinary plugin metadata remains untouched",
            }
        ],
    }
    if row.shape == "list":
        body: Any = [record]
        sanitized = sanitized_response_body(row, body)
        assert POST_PASSWORD_FIELD not in sanitized[0]
        assert sanitized[0]["meta_data"] == record["meta_data"]
    elif row.shape == "batch":
        body = {"create": [record], "update": [record]}
        sanitized = sanitized_response_body(row, body)
        assert POST_PASSWORD_FIELD not in sanitized["create"][0]
        assert POST_PASSWORD_FIELD not in sanitized["update"][0]
        assert sanitized["create"][0]["meta_data"] == record["meta_data"]
    else:
        sanitized = sanitized_response_body(row, record)
        assert POST_PASSWORD_FIELD not in sanitized
        assert sanitized["meta_data"] == record["meta_data"]


@pytest.mark.parametrize("state", ["approved", "hold", "spam", "trash"])
def test_comment_moderation_states_survive_the_destructive_policy(
    state: str, http, transport_factory
) -> None:
    """Moderating a comment is the approved way to reach `spam` and `trash`.

    The destructive-value policy strips `trash` from write enumerations so that
    a workflow cannot bin a post or a product by setting its status. Comment
    moderation is the deliberate exception: marking a comment as spam, or
    trashing one, is what moderation *is*, and blocking it would remove the
    capability rather than protect anything.
    """
    http.queue(json_response({"id": 9, "status": state}))
    response = _run("wp_update_comment", {"id": 9, "status": state}, transport_factory)

    assert response["ok"] is True
    assert json.loads(http.last["body"]) == {"status": state}
    assert response["result"]["data"]["status"] == state


@pytest.mark.parametrize(
    "operation_id",
    [
        # A revision and an autosave share a resource with the post, but their
        # own documented record has no password property.
        "wp_get_post_revision",
        "wp_list_post_revisions",
        "wp_get_post_autosave",
        "wp_get_page_revision",
        "wp_get_block_revision",
        # A customer's downloads listing shares a page with the customer record
        # and returns download entries, not customers.
        "wc_list_customer_downloads",
    ],
)
def test_an_operation_without_a_documented_password_returns_the_body_untouched(
    operation_id: str,
) -> None:
    """Negative control for the redaction.

    Deleting a key the contract never declared is data loss, not safety: a
    plugin is free to put its own `password` on a revision, and this extension
    has no business removing it.
    """
    row = operation(operation_id)
    record = {
        "id": 1,
        "password": "a third party's own field",  # pragma: allowlist secret
        "title": "kept",
    }
    body = [record] if row.shape == "list" else record

    assert sanitized_response_body(row, body) == body


def test_the_redaction_list_matches_the_committed_reference() -> None:
    """The policy names exactly the operations whose record documents a password.

    Derived from the snapshot rather than restated, so an operation added later
    cannot quietly fall in or out of the list.
    """
    import yaml
    from build_parameters import RESPONSE_TABLE_BY_OPERATION, _slug

    snapshot = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "contracts" / "rest_reference.yaml").read_text(
            encoding="utf-8"
        )
    )
    pages = {(page["provider"], page["slug"]): page for page in snapshot["pages"]}
    documented: set[str] = set()
    for row in REST_OPERATIONS:
        page = pages[(row.provider, row.doc_slug)]
        if row.provider == "wordpress":
            names = {entry.get("name") for entry in page.get("schema") or []}
        else:
            tables = page.get("properties") or []
            wanted = RESPONSE_TABLE_BY_OPERATION.get(row.operation_id, "")
            primary = tables[0]["fields"] if tables else []
            for table in tables:
                if wanted and _slug(table["heading"]) == wanted:
                    primary = table["fields"]
                    break
            names = {entry.get("name") for entry in primary}
        if PASSWORD_FIELD in names:
            documented.add(row.operation_id)

    assert documented == PASSWORD_RESPONSE_OPERATIONS


@pytest.mark.parametrize(
    "line_items",
    [
        [{}],
        [{"line_item_id": 5}],
        [{"quantity": 1}],
        [{"line_item_id": 5, "quantity": 1}, {"line_item_id": 6}],
    ],
)
def test_an_incomplete_preview_line_is_refused_before_any_request(
    line_items: list[dict[str, Any]], http, transport_factory
) -> None:
    """A required member of a documented entry is required in the entry.

    Publishing `properties` without `required` let `line_items: [{}]` through to
    WooCommerce, which is a round trip to learn something the contract already
    knew.
    """
    response = _run(
        "wc_preview_order_refund", {"id": 1, "line_items": line_items}, transport_factory, **WOO
    )

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_a_complete_preview_line_is_accepted(http, transport_factory) -> None:
    http.queue(json_response({"subtotal": "10.00", "tax": "2.00", "total": "12.00"}))
    response = _run(
        "wc_preview_order_refund",
        {"id": 1, "line_items": [{"line_item_id": 5, "quantity": 1}]},
        transport_factory,
        **WOO,
    )

    assert response["ok"] is True
    assert json.loads(http.last["body"]) == {"line_items": [{"line_item_id": 5, "quantity": 1}]}


def test_the_published_schema_states_the_nested_required_members() -> None:
    """What the runtime enforces has to be visible in the contract as well."""
    import yaml

    manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "contracts" / "operation_manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    operations = {row["operation_id"]: row for row in manifest["operations"]}
    line_items = next(
        row
        for row in operations["wc_preview_order_refund"]["inputs"]
        if row["name"] == "line_items"
    )
    items = line_items["schema"]["items"]
    assert items["required"] == ["line_item_id", "quantity"]
    assert "refund_total" in items["properties"]
    assert "refund_total" not in items["required"]
