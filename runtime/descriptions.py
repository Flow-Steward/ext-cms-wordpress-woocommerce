"""Plain-language documentation for every declared operation.

This is the single source of the human-facing text. The workflow-builder action
descriptions, the operation manifest descriptions, and the WordPress API and
WooCommerce API pages are all rendered from here, so they cannot drift apart.

Each block is built from the operation's own declared shape and its typed
parameter tables, which keeps the prose truthful: the fields named as required
really are the documented required fields, and the filters named really are the
documented filters.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import REST_OPERATIONS, Operation
from .parameters import BODY_FIELDS, QUERY_FIELDS, RESPONSE_FIELDS

_MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE = (
    "This returns the whole set in one response and does not page."
)
_MESSAGE_THE_CREATED_AUTOSAVE_INCLUDING_THE_ID_WORDPRESS_ASSIGNED_TO_IT = (
    "The created autosave, including the ID WordPress assigned to it."
)
_MESSAGE_THE_AUTOSAVE_INCLUDING_ITS_AUTHOR_DATE_TITLE_AND_CONTENT = (
    "The autosave, including its author, date, title and content."
)
_MESSAGE_NOTHING_BEYOND_THE_CONNECTION = "Nothing beyond the connection."
_MESSAGE_THIS_IS_WOOCOMMERCE_S_BUILT_IN_REFERENCE_DATA_NOT_YOUR_STORE_S_SETT = "This is WooCommerce's built-in reference data, not your store's settings, and it returns the whole set in one response."

INITIAL_VERSION = "1.0.0"

#: Plain nouns for each resource: (singular, plural).
RESOURCE_NOUNS: dict[str, tuple[str, str]] = {
    # WordPress
    "posts": ("post", "posts"),
    "post_revisions": ("post revision", "post revisions"),
    "pages": ("page", "pages"),
    "page_revisions": ("page revision", "page revisions"),
    "media": ("media item", "media items"),
    "comments": ("comment", "comments"),
    "categories": ("category", "categories"),
    "tags": ("tag", "tags"),
    "taxonomies": ("taxonomy", "taxonomies"),
    "users": ("user", "users"),
    "post_types": ("post type", "post types"),
    "post_statuses": ("post status", "post statuses"),
    "settings": ("site setting", "site settings"),
    "themes": ("theme", "themes"),
    "search": ("search result", "search results"),
    "block_types": ("block type", "block types"),
    "blocks": ("reusable block", "reusable blocks"),
    "block_revisions": ("block revision", "block revisions"),
    "block_directory_items": ("block directory item", "block directory items"),
    "block_patterns": ("block pattern", "block patterns"),
    "block_pattern_categories": ("block pattern category", "block pattern categories"),
    "pattern_directory_items": ("pattern directory item", "pattern directory items"),
    "rendered_blocks": ("rendered block", "rendered blocks"),
    "menu_locations": ("menu location", "menu locations"),
    "sidebars": ("sidebar", "sidebars"),
    "widget_types": ("widget type", "widget types"),
    "widgets": ("widget", "widgets"),
    "plugins": ("plugin", "plugins"),
    # WooCommerce
    "coupons": ("coupon", "coupons"),
    "customers": ("customer", "customers"),
    "orders": ("order", "orders"),
    "order_actions": ("order action", "order actions"),
    "order_notes": ("order note", "order notes"),
    "order_refunds": ("refund", "refunds"),
    "refunds": ("refund", "refunds"),
    "products": ("product", "products"),
    "product_variations": ("product variation", "product variations"),
    "product_attributes": ("product attribute", "product attributes"),
    "product_attribute_terms": ("attribute term", "attribute terms"),
    "product_categories": ("product category", "product categories"),
    "product_custom_fields": ("custom field name", "custom field names"),
    "product_shipping_classes": ("shipping class", "shipping classes"),
    "product_tags": ("product tag", "product tags"),
    "product_reviews": ("product review", "product reviews"),
    "reports": ("report", "reports"),
    "taxes": ("tax rate", "tax rates"),
    "tax_classes": ("tax class", "tax classes"),
    "webhooks": ("webhook", "webhooks"),
    "setting_options": ("setting", "settings"),
    "payment_gateways": ("payment gateway", "payment gateways"),
    "shipping_zones": ("shipping zone", "shipping zones"),
    "shipping_zone_locations": ("shipping zone location", "shipping zone locations"),
    "shipping_zone_methods": ("shipping zone method", "shipping zone methods"),
    "shipping_methods": ("shipping method", "shipping methods"),
    "system_status": ("system status report", "system status reports"),
    "system_status_tools": ("system status tool", "system status tools"),
    "data": ("store data record", "store data records"),
}

#: Resources this version can only read.
READ_ONLY_RESOURCES: frozenset[str] = frozenset(
    {
        "themes",
        "plugins",
        "system_status",
        "system_status_tools",
        "taxonomies",
        "post_types",
        "post_statuses",
        "block_types",
        "block_patterns",
        "block_pattern_categories",
        "block_directory_items",
        "pattern_directory_items",
        "menu_locations",
        "widget_types",
        "shipping_methods",
        "payment_gateways",
        "data",
        "reports",
        "refunds",
        "product_custom_fields",
    }
)

#: How the API pages group resources for a reader.
RESOURCE_GROUPS: dict[str, list[tuple[str, list[str]]]] = {
    "wordpress": [
        ("Content", ["posts", "post_revisions", "pages", "page_revisions", "media", "comments"]),
        ("Categories and tags", ["categories", "tags", "taxonomies"]),
        ("Users", ["users"]),
        (
            "Site settings and information",
            ["settings", "post_types", "post_statuses", "themes", "plugins", "search"],
        ),
        (
            "Blocks and patterns",
            [
                "block_types",
                "blocks",
                "block_revisions",
                "block_directory_items",
                "block_patterns",
                "block_pattern_categories",
                "pattern_directory_items",
                "rendered_blocks",
            ],
        ),
        ("Menus, sidebars and widgets", ["menu_locations", "sidebars", "widget_types", "widgets"]),
    ],
    "woocommerce": [
        (
            "Products",
            [
                "products",
                "product_variations",
                "product_attributes",
                "product_attribute_terms",
                "product_categories",
                "product_tags",
                "product_shipping_classes",
                "product_custom_fields",
                "product_reviews",
            ],
        ),
        ("Orders", ["orders", "order_notes", "order_actions", "order_refunds", "refunds"]),
        ("Customers", ["customers"]),
        ("Coupons", ["coupons"]),
        ("Taxes", ["taxes", "tax_classes"]),
        (
            "Shipping",
            [
                "shipping_zones",
                "shipping_zone_locations",
                "shipping_zone_methods",
                "shipping_methods",
            ],
        ),
        ("Store configuration", ["settings", "setting_options", "payment_gateways", "webhooks"]),
        ("Reports and store data", ["reports", "system_status", "system_status_tools", "data"]),
    ],
}

#: Section headings for each resource inside its group.
RESOURCE_HEADINGS: dict[str, str] = {
    "post_revisions": "Post revisions and autosaves",
    "page_revisions": "Page revisions and autosaves",
    "block_revisions": "Block revisions and autosaves",
    "order_refunds": "Order refunds",
    "refunds": "All refunds",
    "product_custom_fields": "Product custom field names",
    "setting_options": "Individual settings",
    "settings": "Setting groups",
    "system_status_tools": "System status tools",
    "data": "Store data",
    "search": "Search",
}

_FILTER_NOISE = frozenset({"context", "page", "per_page", "offset", "order", "orderby", "_fields"})
_OPTIONAL_NOISE_PREFIXES = ("date_", "_")
_OPTIONAL_NOISE = frozenset({"meta", "meta_data", "id", "slug"})


@dataclass(frozen=True)
class OperationDoc:
    """One operation, explained for somebody who is not reading the REST spec."""

    operation_id: str
    title: str
    summary: str
    endpoint: str
    provides: str
    returns: str
    important: str
    introduced_in: str
    documentation_url: str


#: The ``endpoint`` of an operation that never contacts the site.
NO_REQUEST = "(no request)"


def catalog_description(doc: OperationDoc) -> str:
    """The one line the workflow builder shows under an operation's title.

    The builder's catalog projects only a title and a description, so the
    endpoint has nowhere else to appear — and without it an author cannot tell
    which of two similar operations calls which route.
    """
    if doc.endpoint == NO_REQUEST:
        return doc.summary
    return f"{doc.summary} Calls {doc.endpoint}."


#: Words whose article does not follow the first letter.
_ARTICLE_EXCEPTIONS = {"user": "a", "unit": "a", "hour": "an"}


def _article(word: str) -> str:
    """English article for a noun phrase, by sound rather than spelling."""
    head = word.split()[0].lower() if word.split() else word.lower()
    if head in _ARTICLE_EXCEPTIONS:
        return _ARTICLE_EXCEPTIONS[head]
    return "an" if head[:1] in "aeiou" else "a"


def _nouns(row: Operation) -> tuple[str, str]:
    return RESOURCE_NOUNS.get(
        row.resource, (row.resource.replace("_", " "), row.resource.replace("_", " "))
    )


#: Field names that read badly when simply de-underscored in prose.
_FIELD_LABELS = {
    "id": "ID",
    "sku": "SKU",
    "guid": "GUID",
    "url": "URL",
    "uri": "URI",
    "plugin_uri": "plugin URL",
    "author_uri": "author URL",
    "date_gmt": "GMT date",
    "date_created_gmt": "GMT creation date",
    "permalink": "public link",
}


def _field_label(name: str) -> str:
    if name in _FIELD_LABELS:
        return _FIELD_LABELS[name]
    return name.replace("_", " ")


def _join(names: list[str], *, conjunction: str = "or") -> str:
    readable = [_field_label(name) for name in names]
    if len(readable) == 1:
        return readable[0]
    return f"{', '.join(readable[:-1])} {conjunction} {readable[-1]}"


def _required_body(row: Operation) -> list[str]:
    return [f["name"] for f in BODY_FIELDS.get(row.operation_id, []) if f.get("required")]


def _optional_body(row: Operation, limit: int = 4) -> list[str]:
    names = [
        f["name"]
        for f in BODY_FIELDS.get(row.operation_id, [])
        if not f.get("required")
        and f["name"] not in _OPTIONAL_NOISE
        and not f["name"].startswith(_OPTIONAL_NOISE_PREFIXES)
    ]
    return names[:limit]


def _filters(row: Operation, limit: int = 5) -> list[str]:
    names = [
        f["name"] for f in QUERY_FIELDS.get(row.operation_id, []) if f["name"] not in _FILTER_NOISE
    ]
    return names[:limit]


def _supports_paging(row: Operation) -> bool:
    return "page" in {f["name"] for f in QUERY_FIELDS.get(row.operation_id, [])}


#: Friendly labels for the path parameters, so prose never says "the id".
_PATH_LABELS: dict[str, str] = {
    "product_id": "product ID",
    "note_id": "note ID",
    "refund_id": "refund ID",
    "attribute_id": "attribute ID",
    "zone_id": "shipping zone ID",
    "group_id": "settings group",
    "taxonomy": "taxonomy name",
    "type": "post type name",
    "status": "status name",
    "stylesheet": "theme folder name",
    "plugin": "plugin file",
    "location": "location name",
    "namespace": "block namespace",
    "name": "block name",
    "currency": "currency code",
    "uuid": "identifier",
}


_IRREGULAR_SINGULARS = {
    "categories": "category",
    "taxonomies": "taxonomy",
    "classes": "class",
    "statuses": "status",
    "shipping_classes": "shipping class",
    "attributes": "attribute",
    "types": "type",
    "settings": "setting",
    "zones": "zone",
    "methods": "method",
}


def _singularise(segment: str) -> str:
    readable = segment.replace("-", " ").replace("_", " ")
    key = segment.replace("-", "_")
    if key in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[key]
    if readable.endswith("ies"):
        return f"{readable[:-3]}y"
    if readable.endswith("ses"):
        return readable[:-2]
    if readable.endswith("s"):
        return readable[:-1]
    return readable


def _path_labels(row: Operation, singular: str) -> list[str]:
    """Name each path parameter after the collection it indexes.

    In a nested route such as ``/orders/{id}/notes/{note_id}``, ``{id}`` is the
    order, not the note, so the label has to come from the preceding path
    segment rather than from the operation's own resource.
    """
    segments = [part for part in row.route.split("/") if part]
    labels: list[str] = []
    for name, _kind in row.path_params:
        placeholder = "{" + name + "}"
        preceding = ""
        if placeholder in segments:
            index = segments.index(placeholder)
            if index > 0 and not segments[index - 1].startswith("{"):
                preceding = segments[index - 1]
        if name in _PATH_LABELS:
            labels.append(_PATH_LABELS[name])
        elif preceding:
            labels.append(f"{_singularise(preceding)} ID")
        elif name == "id":
            labels.append(f"{singular} ID")
        else:
            labels.append(name.replace("_", " "))
    return labels


def _path_phrase(row: Operation, singular: str = "") -> str:
    if not row.path_params:
        return ""
    return _join(_path_labels(row, singular or "record"), conjunction="and")


_HEADLINE_FIELDS = (
    "id",
    "name",
    "title",
    "slug",
    "status",
    "type",
    "link",
    "permalink",
    "price",
    "regular_price",
    "stock_quantity",
    "sku",
    "total",
    "currency",
    "email",
    "number",
    "date_created",
    "date",
    "author",
    "content",
    "excerpt",
    "plugin",
    "stylesheet",
    "description",
    "count",
    "parent",
)


def _returned_fields(row: Operation, limit: int = 6) -> list[str]:
    """Documented response fields, most recognisable first."""
    available = [f["name"] for f in RESPONSE_FIELDS.get(row.operation_id, [])]
    ordered = [name for name in _HEADLINE_FIELDS if name in available]
    ordered += [name for name in available if name not in ordered]
    return ordered[:limit]


#: Titles that the shape-based template alone would collide on.
#:
#: Four WordPress endpoints return the whole set as one keyed object rather than
#: a list, so they take the ``get`` shape and would otherwise be titled the same
#: as the single-record endpoint beside them. The remaining pairs differ only by
#: whose record they address, or by how far the listing reaches.
_DISAMBIGUATED_TITLES: dict[str, str] = {
    "wp_get_menu_locations": "Get every menu location",
    "wp_get_post_statuses": "Get every post status",
    "wp_get_post_types": "Get every post type",
    "wp_get_taxonomies": "Get every taxonomy",
    "wp_get_current_user": "Get the signed-in user",
    "wp_update_current_user": "Update the signed-in user",
    "wp_list_namespace_block_types": "List the block types in one namespace",
    "wc_list_order_refunds": "List the refunds on one order",
}


#: Operations whose purpose is not conveyed by shape alone.
OVERRIDES: dict[str, dict[str, str]] = {
    "test_connection": {
        "title": "Test the connection",
        "summary": "Checks that the site answers, that the WordPress credentials work, and whether WooCommerce is available.",
        "provides": "Nothing beyond choosing the connection you want to check.",
        "returns": "The site name, the REST namespaces it publishes, and a separate readiness state for WordPress and for WooCommerce.",
        "important": "WordPress and WooCommerce are reported independently, so a WooCommerce problem never hides a working WordPress connection.",
    },
    "wp_create_media": {
        "title": "Upload a media file",
        "summary": "Uploads a file to the WordPress media library.",
        "provides": "A file from an earlier workflow step, the file name to store it under, and optionally details such as the title, alt text, caption or description.",
        "returns": "The created media item, including its ID and the public URL of the uploaded file.",
        "important": "The file is sent exactly as supplied. Nothing is resized, converted, compressed or optimised.",
    },
    "wp_render_block": {
        "title": "Render a block",
        "summary": "Asks WordPress to render one block and return its HTML.",
        "provides": "The block name, such as core/paragraph, and the block attributes to render it with.",
        "returns": "The rendered HTML for that block.",
        "important": "This only renders. Nothing is saved to the site.",
    },
    "wp_search": {
        "title": "Search the site",
        "summary": "Searches published content across the site and returns matching items.",
        "provides": "A search term, and optionally the content types to search and how many results per page.",
        "returns": "A list of matches, each with its ID, title, URL and type, plus pagination details.",
        "important": "",
    },
    "wp_update_comment": {
        "title": "Update a comment",
        "summary": "Changes one existing WordPress comment, including moderating it.",
        "provides": "The comment ID and the fields to change; anything you leave out keeps its current value. Setting the status is how you moderate: approved publishes it, hold sends it back to the moderation queue, spam marks it as spam, and trash moves it to the site's trash.",
        "returns": "The updated comment, including its new status.",
        "important": "This is the one place in this extension where something can be moved to trash, and it is deliberate: marking a comment as spam or trashing it is what moderation means. Nothing is deleted outright - a trashed comment stays in the site's trash until somebody empties it there. No other operation accepts trash as a status.",
    },
    "wc_preview_order_refund": {
        "title": "Preview a refund",
        "summary": "Calculates what a refund for an order would come to, without creating it.",
        "provides": "The order ID and the lines to preview. Each line names the order line it refers to, how many units, and optionally an explicit amount for that line.",
        "returns": "The totals the refund would come to - a breakdown by products, shipping and fees, the subtotal, the tax, the total, and how much of the order is still refundable.",
        "important": "This only calculates. No refund is created, and creating, changing or deleting refunds is not available in this version. The endpoint needs WooCommerce 11.1 or newer; on an older store it does not exist and the site answers with a not-found error. Note that a preview line is keyed by the order's line item ID, which the create-a-refund endpoint calls id.",
    },
    "wc_send_order_details": {
        "title": "Email order details to the customer",
        "summary": "Sends the customer the order details email for one order.",
        "provides": "The order ID.",
        "returns": "A confirmation message from WooCommerce.",
        "important": "This sends a real email to the customer.",
    },
    "wc_send_order_email": {
        "title": "Send an order email to the customer",
        "summary": "Sends the customer a chosen WooCommerce order email, such as the completed-order or refunded-order notification.",
        "provides": "The order ID and the email template to send. You can also send it to a different address and update the billing email at the same time.",
        "returns": "A confirmation message from WooCommerce.",
        "important": "This sends a real email to the customer. Only templates that are valid for that order's current status are accepted.",
    },
    "wc_list_order_email_templates": {
        "title": "List the emails available for an order",
        "summary": "Lists the order emails WooCommerce can currently send for one order.",
        "provides": "The order ID.",
        "returns": "A list of the email templates available for that order, each with its ID and name.",
        "important": "Which templates are available depends on the order's current status. This returns the whole set in one response and does not page.",
    },
    "wc_duplicate_product": {
        "title": "Duplicate a product",
        "summary": "Creates a copy of an existing product.",
        "provides": "The ID of the product to copy.",
        "returns": "The newly created copy, including its new ID.",
        "important": "The copy is created as a draft, following WooCommerce's own behaviour.",
    },
    "wc_list_customer_downloads": {
        "title": "List a customer's downloads",
        "summary": "Lists the downloadable files one customer currently has access to.",
        "provides": "The customer ID.",
        "returns": "A list of the downloads available to that customer, each with its file name, product and remaining downloads.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    # --- Autosaves are not revisions -------------------------------------
    "wp_list_post_autosaves": {
        "title": "List post autosaves",
        "summary": "Lists the autosaves WordPress has stored for one post. An autosave is the editor's in-progress draft, separate from a saved revision.",
        "provides": "The post ID.",
        "returns": "A list of autosaves for that post, each with its ID, author, date and content.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wp_create_post_autosave": {
        "title": "Create a post autosave",
        "summary": "Stores an autosave for one post, the way the block editor does while somebody is typing.",
        "provides": "The post ID and the fields to autosave, such as title, content or excerpt.",
        "returns": _MESSAGE_THE_CREATED_AUTOSAVE_INCLUDING_THE_ID_WORDPRESS_ASSIGNED_TO_IT,
        "important": "An autosave does not change the published post.",
    },
    "wp_get_post_autosave": {
        "title": "Get a post autosave",
        "summary": "Returns one stored autosave for a post.",
        "provides": "The post ID and autosave ID.",
        "returns": _MESSAGE_THE_AUTOSAVE_INCLUDING_ITS_AUTHOR_DATE_TITLE_AND_CONTENT,
        "important": "",
    },
    "wp_list_page_autosaves": {
        "title": "List page autosaves",
        "summary": "Lists the autosaves WordPress has stored for one page. An autosave is the editor's in-progress draft, separate from a saved revision.",
        "provides": "The page ID.",
        "returns": "A list of autosaves for that page, each with its ID, author, date and content.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wp_create_page_autosave": {
        "title": "Create a page autosave",
        "summary": "Stores an autosave for one page, the way the block editor does while somebody is typing.",
        "provides": "The page ID and the fields to autosave, such as title, content or excerpt.",
        "returns": _MESSAGE_THE_CREATED_AUTOSAVE_INCLUDING_THE_ID_WORDPRESS_ASSIGNED_TO_IT,
        "important": "An autosave does not change the published page.",
    },
    "wp_get_page_autosave": {
        "title": "Get a page autosave",
        "summary": "Returns one stored autosave for a page.",
        "provides": "The page ID and autosave ID.",
        "returns": _MESSAGE_THE_AUTOSAVE_INCLUDING_ITS_AUTHOR_DATE_TITLE_AND_CONTENT,
        "important": "",
    },
    "wp_list_block_autosaves": {
        "title": "List reusable block autosaves",
        "summary": "Lists the autosaves WordPress has stored for one reusable block.",
        "provides": "The block ID.",
        "returns": "A list of autosaves for that block, each with its ID, author, date and content.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wp_create_block_autosave": {
        "title": "Create a reusable block autosave",
        "summary": "Stores an autosave for one reusable block.",
        "provides": "The block ID and the fields to autosave.",
        "returns": _MESSAGE_THE_CREATED_AUTOSAVE_INCLUDING_THE_ID_WORDPRESS_ASSIGNED_TO_IT,
        "important": "An autosave does not change the saved block.",
    },
    "wp_get_block_autosave": {
        "title": "Get a reusable block autosave",
        "summary": "Returns one stored autosave for a reusable block.",
        "provides": "The block ID and autosave ID.",
        "returns": _MESSAGE_THE_AUTOSAVE_INCLUDING_ITS_AUTHOR_DATE_TITLE_AND_CONTENT,
        "important": "",
    },
    # --- Each report is its own thing -------------------------------------
    "wc_list_reports": {
        "title": "List the available reports",
        "summary": "Lists which WooCommerce reports this store can produce.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of the available reports, each with its slug and description.",
        "important": "This is the index of reports, not the figures themselves. It returns the whole set in one response and does not page.",
    },
    "wc_get_sales_report": {
        "title": "Get the sales report",
        "summary": "Returns gross and net sales, order and item counts, discounts, shipping and taxes for a period.",
        "provides": "Nothing is required. Choose the period with period, or set an exact range with date min and date max.",
        "returns": "A list with the sales figures for the period, including total sales, net sales, average sales, order count, item count, refunds, discounts, shipping and taxes.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_top_sellers_report": {
        "title": "Get the top sellers report",
        "summary": "Returns the best-selling products for a period, with how many of each were sold.",
        "provides": "Nothing is required. Choose the period with period, or set an exact range with date min and date max.",
        "returns": "A list of the top-selling products, each with its product ID, name and quantity sold.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_coupons_totals_report": {
        "title": "Count coupons by type",
        "summary": "Returns how many coupons the store has of each discount type.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of coupon types, each with its name and how many coupons use it.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_customers_totals_report": {
        "title": "Count customers by type",
        "summary": "Returns how many customers the store has, split into paying and non-paying.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of customer types, each with its name and how many customers it covers.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_orders_totals_report": {
        "title": "Count orders by status",
        "summary": "Returns how many orders the store has in each order status.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of order statuses, each with its name and how many orders are in it.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_products_totals_report": {
        "title": "Count products by type",
        "summary": "Returns how many products the store has of each product type, such as simple or variable.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of product types, each with its name and how many products use it.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_get_reviews_totals_report": {
        "title": "Count reviews by status",
        "summary": "Returns how many product reviews the store has in each moderation status.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of review statuses, each with its name and how many reviews are in it.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    # --- Store data is countries, continents and currencies ---------------
    "wc_list_data_resources": {
        "title": "List the available store data",
        "summary": "Lists which reference data sets WooCommerce can return, such as countries and currencies.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of the available data sets, each with its slug and description.",
        "important": _MESSAGE_THIS_RETURNS_THE_WHOLE_SET_IN_ONE_RESPONSE_AND_DOES_NOT_PAGE,
    },
    "wc_list_continents": {
        "title": "List continents",
        "summary": "Returns every continent WooCommerce knows about, with the countries in each.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of continents, each with its code, name and the countries it contains.",
        "important": _MESSAGE_THIS_IS_WOOCOMMERCE_S_BUILT_IN_REFERENCE_DATA_NOT_YOUR_STORE_S_SETT,
    },
    "wc_get_continent": {
        "title": "Get one continent",
        "summary": "Returns one continent and the countries it contains.",
        "provides": "The continent code, such as eu or na.",
        "returns": "The continent with its code, name and countries, including each country's states and currency.",
        "important": "",
    },
    "wc_list_countries": {
        "title": "List countries",
        "summary": "Returns every country WooCommerce knows about, with its states or provinces.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of countries, each with its two-letter code, name and states.",
        "important": _MESSAGE_THIS_IS_WOOCOMMERCE_S_BUILT_IN_REFERENCE_DATA_NOT_YOUR_STORE_S_SETT,
    },
    "wc_get_country": {
        "title": "Get one country",
        "summary": "Returns one country and its states or provinces.",
        "provides": "The two-letter country code, such as US or DE.",
        "returns": "The country with its code, name and the list of its states.",
        "important": "",
    },
    "wc_list_currencies": {
        "title": "List currencies",
        "summary": "Returns every currency WooCommerce knows about, with its symbol.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "A list of currencies, each with its three-letter code, name and symbol.",
        "important": _MESSAGE_THIS_IS_WOOCOMMERCE_S_BUILT_IN_REFERENCE_DATA_NOT_YOUR_STORE_S_SETT,
    },
    "wc_get_currency": {
        "title": "Get one currency",
        "summary": "Returns one currency and its symbol.",
        "provides": "The three-letter currency code, such as USD or EUR.",
        "returns": "The currency with its code, name and symbol.",
        "important": "",
    },
    "wc_get_current_currency": {
        "title": "Get the store's currency",
        "summary": "Returns the currency this store is currently selling in.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "The store's currency with its code, name and symbol.",
        "important": "",
    },
    # --- Stock and price are the reason most people come here -------------
    "wc_update_product": {
        "title": "Update a product",
        "summary": "Changes the data of one existing WooCommerce product, including its price and stock level.",
        "provides": "The product ID and only the fields that should change, such as regular price, sale price, stock quantity, stock status, name, description or status. Anything you leave out keeps its current value.",
        "returns": "The updated product with its current values.",
        "important": "This changes the product itself. A variable product's prices and stock live on its variations, which are updated through the variation operations.",
    },
    "wc_batch_products": {
        "title": "Create or update several products",
        "summary": "Creates and updates many WooCommerce products in one request, which is the efficient way to push a price or stock update for a whole catalogue.",
        "provides": "A list of products to create and a list of products to update. Each update entry needs the product ID plus the fields that change, such as regular price, sale price or stock quantity.",
        "returns": "The created and updated products, grouped under create and update the way WooCommerce returns them.",
        "important": "Deleting through a batch is not available in this version. WooCommerce accepts at most 100 items per request.",
    },
    "wc_update_product_variation": {
        "title": "Update a product variation",
        "summary": "Changes one variation of a variable product, including its own price and stock level.",
        "provides": "The product ID and variation ID, plus only the fields that should change, such as regular price, sale price, stock quantity or stock status. Anything you leave out keeps its current value.",
        "returns": "The updated variation with its current values.",
        "important": "A variation carries its own price and stock, separate from the parent product.",
    },
    "wc_batch_product_variations": {
        "title": "Create or update several product variations",
        "summary": "Creates and updates many variations of one product in a single request, for bulk price or stock changes.",
        "provides": "The product ID, plus a list of variations to create and a list to update. Each update entry needs the variation ID and the fields that change, such as regular price or stock quantity.",
        "returns": "The created and updated variations, grouped under create and update.",
        "important": "Deleting through a batch is not available in this version. WooCommerce accepts at most 100 items per request.",
    },
    "wc_get_system_status": {
        "title": "Get the store's system status",
        "summary": "Returns WooCommerce's own diagnostic report about the store environment.",
        "provides": _MESSAGE_NOTHING_BEYOND_THE_CONNECTION,
        "returns": "The environment, database, active theme, settings and security sections of the WooCommerce status report.",
        "important": "Read only. Running system status tools is not available in this version.",
    },
}


_TITLE_TEMPLATES = {
    "list": "List {plural}",
    "get": "Get {article} {singular}",
    "create": "Create {article} {singular}",
    "update": "Update {article} {singular}",
    "batch": "Create or update several {plural}",
    "media_create": "Upload {article} {singular}",
}


def _title(row: Operation, singular: str, plural: str) -> str:
    disambiguated = _DISAMBIGUATED_TITLES.get(row.operation_id)
    if disambiguated is not None:
        return disambiguated
    template = _TITLE_TEMPLATES.get(row.shape)
    if template is None:
        return row.display_name
    return template.format(singular=singular, plural=plural, article=_article(singular))


def _build(row: Operation) -> OperationDoc:
    singular, plural = _nouns(row)
    provider = "WordPress" if row.provider == "wordpress" else "WooCommerce"
    endpoint = f"{row.method} {row.route_pattern.replace('/wp-json', '')}"
    override = OVERRIDES.get(row.operation_id, {})

    required = _required_body(row)
    optional = _optional_body(row)
    filters = _filters(row)
    returned = _returned_fields(row)
    identified_by = _path_phrase(row, singular)

    if row.shape == "list":
        summary = f"Lists the {provider} {plural} on the site."
        pieces = ["Nothing is required beyond the connection."]
        if identified_by:
            pieces = [f"The {identified_by} to list {plural} for."]
        if filters:
            pieces.append(f"You can narrow the result by {_join(filters)}.")
        if _supports_paging(row):
            pieces.append("Use page and per page to work through a long list.")
        provides = " ".join(pieces)
        returns = f"A list of {plural}"
        if returned:
            returns += f", each with fields such as {_join(returned[:4], conjunction='and')}"
        returns += ", together with pagination details: the total number of items, the total number of pages, and links to the next and previous pages."
        important = (
            ""
            if _supports_paging(row)
            else "This endpoint returns the whole set in one response and does not page."
        )
    elif row.shape == "get":
        summary = (
            f"Returns the full record for one {provider} {singular}, found by its {identified_by}."
            if identified_by
            else f"Returns the current {provider} {singular} for this site."
        )
        provides = (
            f"The {identified_by}." if identified_by else _MESSAGE_NOTHING_BEYOND_THE_CONNECTION
        )
        if filters:
            provides += f" You can also set {_join(filters)}."
        returns = f"The {singular}"
        if returned:
            returns += f", including {_join(returned[:5], conjunction='and')}"
        returns += "."
        important = ""
    elif row.shape == "create":
        summary = f"Creates a new {provider} {singular}."
        provides = (
            f"The fields for the new {singular}."
            if not required
            else f"The fields for the new {singular}. {_join(required, conjunction='and').capitalize()} must be supplied."
        )
        if identified_by:
            provides = (
                f"The {identified_by} it belongs to, plus " + provides[0].lower() + provides[1:]
            )
        if optional:
            provides += f" You can also set {_join(optional)}."
        returns = f"The created {singular}, including the ID the site assigned to it."
        important = ""
    elif row.shape == "update":
        summary = f"Changes the data of one existing {provider} {singular}."
        target = f"The {identified_by}" if identified_by else "The connection"
        provides = (
            f"{target}, plus only the fields that should change"
            + (f", such as {_join(optional)}" if optional else "")
            + ". Anything you leave out keeps its current value."
        )
        returns = f"The updated {singular} with its current values."
        important = ""
    elif row.shape == "batch":
        summary = f"Creates and updates several {provider} {plural} in one request."
        provides = (
            f"A list of {plural} to create and a list of {plural} to update. "
            f"Each entry accepts the same fields as the single-{singular} operations, "
            "and every update entry needs the ID of the record it changes."
        )
        returns = f"The created and updated {plural}, grouped the way WooCommerce returns them."
        important = "Deleting through a batch is not available in this version."
    elif row.shape == "media_create":
        summary = f"Uploads a new {provider} {singular}."
        provides = "A file, a file name, and optionally the item's details."
        returns = f"The created {singular}."
        important = ""
    else:  # action, read_post
        summary = f"Runs the {provider} {singular} operation."
        provides = (
            f"The {identified_by}." if identified_by else _MESSAGE_NOTHING_BEYOND_THE_CONNECTION
        )
        returns = "What the site returns for this operation."
        important = ""

    if row.resource in READ_ONLY_RESOURCES and row.shape in {"list", "get"}:
        read_only_note = f"This version reads {plural} only; it does not change them."
        important = f"{important} {read_only_note}".strip()
    if row.resource == "webhooks":
        important = (
            f"{important} This manages the webhook record inside WooCommerce only. "
            "It creates no Flow Steward trigger, callback, subscription or workflow."
        ).strip()
    if row.resource == "product_variations" and row.shape in {"create", "update"}:
        important = f"{important} Variations belong to one product and are managed separately from it.".strip()
    if row.resource == "products" and row.shape == "update":
        important = f"{important} Product variations are updated through a separate variation operation.".strip()

    return OperationDoc(
        operation_id=row.operation_id,
        title=override.get("title") or _title(row, singular, plural),
        summary=override.get("summary") or summary,
        endpoint=endpoint,
        provides=override.get("provides") or provides,
        returns=override.get("returns") or returns,
        important=override.get("important", important),
        introduced_in=INITIAL_VERSION,
        documentation_url=row.doc_url,
    )


TEST_CONNECTION_DOC = OperationDoc(
    operation_id="test_connection",
    title=OVERRIDES["test_connection"]["title"],
    summary=OVERRIDES["test_connection"]["summary"],
    endpoint="GET /wp-json/",
    provides=OVERRIDES["test_connection"]["provides"],
    returns=OVERRIDES["test_connection"]["returns"],
    important=OVERRIDES["test_connection"]["important"],
    introduced_in=INITIAL_VERSION,
    documentation_url="https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/",
)

VALIDATE_SETTINGS_DOC = OperationDoc(
    operation_id="validate_connection_settings",
    title="Check connection settings",
    summary=(
        "Checks the site URL and the WooCommerce credential pair before the connection is "
        "saved, without contacting the site."
    ),
    endpoint=NO_REQUEST,
    provides="The site URL from the connection form. No secret is sent to this check.",
    returns="Confirmation that the settings are usable, with the site URL as it will be stored.",
    important=(
        "This runs in the browser's save step. It contacts nothing and never receives the "
        "Application Password or the WooCommerce keys."
    ),
    introduced_in=INITIAL_VERSION,
    documentation_url="https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/",
)

EXPORT_PRODUCTS_DOC = OperationDoc(
    operation_id="wc_export_products",
    title="Export every matching WooCommerce product",
    summary=(
        "Reads every page of matching WooCommerce products and saves the complete catalog "
        "as a downloadable JSON Lines file."
    ),
    endpoint="GET /wp-json/wc/v3/products (all pages)",
    provides=(
        "The WooCommerce connection and, optionally, the same catalog filters as the single-page "
        "product list. Per page controls request size; page and offset are intentionally unavailable."
    ),
    returns=(
        "A downloadable JSON Lines artifact plus the number of products and pages read, the total "
        "reported by WooCommerce, its byte size and checksum."
    ),
    important=(
        "Pagination is completed inside this extension. The full catalog is not placed in workflow "
        "state or the job log."
    ),
    introduced_in=INITIAL_VERSION,
    documentation_url="https://developer.woocommerce.com/docs/apis/rest-api/v3/products/",
)

OPERATION_DOCS: dict[str, OperationDoc] = {
    "test_connection": TEST_CONNECTION_DOC,
    "validate_connection_settings": VALIDATE_SETTINGS_DOC,
    "wc_export_products": EXPORT_PRODUCTS_DOC,
    **{row.operation_id: _build(row) for row in REST_OPERATIONS},
}


def operation_doc(operation_id: str) -> OperationDoc | None:
    return OPERATION_DOCS.get(operation_id)


def resource_heading(resource: str) -> str:
    """Section heading for one resource on an API page."""
    if resource in RESOURCE_HEADINGS:
        return RESOURCE_HEADINGS[resource]
    _singular, plural = RESOURCE_NOUNS.get(resource, (resource, resource))
    return plural[:1].upper() + plural[1:]


__all__ = [
    "INITIAL_VERSION",
    "OPERATION_DOCS",
    "READ_ONLY_RESOURCES",
    "RESOURCE_GROUPS",
    "RESOURCE_HEADINGS",
    "RESOURCE_NOUNS",
    "OperationDoc",
    "operation_doc",
    "resource_heading",
]
