"""Documented fields this version refuses to carry, declared once.

The official contracts include a handful of credential fields that a workflow
has no business setting or receiving: the password that protects a post, page or
block, and the password on a WooCommerce customer account. This module is the
single source for that decision. The generators build the manifests, step forms
and documentation from it, and the runtime rejects the same fields, so a field
can never be published in one place and refused in another.

The policy is deliberately narrow. It names the exact operations and the exact
top-level field of the documented record. It is not a rule about the word
"password": it never touches WordPress ``meta``, WooCommerce ``meta_data``, a
WooCommerce setting whose own ``type`` is ``password``, ordinary text that
mentions a password, or any nested value that merely shares the name. The
connection's own WordPress Application Password is a stored connection secret
and is untouched by any of this.
"""

from __future__ import annotations

from typing import Any

from .catalog import Operation

#: The documented field name used by WordPress and WooCommerce customer records.
PASSWORD_FIELD = "password"  # pragma: allowlist secret

#: WooCommerce 11 also emits this undocumented product-record credential field.
#: It is intentionally absent from the public contract and must be removed before
#: a response can enter workflow state or the external-effect replay store.
POST_PASSWORD_FIELD = "post_password"  # pragma: allowlist secret

#: Operations whose documented **query** accepts the password of a protected
#: record. Supplying it would send a content credential in a URL.
EXCLUDED_QUERY_FIELDS: dict[str, frozenset[str]] = {
    "wp_get_post": frozenset({PASSWORD_FIELD}),
    "wp_get_page": frozenset({PASSWORD_FIELD}),
    "wp_get_block": frozenset({PASSWORD_FIELD}),
    "wp_list_comments": frozenset({PASSWORD_FIELD}),
    "wp_get_comment": frozenset({PASSWORD_FIELD}),
}

#: Operations whose documented **body** accepts a password: the protected-content
#: password on WordPress records, and the account password on a WooCommerce
#: customer.
EXCLUDED_BODY_FIELDS: dict[str, frozenset[str]] = {
    "wp_create_post": frozenset({PASSWORD_FIELD}),
    "wp_update_post": frozenset({PASSWORD_FIELD}),
    "wp_create_post_autosave": frozenset({PASSWORD_FIELD}),
    "wp_create_page": frozenset({PASSWORD_FIELD}),
    "wp_update_page": frozenset({PASSWORD_FIELD}),
    "wp_create_page_autosave": frozenset({PASSWORD_FIELD}),
    "wp_create_block": frozenset({PASSWORD_FIELD}),
    "wp_update_block": frozenset({PASSWORD_FIELD}),
    "wp_create_block_autosave": frozenset({PASSWORD_FIELD}),
    "wc_create_customer": frozenset({PASSWORD_FIELD}),
    "wc_update_customer": frozenset({PASSWORD_FIELD}),
    # The batch endpoint publishes the same customer record as its body model.
    "wc_batch_customers": frozenset({PASSWORD_FIELD}),
}

#: Batch members whose entries would otherwise accept the same customer password.
EXCLUDED_BATCH_ITEM_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "wc_batch_customers": {
        "create": frozenset({PASSWORD_FIELD}),
        "update": frozenset({PASSWORD_FIELD}),
    },
}

#: Operations whose own documented record carries a direct ``password``
#: property, listed one by one.
#:
#: Naming a resource family instead would be wrong in both directions. A
#: revision, an autosave and a customer's downloads listing share a resource
#: with a record that has a password but do not have one themselves, so a
#: family rule silently deletes whatever a site happens to return under that
#: key — a plugin's own field, for instance. ``test_field_policy`` derives this
#: set from the committed reference and fails if the two disagree.
PASSWORD_RESPONSE_OPERATIONS: frozenset[str] = frozenset(
    {
        "wp_list_posts",
        "wp_get_post",
        "wp_create_post",
        "wp_update_post",
        "wp_list_pages",
        "wp_get_page",
        "wp_create_page",
        "wp_update_page",
        "wp_list_blocks",
        "wp_get_block",
        "wp_create_block",
        "wp_update_block",
        "wp_list_users",
        "wp_get_user",
        "wp_get_current_user",
        "wc_list_customers",
        "wc_get_customer",
        "wc_create_customer",
        "wc_update_customer",
        "wc_batch_customers",
    }
)

#: Product operations whose upstream response may contain ``post_password`` even
#: though the official WooCommerce REST schema does not document that property.
PRODUCT_POST_PASSWORD_RESPONSE_OPERATIONS: frozenset[str] = frozenset(
    {
        "wc_list_products",
        "wc_create_product",
        "wc_get_product",
        "wc_update_product",
        "wc_batch_products",
        "wc_duplicate_product",
    }
)


def excluded_query_fields(operation_id: str) -> frozenset[str]:
    """Query fields this version does not publish or accept."""
    return EXCLUDED_QUERY_FIELDS.get(operation_id, frozenset())


def excluded_body_fields(operation_id: str) -> frozenset[str]:
    """Body fields this version does not publish or accept."""
    return EXCLUDED_BODY_FIELDS.get(operation_id, frozenset())


def excluded_batch_item_fields(operation_id: str, member: str) -> frozenset[str]:
    """Batch-entry fields this version does not publish or accept."""
    return EXCLUDED_BATCH_ITEM_FIELDS.get(operation_id, {}).get(member, frozenset())


def excluded_response_fields(row: Operation) -> frozenset[str]:
    """Top-level record properties this version never returns."""
    names: set[str] = set()
    if row.operation_id in PASSWORD_RESPONSE_OPERATIONS:
        names.add(PASSWORD_FIELD)
    if row.operation_id in PRODUCT_POST_PASSWORD_RESPONSE_OPERATIONS:
        names.add(POST_PASSWORD_FIELD)
    return frozenset(names)


def _without(record: Any, names: frozenset[str]) -> Any:
    """Drop the named top-level keys from one record, and only those.

    Nothing recurses: a value nested inside ``meta``, ``meta_data`` or any other
    structure keeps whatever keys it has.
    """
    if not isinstance(record, dict):
        return record
    if not any(name in record for name in names):
        return record
    return {key: value for key, value in record.items() if key not in names}


def sanitized_response_body(row: Operation, body: Any) -> Any:
    """Remove excluded record properties from one upstream response body.

    The runtime forwards upstream bodies to the workflow, so the excluded
    property is dropped here, before the result is built. Which shape to expect
    comes from the operation itself: a list returns records, a batch returns
    them grouped by member, and everything else returns one record. The removed
    value is never logged or reported.
    """
    names = excluded_response_fields(row)
    if not names:
        return body
    if row.shape == "list":
        if isinstance(body, list):
            return [_without(item, names) for item in body]
        return body
    if row.shape == "batch":
        if isinstance(body, dict):
            return {
                member: (
                    [_without(item, names) for item in entries]
                    if isinstance(entries, list)
                    else entries
                )
                for member, entries in body.items()
            }
        return body
    return _without(body, names)


__all__ = [
    "EXCLUDED_BATCH_ITEM_FIELDS",
    "EXCLUDED_BODY_FIELDS",
    "EXCLUDED_QUERY_FIELDS",
    "PASSWORD_FIELD",
    "PASSWORD_RESPONSE_OPERATIONS",
    "POST_PASSWORD_FIELD",
    "PRODUCT_POST_PASSWORD_RESPONSE_OPERATIONS",
    "excluded_batch_item_fields",
    "excluded_body_fields",
    "excluded_query_fields",
    "excluded_response_fields",
    "sanitized_response_body",
]
