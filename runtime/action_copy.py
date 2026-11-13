"""Workflow field guidance; presentation only, never request validation."""

from __future__ import annotations

import json
from typing import Any

# Examples illustrate values; they do not populate or change action defaults.
FIELD_GUIDANCE: dict[str, tuple[str, str]] = {
    "page": (
        "Page number to read, starting at 1. Use the returned pagination to request later pages.",
        "1",
    ),
    "per_page": (
        "Maximum records in each page. A list action returns one page; the product export reads all matching pages.",
        "50",
    ),
    "offset": ("Number of matching records to skip before returning this page.", "0"),
    "search": ("Text to match against this resource's searchable fields.", "summer"),
    "context": (
        "Response context. Choose edit only when you need editable fields and the connection user can access them.",
        "",
    ),
    "order": ("Ascending or descending order for the selected sort field.", ""),
    "orderby": (
        "Field used to sort matching records. Choose from this operation's available values.",
        "",
    ),
    "include": (
        "Return only these existing record IDs, as a JSON array of numbers.",
        "[1042, 1043]",
    ),
    "exclude": ("Exclude these existing record IDs, as a JSON array of numbers.", "[1042]"),
    "slug": (
        "URL-friendly resource name. On list actions it filters results; on write actions it sets the resource slug.",
        "summer-collection",
    ),
    "sku": (
        "Merchant stock-keeping code. On list actions it filters products; on write actions it sets the product or variation SKU.",
        "MUG-BLUE-01",
    ),
    "regular_price": (
        "Regular unit price as decimal text in the store currency; do not include a currency symbol.",
        "19.90",
    ),
    "sale_price": ("Sale unit price as decimal text in the store currency.", "16.90"),
    "manage_stock": (
        "Enable stock management for this product or variation before setting its stock quantity.",
        "true",
    ),
    "stock_quantity": (
        "Absolute stock count for this product or variation when stock management is enabled.",
        "24",
    ),
    "title": ("Title to save for this content item.", "Summer collection"),
    "content": (
        "Content to save. WordPress accepts HTML subject to the connected user's permissions.",
        "<p>Explore our summer collection.</p>",
    ),
    "alt_text": (
        "Text describing the media image for readers using assistive technology.",
        "Blue ceramic mug viewed from the side",
    ),
    "caption": ("Caption to display with this media item.", "Blue mug, 300 ml"),
    "excerpt": ("Short summary of the content item.", "Meet our summer collection."),
    "short_description": (
        "Short product summary, separate from its full description.",
        "Blue ceramic mug, 300 ml.",
    ),
    "featured_media": (
        "Existing WordPress media ID to use as the featured image. Get the ID from a media lookup or upload.",
        "1042",
    ),
    "artifact_handle": (
        "File handle returned by an earlier workflow file step. Bind that output here; a local path or public URL is not a file handle.",
        "",
    ),
    "filename": (
        "Filename to store in the WordPress media library, including its extension.",
        "blue-mug.jpg",
    ),
    "content_type": ("MIME type of the uploaded file, when supplied.", "image/jpeg"),
    "email": ("Email address for this record or filter.", "buyer@example.com"),
    "customer_note": (
        "Customer-facing note saved on the WooCommerce order.",
        "Please deliver after 10:00.",
    ),
    "note": ("Text of the order note to create.", "Packed and ready for dispatch."),
    "set_paid": (
        "Mark this order as paid; WooCommerce can trigger its payment-complete behavior, including stock changes.",
        "true",
    ),
    "currency": ("Three-letter currency code supported by this operation.", "EUR"),
    "code": ("Coupon code to save or match.", "SUMMER10"),
    "date": (
        "Publication date and time in the site's timezone, using ISO 8601.",
        "2026-11-13T10:00:00",
    ),
    "date_gmt": ("Publication date and time in UTC, using ISO 8601.", "2026-11-13T08:00:00"),
    "after": (
        "Return records created or published after this ISO 8601 date and time.",
        "2026-11-01T00:00:00",
    ),
    "before": (
        "Return records created or published before this ISO 8601 date and time.",
        "2026-12-01T00:00:00",
    ),
    "modified_after": (
        "Return records modified after this ISO 8601 date and time.",
        "2026-11-01T00:00:00",
    ),
    "modified_before": (
        "Return records modified before this ISO 8601 date and time.",
        "2026-12-01T00:00:00",
    ),
    "dates_are_gmt": ("Interpret the date filters as UTC instead of the site's timezone.", "true"),
    "meta": (
        "Registered WordPress metadata as a JSON object. Available keys depend on the site's REST-exposed metadata.",
        "",
    ),
    "meta_data": (
        "WooCommerce metadata as JSON entries containing key and value. Use keys recognized by your store.",
        '[{"key":"supplier_ref","value":"SUP-42"}]',
    ),
    "line_items": (
        "Order or refund-preview lines. Use the nested fields declared for this operation; product IDs and existing order-line IDs serve different purposes.",
        "",
    ),
    "images": (
        "Product image entries. Use an existing media ID or a supported image source, with optional alt text.",
        '[{"src":"https://example.com/blue-mug.jpg","alt":"Blue ceramic mug"}]',
    ),
    "billing": (
        "Billing address fields as a JSON object. Omitted fields keep the operation's native behavior.",
        '{"first_name":"Alex","last_name":"Morgan","email":"buyer@example.com"}',
    ),
    "shipping": (
        "Shipping address for orders or customers; for a tax rate, whether that tax applies to shipping. Follow this field's declared type.",
        "",
    ),
    "create_items": (
        "JSON array of new records to create in this batch. Each entry uses the create fields for this resource; inspect each returned item for errors.",
        "",
    ),
    "update_items": (
        "JSON array of existing records to change in this batch. Each entry needs its record ID and changed fields; inspect each returned item for errors.",
        "",
    ),
}


