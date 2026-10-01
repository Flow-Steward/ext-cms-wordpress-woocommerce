"""The markers the official references use, and what this version does with them.

Every case here is either a string that appears in the committed snapshot or a
string shaped like one. Nothing reaches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from markers import is_never_included, is_required, is_response_suppressed, is_write_only
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID
from runtime.parameters import BODY_FIELDS, QUERY_FIELDS, RESPONSE_FIELDS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = BUNDLE_ROOT / "contracts" / "rest_reference.yaml"


def _snapshot() -> dict[str, Any]:
    return yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))


def _described_fields(page: dict[str, Any]):
    """Every documented field on a page, with the table it came from."""
    for section in page.get("sections") or []:
        for field in section.get("fields") or []:
            yield "argument", section.get("heading", ""), field
    for table in page.get("properties") or []:
        for field in table.get("fields") or []:
            yield "property", table.get("heading", ""), field
    for field in page.get("schema") or []:
        yield "property", "schema", field


@pytest.mark.parametrize(
    "description",
    [
        "HTML title for the term. Required: 1",
        "Limit result set to blocks matching the search term. Required: 1",
        "The sidebar the widget belongs to. Required: 1 Default: wp_inactive_widgets",
        "required:1",
        "REQUIRED : 1",
    ],
)
def test_a_wordpress_required_marker_is_read(description: str) -> None:
    assert is_required(description) is True


@pytest.mark.parametrize(
    "description",
    [
        "The email address for the customer. MANDATORY",
        "Coupon code. MANDATORY",
        "Order note content. MANDATORY",
    ],
)
def test_a_woocommerce_mandatory_marker_is_read(description: str) -> None:
    assert is_required(description) is True


@pytest.mark.parametrize(
    "description",
    [
        # The commonest sentence in both references. It describes the value a
        # field must carry when supplied, not whether it has to be supplied.
        "Required to be true, as terms do not support trashing.",
        "Required to be true , as resource does not support trashing.",
        "The minimum required version of WordPress.",
        "The minimum required version of PHP.",
        "Products required an assigned attribute term.",
        "Whether the theme has the required assets.",
        # Neither provider's marker, so neither is claimed.
        "Tax class name. REQUIRED",
        "Brand ID REQUIRED FOR WRITE OPERATIONS",
        "This field is mandatory on some hosts.",
        "",
    ],
)
def test_ordinary_prose_is_not_a_required_marker(description: str) -> None:
    assert is_required(description) is False


def test_write_only_and_never_included_are_read() -> None:
    assert is_write_only("Customer password. WRITE-ONLY") is True
    assert is_never_included("Password for the user (never included). Required: 1") is True
    assert is_response_suppressed("Customer password. WRITE-ONLY") is True
    assert is_response_suppressed("Downloadable product ID. READ-ONLY") is False


#: The heading a provider gives the argument table for each operation shape. A
#: field that is required when creating a record is optional when updating it,
#: so a marker only speaks for the section it appears in.
_SECTION_PREFIX_BY_SHAPE = {
    "create": ("create",),
    "update": ("update",),
    "list": ("list",),
    "get": ("retrieve",),
}


def test_every_snapshot_required_marker_reaches_the_generated_tables() -> None:
    """No marker in the snapshot is silently dropped on the way to a contract.

    This is the drift check: it reads the committed documentation, finds every
    field a provider marks required in the section that describes this very
    operation, and insists the published contract agrees.
    """
    snapshot = _snapshot()
    pages = {(page["provider"], page["slug"]): page for page in snapshot["pages"]}
    missed: list[str] = []
    checked = 0
    for row in REST_OPERATIONS:
        prefixes = _SECTION_PREFIX_BY_SHAPE.get(row.shape)
        if not prefixes:
            continue
        page = pages[(row.provider, row.doc_slug)]
        published = {
            field["name"]: field
            for field in (QUERY_FIELDS.get(row.operation_id) or [])
            + (BODY_FIELDS.get(row.operation_id) or [])
        }
        path_names = {name for name, _kind in row.path_params}
        for kind, heading, field in _described_fields(page):
            if kind != "argument" or not heading.lower().startswith(prefixes):
                continue
            if not is_required(field.get("description", "")):
                continue
            name = field.get("name")
            if name in path_names or name not in published:
                continue
            checked += 1
            if not published[name].get("required"):
                missed.append(f"{row.operation_id}.{name} ({heading})")
    assert missed == []
    # The check is worthless if it never actually looked at a marked field.
    assert checked >= 4


def test_a_field_the_reference_never_returns_is_absent_from_response_models() -> None:
    snapshot = _snapshot()
    pages = {(page["provider"], page["slug"]): page for page in snapshot["pages"]}
    leaked: list[str] = []
    for row in REST_OPERATIONS:
        page = pages[(row.provider, row.doc_slug)]
        published = {field["name"] for field in RESPONSE_FIELDS.get(row.operation_id) or []}
        for kind, _heading, field in _described_fields(page):
            if kind != "property" or not is_response_suppressed(field.get("description", "")):
                continue
            if field.get("name") in published:
                leaked.append(f"{row.operation_id}.{field['name']}")
    assert leaked == []


def test_the_documented_examples_from_the_brief_are_required() -> None:
    """The specific fields whose required marker used to be dropped."""
    expected = {
        ("wp_create_category", "name"),
        ("wp_create_tag", "name"),
        ("wp_create_widget", "sidebar"),
        ("wc_create_customer", "email"),
    }
    for operation_id, field_name in expected:
        assert operation_id in REST_OPERATIONS_BY_ID, operation_id
        rows = BODY_FIELDS[operation_id]
        match = next(row for row in rows if row["name"] == field_name)
        assert match.get("required") is True, (operation_id, field_name)
    search = next(row for row in QUERY_FIELDS["wp_search_block_directory"] if row["name"] == "term")
    assert search.get("required") is True
