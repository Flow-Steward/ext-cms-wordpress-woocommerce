#!/usr/bin/env python3
"""Render the WordPress API and WooCommerce API pages from the operation metadata.

The pages are not written by hand: every heading, explanation and endpoint comes
from ``runtime/descriptions.py`` and ``runtime/coverage.py``, which are the same
sources the workflow-builder action descriptions come from. That is what keeps
the two surfaces from drifting apart.

    python tests/reference/build_ui_pages.py            # rewrite the pages
    python tests/reference/build_ui_pages.py --check    # fail if they drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BUNDLE_ROOT))

from runtime.catalog import REST_OPERATIONS, WOOCOMMERCE, WORDPRESS  # noqa: E402
from runtime.coverage import (  # noqa: E402
    EXCLUDED_ROWS,
    STATUS_NOT_DOCUMENTED,
    explain,
)
from runtime.descriptions import (  # noqa: E402
    OPERATION_DOCS,
    RESOURCE_GROUPS,
    resource_heading,
)

PAGES = {
    WORDPRESS: {
        "path": BUNDLE_ROOT / "ui" / "pages" / "wordpress-api.yaml",
        "page_id": "wordpress-api",
        "title": "WordPress API",
        "description": "What this extension can do with WordPress, and what each operation needs.",
        "reference": "https://developer.wordpress.org/rest-api/reference/",
        "namespace": "/wp/v2",
        "intro": (
            "Every operation below is fixed in advance and typed against the official WordPress "
            "REST reference. Nothing is discovered from your site, so a custom post type, a custom "
            "taxonomy, a custom route or a plugin field never appears here, and there is no "
            "general-purpose request action.\n\nEndpoints are shown relative to your site URL."
        ),
    },
    WOOCOMMERCE: {
        "path": BUNDLE_ROOT / "ui" / "pages" / "woocommerce-api.yaml",
        "page_id": "woocommerce-api",
        "title": "WooCommerce API",
        "description": "What this extension can do with your WooCommerce store, and what each operation needs.",
        "reference": "https://developer.woocommerce.com/docs/apis/rest-api/v3/",
        "namespace": "/wc/v3",
        "intro": (
            "Every operation below is fixed in advance and typed against the official WooCommerce "
            "REST API v3 reference. Nothing is discovered from your store, and there is no "
            "general-purpose request action.\n\n"
            "Endpoints are shown relative to your site URL. These operations need the WooCommerce "
            "Consumer Key and Consumer Secret on the connection."
        ),
    },
}

INDENT = "      "


def _block(lines: list[str]) -> str:
    """Indent a markdown body into a YAML block scalar.

    Elements may themselves contain newlines, so split before indenting or the
    continuation lines land at column zero and break the document.
    """
    flattened: list[str] = []
    for line in lines:
        flattened.extend(str(line).split("\n"))
    return "\n".join(f"{INDENT}{line}".rstrip() for line in flattened)


def _operation_markdown(operation_id: str) -> list[str]:
    doc = OPERATION_DOCS[operation_id]
    lines = [
        f"### {doc.title}",
        "",
        doc.summary,
        "",
        f"- **Endpoint:** `{doc.endpoint}`",
        f"- **What you need to provide:** {doc.provides}",
        f"- **What you get back:** {doc.returns}",
    ]
    if doc.important:
        lines.append(f"- **Important:** {doc.important}")
    lines.append("")
    return lines


def _group_component(provider: str, heading: str, resources: list[str]) -> list[str]:
    by_resource: dict[str, list[str]] = {}
    for row in REST_OPERATIONS:
        if row.provider == provider:
            by_resource.setdefault(row.resource, []).append(row.operation_id)

    body: list[str] = []
    for resource in resources:
        operation_ids = by_resource.get(resource, [])
        if not operation_ids:
            continue
        body.append(f"## {resource_heading(resource)}")
        body.append("")
        for operation_id in operation_ids:
            body.extend(_operation_markdown(operation_id))
    component_id = f"{provider}_api_{heading.lower().replace(' ', '_').replace(',', '')}"
    return [
        f"  - component_id: {component_id}",
        "    type: markdown",
        f"    title: {heading}",
        "    body: |",
        _block(body),
    ]


#: Reader-facing heading for each exclusion reason.
REASON_HEADINGS = {
    "destructive_delete_excluded": "Deleting records",
    "plugin_lifecycle_excluded": "Installing or changing plugins",
    "theme_lifecycle_excluded": "Installing or changing themes",
    "application_password_management_excluded": "Managing Application Passwords",  # pragma: allowlist secret
    "refund_mutation_excluded": "Creating or changing refunds",
    "system_status_tool_execution_excluded": "Running system status tools",
    "batch_delete_payload_excluded": "Deleting through a batch request",
    "namespace_outside_wp_v2": "Routes outside the covered namespaces",
    "not_officially_documented": "Resources with no official reference page",
    "identity_lifecycle_automation_excluded": "Creating or changing user accounts",
    "webhook_administration_excluded": "Adding or changing WooCommerce webhooks",
}


def _excluded_component(provider: str) -> list[str]:
    """Group the exclusions by reason, so each explanation is stated once."""
    grouped: dict[str, list[str]] = {}
    for row in EXCLUDED_ROWS:
        if row.provider != provider:
            continue
        entry = grouped.setdefault(row.exclusion_reason, [])
        heading = resource_heading(row.resource)
        if row.coverage_status == STATUS_NOT_DOCUMENTED and not row.route_pattern:
            label = heading
        else:
            route = row.route_pattern.replace("/wp-json", "")
            label = f"`{row.method} {route}`"
        if label not in entry:
            entry.append(label)

    body = [
        "These are excluded by design, not missing by accident. The technical inventory with one "
        "row per route is in `contracts/rest_coverage.yaml`.",
        "",
    ]
    for reason, labels in grouped.items():
        body.append(f"### {REASON_HEADINGS.get(reason, reason)}")
        body.append("")
        body.append(explain(reason))
        body.append("")
        body.append(f"Affects: {', '.join(labels)}.")
        body.append("")
    while body and not body[-1].strip():
        body.pop()
    return [
        f"  - component_id: {provider}_api_unavailable",
        "    type: markdown",
        "    title: Not available in this version",
        "    body: |",
        _block(body),
    ]


def render(provider: str) -> str:
    page = PAGES[provider]
    supported = [row for row in REST_OPERATIONS if row.provider == provider]
    lines = [
        "# Generated by tests/reference/build_ui_pages.py from runtime/descriptions.py.",
        "# Do not edit by hand.",
        f"page_id: {page['page_id']}",
        f"title: {page['title']}",
        f"description: {page['description']}",
        "components:",
        f"  - component_id: {provider}_api_overview",
        "    type: markdown",
        f"    title: {len(supported)} operations available",
        "    body: |",
        _block([page["intro"], "", f"[Official {page['title']} reference]({page['reference']})"]),
    ]
    for heading, resources in RESOURCE_GROUPS[provider]:
        lines.extend(_group_component(provider, heading, resources))
    lines.extend(_excluded_component(provider))
    return "\n".join(lines) + "\n"


CHANGELOG = BUNDLE_ROOT / "CHANGELOG.md"
CHANGELOG_PAGE = BUNDLE_ROOT / "ui" / "pages" / "changelog.yaml"


def render_changelog() -> str:
    """The Changelog page renders CHANGELOG.md, so the two cannot disagree."""
    body = CHANGELOG.read_text(encoding="utf-8").strip()
    # The page supplies its own heading, so drop the file's top-level title.
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return (
        "\n".join(
            [
                "# Generated by tests/reference/build_ui_pages.py from CHANGELOG.md.",
                "# Do not edit by hand.",
                "page_id: changelog",
                "title: Changelog",
                "description: What changed in each release of this extension.",
                "project_scoped: false",
                "components:",
                "  - component_id: changelog_entries",
                "    type: markdown",
                "    title: Release history",
                "    body: |",
                _block(lines),
            ]
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    drifted: list[str] = []
    for provider, page in PAGES.items():
        rendered = render(provider)
        target = Path(str(page["path"]))
        if arguments.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if current != rendered:
                drifted.append(str(page["page_id"]))
            continue
        target.write_text(rendered, encoding="utf-8")
    changelog = render_changelog()
    if arguments.check:
        current = CHANGELOG_PAGE.read_text(encoding="utf-8") if CHANGELOG_PAGE.is_file() else ""
        if current != changelog:
            drifted.append("changelog")
    else:
        CHANGELOG_PAGE.write_text(changelog, encoding="utf-8")
    if arguments.check:
        if drifted:
            print(f"API pages are out of date: {', '.join(drifted)}", file=sys.stderr)
            return 1
        print(json.dumps({"status": "current"}))
        return 0
    print(
        json.dumps(
            {
                "status": "written",
                "pages": [p["page_id"] for p in PAGES.values()] + ["changelog"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
