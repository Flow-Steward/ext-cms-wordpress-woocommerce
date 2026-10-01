"""``contracts/rest_coverage.yaml`` is the exact coverage source of truth."""

from __future__ import annotations

from pathlib import Path

import yaml
from runtime.catalog import REST_OPERATIONS_BY_ID
from runtime.coverage import (
    COVERAGE_STATUSES,
    EXCLUSION_REASONS,
    STATUS_EXCLUDED,
    STATUS_NOT_DOCUMENTED,
    STATUS_SUPPORTED,
    coverage_rows,
)

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
ROW_KEYS = {
    "provider",
    "resource",
    "namespace",
    "route_pattern",
    "method",
    "operation_id",
    "documentation_url",
    "coverage_status",
}


def _coverage() -> list[dict]:
    return yaml.safe_load((BUNDLE_ROOT / "contracts/rest_coverage.yaml").read_text())["coverage"]


def test_published_inventory_equals_the_declared_inventory() -> None:
    assert _coverage() == [row.as_mapping() for row in coverage_rows()]


def test_every_row_carries_the_required_columns() -> None:
    for row in _coverage():
        assert set(row) >= ROW_KEYS
        assert set(row) - ROW_KEYS <= {"exclusion_reason"}
        assert row["provider"] in {"wordpress", "woocommerce"}
        assert row["resource"]
        assert row["namespace"]
        assert row["coverage_status"] in COVERAGE_STATUSES
        assert row["documentation_url"].startswith("https://")


def test_supported_rows_name_a_registered_operation_and_a_real_route() -> None:
    for row in _coverage():
        if row["coverage_status"] != STATUS_SUPPORTED:
            continue
        operation = REST_OPERATIONS_BY_ID[row["operation_id"]]
        assert row["route_pattern"] == operation.route_pattern
        assert row["method"] == operation.method
        assert row["namespace"] == operation.namespace
        assert row["documentation_url"] == operation.doc_url
        assert "exclusion_reason" not in row


def test_excluded_rows_always_state_a_reason_and_never_name_an_operation() -> None:
    for row in _coverage():
        if row["coverage_status"] == STATUS_SUPPORTED:
            continue
        assert row["coverage_status"] in {STATUS_EXCLUDED, STATUS_NOT_DOCUMENTED}
        assert row["operation_id"] == ""
        assert row["exclusion_reason"] in EXCLUSION_REASONS


def test_no_route_appears_twice_in_the_inventory() -> None:
    seen = [
        (row["provider"], row["namespace"], row["route_pattern"], row["method"], row["resource"])
        for row in _coverage()
    ]
    duplicates = sorted({key for key in seen if seen.count(key) > 1})
    assert duplicates == []


def test_the_refund_preview_is_supported_as_a_read() -> None:
    """It computes a refund without creating one, so it is not a mutation."""
    row = next(
        entry
        for entry in _coverage()
        if entry["route_pattern"] == "/wp-json/wc/v3/orders/{id}/refunds/preview"
    )
    assert row["coverage_status"] == "supported"
    assert row["operation_id"] == "wc_preview_order_refund"
    assert REST_OPERATIONS_BY_ID["wc_preview_order_refund"].has_external_effect is False


def test_refund_creation_update_and_deletion_stay_excluded() -> None:
    reasons = {
        (row["method"], row["route_pattern"]): row.get("exclusion_reason") for row in _coverage()
    }
    assert reasons[("POST", "/wp-json/wc/v3/orders/{id}/refunds")] == "refund_mutation_excluded"
    assert (
        reasons[("DELETE", "/wp-json/wc/v3/orders/{id}/refunds/{refund_id}")]
        == "refund_mutation_excluded"
    )


def test_no_supported_row_is_destructive_or_outside_the_two_namespaces() -> None:
    supported = [row for row in _coverage() if row["coverage_status"] == STATUS_SUPPORTED]
    assert supported
    for row in supported:
        assert row["method"] in {"GET", "POST", "PUT"}
        assert row["method"] != "DELETE"
        assert row["namespace"] in {"wp/v2", "wc/v3"}


