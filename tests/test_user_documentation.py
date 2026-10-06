"""Every operation is explained in plain language, in one place, on every surface."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from runtime.catalog import REST_OPERATIONS, REST_OPERATIONS_BY_ID
from runtime.catalog_export import EXPORT_PRODUCTS_OPERATION_ID
from runtime.coverage import EXCLUDED_ROWS, EXCLUSION_REASONS, coverage_rows, explain
from runtime.descriptions import (
    INITIAL_VERSION,
    OPERATION_DOCS,
    RESOURCE_GROUPS,
    RESOURCE_NOUNS,
    catalog_description,
)

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
PAGE_BUILDER = BUNDLE_ROOT / "tests" / "reference" / "build_ui_pages.py"
ALL_IDS = set(REST_OPERATIONS_BY_ID) | {
    "test_connection",
    "validate_connection_settings",
    EXPORT_PRODUCTS_OPERATION_ID,
}

#: Words that make a description technical rather than plain.
JARGON_ONLY = re.compile(r"^(input|output|payload|source|action|request|response)\b", re.I)


def _yaml(relative: str) -> dict:
    return yaml.safe_load((BUNDLE_ROOT / relative).read_text())


def _page_text(page_id: str) -> str:
    page = _yaml(f"ui/pages/{page_id}.yaml")
    return "\n".join(str(component.get("body") or "") for component in page["components"])


# -- Every operation is documented ---------------------------------------


def test_every_operation_has_a_documentation_block() -> None:
    assert set(OPERATION_DOCS) == ALL_IDS


@pytest.mark.parametrize("operation_id", sorted(ALL_IDS))
def test_each_block_explains_purpose_inputs_and_outputs(operation_id: str) -> None:
    doc = OPERATION_DOCS[operation_id]
    assert doc.title.strip()
    assert doc.summary.strip().endswith("."), doc.summary
    assert len(doc.summary.split()) >= 5, doc.summary
    assert doc.provides.strip(), operation_id
    assert doc.returns.strip(), operation_id
    assert doc.introduced_in == INITIAL_VERSION
    assert doc.documentation_url.startswith("https://")
    assert not JARGON_ONLY.match(doc.summary), doc.summary


@pytest.mark.parametrize("operation_id", sorted(ALL_IDS))
def test_no_description_is_only_a_method_and_route(operation_id: str) -> None:
    doc = OPERATION_DOCS[operation_id]
    assert not re.fullmatch(r"(GET|POST|PUT)\s+\S+", doc.summary.strip())
    assert doc.summary.strip() != doc.endpoint


def test_list_operations_explain_filters_and_pagination() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "list":
            continue
        doc = OPERATION_DOCS[row.operation_id]
        assert "a list" in doc.returns.lower(), row.operation_id
        # Either it pages, or it says plainly that it does not.
        assert "pagination" in doc.returns.lower() or "one response" in doc.important.lower(), (
            row.operation_id
        )


def test_create_operations_explain_required_fields_and_the_returned_record() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "create":
            continue
        doc = OPERATION_DOCS[row.operation_id]
        assert "created" in doc.returns.lower(), row.operation_id
        assert "ID" in doc.returns, row.operation_id


def test_update_operations_explain_identification_and_untouched_values() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "update":
            continue
        doc = OPERATION_DOCS[row.operation_id]
        assert "keeps its current value" in doc.provides, row.operation_id
        assert "updated" in doc.returns.lower(), row.operation_id


def test_batch_operations_state_that_deletion_is_unavailable() -> None:
    for row in REST_OPERATIONS:
        if row.shape != "batch":
            continue
        assert "Deleting" in OPERATION_DOCS[row.operation_id].important, row.operation_id


def test_every_resource_has_a_plain_noun() -> None:
    for row in REST_OPERATIONS:
        assert row.resource in RESOURCE_NOUNS, row.resource


# -- The surfaces agree ---------------------------------------------------


def test_the_operation_manifest_carries_the_same_descriptions() -> None:
    operations = {
        row["operation_id"]: row for row in _yaml("contracts/operation_manifest.yaml")["operations"]
    }
    assert set(operations) == ALL_IDS
    for operation_id, row in operations.items():
        doc = OPERATION_DOCS[operation_id]
        assert row["description"] == doc.summary
        assert row["display_name"] == doc.title


def test_every_builder_action_has_a_human_description() -> None:
    actions = {row["action_id"]: row for row in _yaml("ui/actions/actions.yaml")["actions"]}
    assert set(actions) == ALL_IDS
    for action_id, row in actions.items():
        doc = OPERATION_DOCS[action_id]
        assert row["description"].strip(), action_id
        assert row["description"] == catalog_description(doc)
        assert row["description"].startswith(doc.summary)
        assert row["title"] == doc.title
        assert not re.fullmatch(r"(GET|POST|PUT)\s+\S+", row["description"].strip())


def test_every_rest_action_names_the_endpoint_it_calls() -> None:
    """The builder catalog has no field for the route, so the description carries it."""
    actions = {row["action_id"]: row for row in _yaml("ui/actions/actions.yaml")["actions"]}
    for operation_id in sorted(REST_OPERATIONS_BY_ID):
        doc = OPERATION_DOCS[operation_id]
        assert actions[operation_id]["description"].endswith(f"Calls {doc.endpoint}.")


def test_the_api_pages_are_rebuilt_from_the_same_metadata() -> None:
    result = subprocess.run(
        [sys.executable, str(PAGE_BUILDER), "--check"],
        cwd=str(BUNDLE_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("operation_id", sorted(REST_OPERATIONS_BY_ID))
def test_each_operation_appears_on_its_provider_page(operation_id: str) -> None:
    row = REST_OPERATIONS_BY_ID[operation_id]
    page = "wordpress-api" if row.provider == "wordpress" else "woocommerce-api"
    text = _page_text(page)
    doc = OPERATION_DOCS[operation_id]

    assert f"### {doc.title}" in text
    assert f"`{doc.endpoint}`" in text
    assert doc.provides in text
    assert doc.returns in text
    if doc.important:
        assert doc.important in text


def test_the_api_pages_group_operations_by_resource() -> None:
    for provider, page_id in (("wordpress", "wordpress-api"), ("woocommerce", "woocommerce-api")):
        page = _yaml(f"ui/pages/{page_id}.yaml")
        titles = [component["title"] for component in page["components"]]
        for heading, _resources in RESOURCE_GROUPS[provider]:
            assert heading in titles, (provider, heading)
        assert "Not available in this version" in titles


def test_the_pages_use_the_required_section_labels() -> None:
    for page_id in ("wordpress-api", "woocommerce-api"):
        text = _page_text(page_id)
        assert "**What you need to provide:**" in text
        assert "**What you get back:**" in text
        assert "**Endpoint:**" in text


# -- Exclusions are explained in human language --------------------------


@pytest.mark.parametrize("reason", sorted(EXCLUSION_REASONS))
def test_every_exclusion_reason_has_a_human_explanation(reason: str) -> None:
    explanation = explain(reason)
    assert explanation
    assert len(explanation.split()) >= 8
    assert reason not in explanation


def test_each_page_explains_its_exclusions_without_showing_only_a_code() -> None:
    for provider, page_id in (("wordpress", "wordpress-api"), ("woocommerce", "woocommerce-api")):
        text = _page_text(page_id)
        reasons = {row.exclusion_reason for row in EXCLUDED_ROWS if row.provider == provider}
        for reason in reasons:
            assert explain(reason) in text, (provider, reason)
            assert reason not in text, (provider, reason)


def test_deletion_is_explained_rather_than_merely_coded() -> None:
    text = _page_text("woocommerce-api")
    assert "Deleting is unavailable in version 1.0.0" in text
    assert "destructive_delete_excluded" not in text


# -- Changelog ------------------------------------------------------------


def test_the_changelog_page_is_registered() -> None:
    manifest = _yaml("ui/ui_manifest.yaml")
    refs = [row["ref"] for row in manifest["pages"]]
    assert refs == [
        "pages/setup-guide.yaml",
        "pages/connection.yaml",
        "pages/wordpress-api.yaml",
        "pages/woocommerce-api.yaml",
        "pages/changelog.yaml",
    ]
    page = _yaml("ui/pages/changelog.yaml")
    assert page["page_id"] == "changelog"
    assert page["title"] == "Changelog"


def test_the_changelog_file_documents_the_current_version() -> None:
    manifest = _yaml("extension.yaml")
    changelog = (BUNDLE_ROOT / "CHANGELOG.md").read_text()
    assert f"## {manifest['version']}" in changelog
    assert f"## {INITIAL_VERSION}" in changelog


def test_the_initial_entry_summarises_the_release() -> None:
    changelog = (BUNDLE_ROOT / "CHANGELOG.md").read_text()
    wordpress = len([row for row in REST_OPERATIONS if row.provider == "wordpress"])
    woocommerce = len([row for row in REST_OPERATIONS if row.provider == "woocommerce"])

    assert f"{wordpress} operations" in changelog
    assert f"{woocommerce} operations" in changelog
    assert "/wp/v2" in changelog
    assert "/wc/v3" in changelog
    assert "Consumer Secret" in changelog
    assert "Intentionally not included" in changelog
    assert "Every HTTP `DELETE`" in changelog
    assert "### Added" in changelog
    assert "### Security" in changelog


def test_the_changelog_style_example_pairs_capability_with_endpoint() -> None:
    changelog = (BUNDLE_ROOT / "CHANGELOG.md").read_text()
    assert "Added the ability to retrieve refunds for an order." in changelog
    assert "`GET /orders/{id}/refunds`" in changelog
    for section in ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"):
        assert f"**{section}**" in changelog or f"### {section}" in changelog


def test_the_changelog_page_renders_the_changelog_file() -> None:
    page_text = _page_text("changelog")
    changelog = (BUNDLE_ROOT / "CHANGELOG.md").read_text()
    for marker in ("## 1.0.0", "First release.", "Intentionally not included"):
        assert marker in page_text
        assert marker in changelog


def test_the_readme_points_at_every_page() -> None:
    readme = (BUNDLE_ROOT / "README.md").read_text()
    for page in ("Setup Guide", "Connection", "WordPress API", "WooCommerce API", "Changelog"):
        assert page in readme
    assert "CHANGELOG.md" in readme


# -- Coverage stays explained --------------------------------------------


def test_the_refund_preview_is_documented_as_supported_and_non_destructive() -> None:
    doc = OPERATION_DOCS["wc_preview_order_refund"]
    assert "without creating" in doc.summary
    assert "No refund is created" in doc.important
    supported = {row.operation_id for row in coverage_rows() if row.coverage_status == "supported"}
    assert "wc_preview_order_refund" in supported


def test_no_two_operations_share_a_title() -> None:
    """A duplicated title makes two different operations indistinguishable.

    The builder lists operations by title alone, so a collision leaves the
    author guessing which of the two they picked. Four WordPress endpoints
    return their whole set as one keyed object, which gives them the same
    ``get`` shape — and so the same generated title — as the single-record
    endpoint beside them.
    """
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for operation_id, doc in OPERATION_DOCS.items():
        previous = seen.get(doc.title)
        if previous is not None:
            collisions.append((doc.title, previous, operation_id))
        seen[doc.title] = operation_id
    assert collisions == []


def test_every_operation_title_reads_as_a_human_action() -> None:
    """Titles are what the builder shows, so none of them may be an identifier."""
    for operation_id, doc in OPERATION_DOCS.items():
        assert doc.title, operation_id
        assert "_" not in doc.title, f"{operation_id} shows a technical name: {doc.title}"
        assert doc.title[0].isupper(), f"{operation_id} title is not a sentence: {doc.title}"
