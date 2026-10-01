"""Coverage inventory: what this extension supports, and what it deliberately does not.

Supported rows are derived from :mod:`runtime.catalog` so the published
inventory can never drift from the closed runtime registry. Excluded rows are
declared here because a route that is never dispatched has no registry entry to
derive from, and the reason it is absent is exactly what an auditor needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import (
    REST_OPERATIONS,
    WOOCOMMERCE,
    WOOCOMMERCE_DOC_BASE,
    WOOCOMMERCE_NAMESPACE,
    WORDPRESS,
    WORDPRESS_DOC_BASE,
    WORDPRESS_NAMESPACE,
)

_PATH_WEBHOOKS_ID = "/webhooks/{id}"
_PATH_USERS_USER_ID_APPLICATION_PASSWORDS = "/users/{user_id}/application-passwords"
_PATH_USERS_USER_ID_APPLICATION_PASSWORDS_UUID = "/users/{user_id}/application-passwords/{uuid}"
_TOKEN_WP_SITE_HEALTH_V1 = "wp-site-health/v1"

STATUS_SUPPORTED = "supported"
STATUS_EXCLUDED = "excluded"
STATUS_NOT_DOCUMENTED = "not_documented"
COVERAGE_STATUSES: frozenset[str] = frozenset(
    {STATUS_SUPPORTED, STATUS_EXCLUDED, STATUS_NOT_DOCUMENTED}
)

REASON_DELETE = "destructive_delete_excluded"
REASON_PLUGIN_LIFECYCLE = "plugin_lifecycle_excluded"
REASON_THEME_LIFECYCLE = "theme_lifecycle_excluded"
REASON_APPLICATION_PASSWORDS = (
    "application_password_management_excluded"  # pragma: allowlist secret
)
REASON_REFUND_MUTATION = "refund_mutation_excluded"
REASON_SYSTEM_STATUS_TOOL = "system_status_tool_execution_excluded"
REASON_BATCH_DELETE = "batch_delete_payload_excluded"
REASON_OUTSIDE_WP_V2 = "namespace_outside_wp_v2"
REASON_NOT_DOCUMENTED = "not_officially_documented"
REASON_IDENTITY_LIFECYCLE = "identity_lifecycle_automation_excluded"
REASON_WEBHOOK_ADMIN = "webhook_administration_excluded"
EXCLUSION_REASONS: frozenset[str] = frozenset(
    {
        REASON_DELETE,
        REASON_PLUGIN_LIFECYCLE,
        REASON_THEME_LIFECYCLE,
        REASON_APPLICATION_PASSWORDS,
        REASON_REFUND_MUTATION,
        REASON_SYSTEM_STATUS_TOOL,
        REASON_BATCH_DELETE,
        REASON_OUTSIDE_WP_V2,
        REASON_NOT_DOCUMENTED,
        REASON_IDENTITY_LIFECYCLE,
        REASON_WEBHOOK_ADMIN,
    }
)

#: Why each exclusion exists, in language a reader can act on. Requirement:
#: an API page must never show only the internal reason code.
REASON_EXPLANATIONS: dict[str, str] = {
    REASON_DELETE: (
        "Deleting is unavailable in version 1.0.0 because this extension excludes destructive "
        "operations. Read, create and update the record instead, or delete it in the site's admin."
    ),
    REASON_PLUGIN_LIFECYCLE: (
        "Installing, updating, activating, deactivating and deleting plugins is unavailable "
        "because it changes the code the site runs. Plugins can be listed and read."
    ),
    REASON_THEME_LIFECYCLE: (
        "WordPress Core publishes no documented write endpoint for themes, and version 1.0.0 does "
        "not add one. Themes can be listed and read."
    ),
    REASON_APPLICATION_PASSWORDS: (
        "Managing Application Passwords is unavailable because this extension signs in with one. "
        "Create, rotate and revoke them yourself in WordPress under Users then Profile."
    ),
    REASON_REFUND_MUTATION: (
        "Creating, changing and deleting refunds is unavailable in version 1.0.0 because a refund "
        "moves money. Refunds can be read, and a refund can be previewed without creating it."
    ),
    REASON_SYSTEM_STATUS_TOOL: (
        "Running a system status tool is unavailable because those tools change store data. The "
        "list of tools and the status report itself can be read."
    ),
    REASON_BATCH_DELETE: (
        "A batch request can create and update records, never delete them. The delete member of "
        "the native batch payload is not accepted."
    ),
    REASON_OUTSIDE_WP_V2: (
        "This route lives outside the /wp/v2 namespace that version 1.0.0 covers."
    ),
    REASON_NOT_DOCUMENTED: (
        "WordPress Core ships this, but publishes no official REST reference page for it. "
        "Version 1.0.0 does not guess at an undocumented contract."
    ),
    REASON_IDENTITY_LIFECYCLE: (
        "Creating or changing a WordPress user account is account administration rather than "
        "content automation, and a mistake in a workflow can lock somebody out of the site or "
        "hand them more access than intended. Users can be read; create and change them in the "
        "site's admin."
    ),
    REASON_WEBHOOK_ADMIN: (
        "A WooCommerce webhook decides where the store sends its data, so this extension does "
        "not create or change one on your behalf. Add a webhook trigger to a workflow, then "
        "paste the address it gives you into WooCommerce yourself; the Setup Guide walks "
        "through it."
    ),
}

WORDPRESS_REFERENCE_INDEX = "https://developer.wordpress.org/rest-api/reference/"
WOOCOMMERCE_REFERENCE_INDEX = "https://developer.woocommerce.com/docs/apis/rest-api/v3/"


@dataclass(frozen=True)
class CoverageRow:
    """One published coverage-inventory row."""

    provider: str
    resource: str
    namespace: str
    route_pattern: str
    method: str
    operation_id: str
    documentation_url: str
    coverage_status: str
    exclusion_reason: str = ""

    def as_mapping(self) -> dict[str, str]:
        row = {
            "provider": self.provider,
            "resource": self.resource,
            "namespace": self.namespace,
            "route_pattern": self.route_pattern,
            "method": self.method,
            "operation_id": self.operation_id,
            "documentation_url": self.documentation_url,
            "coverage_status": self.coverage_status,
        }
        if self.exclusion_reason:
            row["exclusion_reason"] = self.exclusion_reason
        return row


def _wp_excluded(resource: str, route: str, method: str, doc_slug: str, reason: str) -> CoverageRow:
    return CoverageRow(
        provider=WORDPRESS,
        resource=resource,
        namespace=WORDPRESS_NAMESPACE,
        route_pattern=f"/wp-json/{WORDPRESS_NAMESPACE}{route}",
        method=method,
        operation_id="",
        documentation_url=f"{WORDPRESS_DOC_BASE}{doc_slug}/",
        coverage_status=STATUS_EXCLUDED,
        exclusion_reason=reason,
    )


def _wc_excluded(resource: str, route: str, method: str, doc_slug: str, reason: str) -> CoverageRow:
    return CoverageRow(
        provider=WOOCOMMERCE,
        resource=resource,
        namespace=WOOCOMMERCE_NAMESPACE,
        route_pattern=f"/wp-json/{WOOCOMMERCE_NAMESPACE}{route}",
        method=method,
        operation_id="",
        documentation_url=f"{WOOCOMMERCE_DOC_BASE}{doc_slug}/",
        coverage_status=STATUS_EXCLUDED,
        exclusion_reason=reason,
    )


def _wp_undocumented(resource: str) -> CoverageRow:
    return CoverageRow(
        provider=WORDPRESS,
        resource=resource,
        namespace=WORDPRESS_NAMESPACE,
        route_pattern="",
        method="",
        operation_id="",
        documentation_url=WORDPRESS_REFERENCE_INDEX,
        coverage_status=STATUS_NOT_DOCUMENTED,
        exclusion_reason=REASON_NOT_DOCUMENTED,
    )


EXCLUDED_ROWS: tuple[CoverageRow, ...] = (
    # Creating or changing a user account is administration, not automation.
    _wp_excluded("users", "/users", "POST", "users", REASON_IDENTITY_LIFECYCLE),
    _wp_excluded("users", "/users/{id}", "POST", "users", REASON_IDENTITY_LIFECYCLE),
    _wp_excluded("users", "/users/me", "POST", "users", REASON_IDENTITY_LIFECYCLE),
    # Where the store sends its data is configured by hand, in WooCommerce.
    _wc_excluded("webhooks", "/webhooks", "GET", "webhooks", REASON_WEBHOOK_ADMIN),
    _wc_excluded("webhooks", "/webhooks", "POST", "webhooks", REASON_WEBHOOK_ADMIN),
    _wc_excluded("webhooks", _PATH_WEBHOOKS_ID, "GET", "webhooks", REASON_WEBHOOK_ADMIN),
    _wc_excluded("webhooks", _PATH_WEBHOOKS_ID, "PUT", "webhooks", REASON_WEBHOOK_ADMIN),
    _wc_excluded("webhooks", "/webhooks/batch", "POST", "webhooks", REASON_WEBHOOK_ADMIN),
    # Every documented WordPress DELETE.
    _wp_excluded("posts", "/posts/{id}", "DELETE", "posts", REASON_DELETE),
    _wp_excluded(
        "post_revisions",
        "/posts/{parent}/revisions/{id}",
        "DELETE",
        "post-revisions",
        REASON_DELETE,
    ),
    _wp_excluded("pages", "/pages/{id}", "DELETE", "pages", REASON_DELETE),
    _wp_excluded(
        "page_revisions",
        "/pages/{parent}/revisions/{id}",
        "DELETE",
        "page-revisions",
        REASON_DELETE,
    ),
    _wp_excluded("media", "/media/{id}", "DELETE", "media", REASON_DELETE),
    _wp_excluded("comments", "/comments/{id}", "DELETE", "comments", REASON_DELETE),
    _wp_excluded("categories", "/categories/{id}", "DELETE", "categories", REASON_DELETE),
    _wp_excluded("tags", "/tags/{id}", "DELETE", "tags", REASON_DELETE),
    _wp_excluded("users", "/users/{id}", "DELETE", "users", REASON_DELETE),
    _wp_excluded("users", "/users/me", "DELETE", "users", REASON_DELETE),
    _wp_excluded("blocks", "/blocks/{id}", "DELETE", "blocks", REASON_DELETE),
    _wp_excluded(
        "block_revisions",
        "/blocks/{parent}/revisions/{id}",
        "DELETE",
        "block-revisions",
        REASON_DELETE,
    ),
    _wp_excluded("widgets", "/widgets/{id}", "DELETE", "widgets", REASON_DELETE),
    # WordPress plugin lifecycle.
    _wp_excluded("plugins", "/plugins", "POST", "plugins", REASON_PLUGIN_LIFECYCLE),
    _wp_excluded("plugins", "/plugins/{plugin}", "POST", "plugins", REASON_PLUGIN_LIFECYCLE),
    _wp_excluded("plugins", "/plugins/{plugin}", "DELETE", "plugins", REASON_PLUGIN_LIFECYCLE),
    # WordPress theme lifecycle. Core ships no documented write route for themes,
    # and this extension adds none, so the resource stays read-only by contract.
    CoverageRow(
        provider=WORDPRESS,
        resource="themes",
        namespace=WORDPRESS_NAMESPACE,
        route_pattern="",
        method="",
        operation_id="",
        documentation_url=f"{WORDPRESS_DOC_BASE}themes/",
        coverage_status=STATUS_NOT_DOCUMENTED,
        exclusion_reason=REASON_THEME_LIFECYCLE,
    ),
    # WordPress Application Passwords: every documented operation is management
    # of the credential this extension authenticates with, so all are excluded.
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS,
        "GET",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS,
        "POST",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS,
        "DELETE",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        "/users/{user_id}/application-passwords/introspect",
        "GET",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS_UUID,
        "GET",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS_UUID,
        "POST",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    _wp_excluded(
        "application_passwords",
        _PATH_USERS_USER_ID_APPLICATION_PASSWORDS_UUID,
        "DELETE",
        "application-passwords",
        REASON_APPLICATION_PASSWORDS,
    ),
    # Site health is documented, but ships under /wp-site-health/v1.
    CoverageRow(
        WORDPRESS,
        "site_health",
        _TOKEN_WP_SITE_HEALTH_V1,
        "/wp-json/wp-site-health/v1/tests/background-updates",
        "GET",
        "",
        f"{WORDPRESS_DOC_BASE}wp-site-health-tests/",
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    CoverageRow(
        WORDPRESS,
        "site_health",
        _TOKEN_WP_SITE_HEALTH_V1,
        "/wp-json/wp-site-health/v1/tests/loopback-requests",
        "GET",
        "",
        f"{WORDPRESS_DOC_BASE}wp-site-health-tests/",
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    CoverageRow(
        WORDPRESS,
        "site_health",
        _TOKEN_WP_SITE_HEALTH_V1,
        "/wp-json/wp-site-health/v1/tests/https-status",
        "GET",
        "",
        f"{WORDPRESS_DOC_BASE}wp-site-health-tests/",
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    CoverageRow(
        WORDPRESS,
        "site_health",
        _TOKEN_WP_SITE_HEALTH_V1,
        "/wp-json/wp-site-health/v1/tests/dotorg-communication",
        "GET",
        "",
        f"{WORDPRESS_DOC_BASE}wp-site-health-tests/",
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    CoverageRow(
        WORDPRESS,
        "site_health",
        _TOKEN_WP_SITE_HEALTH_V1,
        "/wp-json/wp-site-health/v1/tests/authorization-header",
        "GET",
        "",
        f"{WORDPRESS_DOC_BASE}wp-site-health-tests/",
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    # WordPress Core's batch controller ships under /batch/v1, outside /wp/v2.
    CoverageRow(
        WORDPRESS,
        "batch",
        "batch/v1",
        "/wp-json/batch/v1",
        "POST",
        "",
        WORDPRESS_REFERENCE_INDEX,
        STATUS_EXCLUDED,
        REASON_OUTSIDE_WP_V2,
    ),
    # Resources named in the task scope that WordPress Core does not publish in
    # its official REST API reference. No route is dispatched for them.
    _wp_undocumented("global_styles"),
    _wp_undocumented("global_styles_revisions"),
    _wp_undocumented("navigation"),
    _wp_undocumented("navigation_revisions"),
    _wp_undocumented("menus"),
    _wp_undocumented("menu_items"),
    _wp_undocumented("templates"),
    _wp_undocumented("template_revisions"),
    _wp_undocumented("template_parts"),
    _wp_undocumented("template_part_revisions"),
    # Every documented WooCommerce DELETE.
    _wc_excluded("coupons", "/coupons/{id}", "DELETE", "coupons", REASON_DELETE),
    _wc_excluded("customers", "/customers/{id}", "DELETE", "customers", REASON_DELETE),
    _wc_excluded("orders", "/orders/{id}", "DELETE", "orders", REASON_DELETE),
    _wc_excluded(
        "order_notes", "/orders/{id}/notes/{note_id}", "DELETE", "order-notes", REASON_DELETE
    ),
    _wc_excluded("products", "/products/{id}", "DELETE", "products", REASON_DELETE),
    _wc_excluded(
        "product_variations",
        "/products/{product_id}/variations/{id}",
        "DELETE",
        "product-variations",
        REASON_DELETE,
    ),
    _wc_excluded(
        "product_attributes",
        "/products/attributes/{id}",
        "DELETE",
        "product-attributes",
        REASON_DELETE,
    ),
    _wc_excluded(
        "product_attribute_terms",
        "/products/attributes/{attribute_id}/terms/{id}",
        "DELETE",
        "product-attribute-terms",
        REASON_DELETE,
    ),
    _wc_excluded(
        "product_categories",
        "/products/categories/{id}",
        "DELETE",
        "product-categories",
        REASON_DELETE,
    ),
    _wc_excluded(
        "product_shipping_classes",
        "/products/shipping_classes/{id}",
        "DELETE",
        "product-shipping-classes",
        REASON_DELETE,
    ),
    _wc_excluded("product_tags", "/products/tags/{id}", "DELETE", "product-tags", REASON_DELETE),
    _wc_excluded(
        "product_reviews", "/products/reviews/{id}", "DELETE", "product-reviews", REASON_DELETE
    ),
    _wc_excluded("taxes", "/taxes/{id}", "DELETE", "taxes", REASON_DELETE),
    _wc_excluded("tax_classes", "/taxes/classes/{slug}", "DELETE", "tax-classes", REASON_DELETE),
    _wc_excluded("webhooks", _PATH_WEBHOOKS_ID, "DELETE", "webhooks", REASON_DELETE),
    _wc_excluded(
        "shipping_zones", "/shipping/zones/{id}", "DELETE", "shipping-zones", REASON_DELETE
    ),
    _wc_excluded(
        "shipping_zone_methods",
        "/shipping/zones/{zone_id}/methods/{id}",
        "DELETE",
        "shipping-zone-methods",
        REASON_DELETE,
    ),
    # WooCommerce refund creation, update, and deletion stay excluded. The
    # documented preview endpoint computes a refund without creating one and
    # is supported as a read.
    _wc_excluded(
        "order_refunds", "/orders/{id}/refunds", "POST", "order-refunds", REASON_REFUND_MUTATION
    ),
    _wc_excluded(
        "order_refunds",
        "/orders/{id}/refunds/{refund_id}",
        "DELETE",
        "order-refunds",
        REASON_REFUND_MUTATION,
    ),
    # WooCommerce system-status tool execution.
    _wc_excluded(
        "system_status_tools",
        "/system_status/tools/{id}",
        "PUT",
        "system-status-tools",
        REASON_SYSTEM_STATUS_TOOL,
    ),
    # The delete member of every documented WooCommerce batch payload.
    CoverageRow(
        provider=WOOCOMMERCE,
        resource="batch_payloads",
        namespace=WOOCOMMERCE_NAMESPACE,
        route_pattern=f"/wp-json/{WOOCOMMERCE_NAMESPACE}/<resource>/batch#delete",
        method="POST",
        operation_id="",
        documentation_url=f"{WOOCOMMERCE_DOC_BASE}api-reference/",
        coverage_status=STATUS_EXCLUDED,
        exclusion_reason=REASON_BATCH_DELETE,
    ),
)


def supported_rows() -> tuple[CoverageRow, ...]:
    """Coverage rows derived from the closed runtime registry."""
    return tuple(
        CoverageRow(
            provider=row.provider,
            resource=row.resource,
            namespace=row.namespace,
            route_pattern=row.route_pattern,
            method=row.method,
            operation_id=row.operation_id,
            documentation_url=row.doc_url,
            coverage_status=STATUS_SUPPORTED,
        )
        for row in REST_OPERATIONS
    )


def coverage_rows() -> tuple[CoverageRow, ...]:
    """The full published coverage inventory, supported rows first."""
    return supported_rows() + EXCLUDED_ROWS


def explain(reason: str) -> str:
    """Human-readable explanation for one exclusion reason."""
    return REASON_EXPLANATIONS.get(reason, "")


__all__ = [
    "COVERAGE_STATUSES",
    "EXCLUDED_ROWS",
    "EXCLUSION_REASONS",
    "REASON_EXPLANATIONS",
    "STATUS_EXCLUDED",
    "STATUS_NOT_DOCUMENTED",
    "STATUS_SUPPORTED",
    "CoverageRow",
    "coverage_rows",
    "explain",
    "supported_rows",
]