def test_every_documented_delete_is_present_and_excluded() -> None:
    deletes = [row for row in _coverage() if row["method"] == "DELETE"]
    assert len(deletes) >= 30
    for row in deletes:
        assert row["coverage_status"] == STATUS_EXCLUDED
        assert row["exclusion_reason"] in {
            "destructive_delete_excluded",
            "plugin_lifecycle_excluded",
            "application_password_management_excluded",
            "refund_mutation_excluded",
        }


def test_scoped_but_undocumented_wordpress_resources_are_declared_not_documented() -> None:
    rows = {
        row["resource"]: row
        for row in _coverage()
        if row["coverage_status"] == STATUS_NOT_DOCUMENTED
    }
    for resource in (
        "global_styles",
        "global_styles_revisions",
        "navigation",
        "navigation_revisions",
        "menus",
        "menu_items",
        "templates",
        "template_revisions",
        "template_parts",
        "template_part_revisions",
    ):
        assert rows[resource]["exclusion_reason"] == "not_officially_documented"
        assert rows[resource]["route_pattern"] == ""


def test_lifecycle_and_execution_surfaces_are_excluded_by_name() -> None:
    reasons = {
        (row["method"], row["route_pattern"]): row.get("exclusion_reason") for row in _coverage()
    }
    assert reasons[("POST", "/wp-json/wp/v2/plugins")] == "plugin_lifecycle_excluded"
    assert reasons[("POST", "/wp-json/wp/v2/plugins/{plugin}")] == "plugin_lifecycle_excluded"
    assert reasons[("DELETE", "/wp-json/wp/v2/plugins/{plugin}")] == "plugin_lifecycle_excluded"
    assert (
        reasons[("PUT", "/wp-json/wc/v3/system_status/tools/{id}")]
        == "system_status_tool_execution_excluded"
    )
    assert reasons[("POST", "/wp-json/wc/v3/orders/{id}/refunds")] == "refund_mutation_excluded"
    assert (
        reasons[("POST", "/wp-json/wc/v3/<resource>/batch#delete")]
        == "batch_delete_payload_excluded"
    )
    assert (
        reasons[("POST", "/wp-json/wp/v2/users/{user_id}/application-passwords")]
        == "application_password_management_excluded"
    )


def test_scoped_wordpress_resources_all_appear_in_the_inventory() -> None:
    resources = {row["resource"] for row in _coverage() if row["provider"] == "wordpress"}
    for resource in (
        "posts",
        "post_revisions",
        "pages",
        "page_revisions",
        "media",
        "comments",
        "categories",
        "tags",
        "taxonomies",
        "users",
        "post_types",
        "post_statuses",
        "settings",
        "themes",
        "search",
        "block_types",
        "blocks",
        "block_revisions",
        "block_directory_items",
        "block_patterns",
        "block_pattern_categories",
        "rendered_blocks",
        "menu_locations",
        "sidebars",
        "widget_types",
        "widgets",
        "plugins",
        "site_health",
    ):
        assert resource in resources, resource


def test_scoped_woocommerce_resources_all_appear_in_the_inventory() -> None:
    resources = {row["resource"] for row in _coverage() if row["provider"] == "woocommerce"}
    for resource in (
        "coupons",
        "customers",
        "orders",
        "order_actions",
        "order_notes",
        "order_refunds",
        "refunds",
        "products",
        "product_variations",
        "product_attributes",
        "product_attribute_terms",
        "product_categories",
        "product_custom_fields",
        "product_shipping_classes",
        "product_tags",
        "product_reviews",
        "reports",
        "taxes",
        "tax_classes",
        "webhooks",
        "settings",
        "setting_options",
        "payment_gateways",
        "shipping_zones",
        "shipping_zone_locations",
        "shipping_zone_methods",
        "shipping_methods",
        "system_status",
        "system_status_tools",
        "data",
    ):
        assert resource in resources, resource