def field_guidance(row: Any, field: dict[str, Any]) -> dict[str, str]:
    """Explain existing fields without altering their shape, widget or default."""
    name = str(field["name"])
    schema = field.get("schema") or {}
    help_text, placeholder = FIELD_GUIDANCE.get(name, ("", ""))
    if name == "slug" and schema.get("type") == "array":
        placeholder = '["summer-collection"]'
        help_text = "Return records with one of these URL-friendly slugs, as a JSON array."
    if name == "customer_note" and field["value_type"] == "boolean":
        placeholder = "true"
        help_text = "Make this order note visible to the customer rather than keeping it private."
    path_names = {item[0] for item in row.path_params}
    if name in path_names:
        help_text = (
            f"Existing {name.replace('_', ' ')} in {row.route}. "
            "Use the identifier returned by the corresponding list or lookup action, not a display name."
        )
        placeholder = "1042" if field["value_type"] == "integer" else ""
    if not help_text:
        role = "Filter" if row.method == "GET" else "Value to save"
        help_text = f"{role} for {name.replace('_', ' ')} on this {row.provider} {row.resource.replace('_', ' ')} action."
    if schema.get("enum"):
        help_text += " Choose one of the listed values."
    if "minimum" in schema or "maximum" in schema:
        help_text += f" Allowed range: {schema.get('minimum', 'unbounded')} to {schema.get('maximum', 'unbounded')}."
    if field["value_type"] in {"array", "object"}:
        help_text += " Supply JSON or bind a matching value from an earlier step."
    result = {"help_text": help_text}
    if placeholder:
        if field["value_type"] in {"array", "object", "json"}:
            try:
                json.loads(placeholder)
            except json.JSONDecodeError:
                # A JSON editor needs quoted string syntax, even when the
                # executable schema also permits plain string values.
                placeholder = json.dumps(placeholder)
        result["placeholder"] = placeholder
    return result
