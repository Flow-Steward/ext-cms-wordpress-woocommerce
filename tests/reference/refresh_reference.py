#!/usr/bin/env python3
"""Re-extract the official WordPress and WooCommerce parameter reference.

This is the reproducible half of the coverage and typing proof. It fetches every
official reference page, extracts the documented routes, resource schemas, and
per-endpoint parameter tables, and writes them to
``contracts/rest_reference.yaml``. The extension-owned tests then check the
typed runtime tables against that committed snapshot, so the suite proves
conformance to the published documentation without needing network access.

    python tests/reference/refresh_reference.py            # rewrite the snapshot
    python tests/reference/refresh_reference.py --check    # fail if it drifted

Run it from the bundle root. It is never imported by the runtime.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = BUNDLE_ROOT / "contracts" / "rest_reference.yaml"

WORDPRESS_BASE = "https://developer.wordpress.org/rest-api/reference/"
WOOCOMMERCE_BASE = "https://developer.woocommerce.com/docs/apis/rest-api/v3/"

WORDPRESS_SLUGS: tuple[str, ...] = (
    "application-passwords",
    "block-directory-items",
    "block-pattern-categories",
    "block-patterns",
    "block-revisions",
    "block-types",
    "blocks",
    "categories",
    "comments",
    "media",
    "menu-locations",
    "page-revisions",
    "pages",
    "pattern-directory-items",
    "plugins",
    "post-revisions",
    "post-statuses",
    "post-types",
    "posts",
    "rendered-blocks",
    "search-results",
    "settings",
    "sidebars",
    "tags",
    "taxonomies",
    "themes",
    "users",
    "widget-types",
    "widgets",
    "wp-site-health-tests",
)
WOOCOMMERCE_SLUGS: tuple[str, ...] = (
    "coupons",
    "customers",
    "orders",
    "order-actions",
    "order-notes",
    "order-refunds",
    "products",
    "product-variations",
    "product-attributes",
    "product-attribute-terms",
    "product-categories",
    "product-custom-fields",
    "product-shipping-classes",
    "product-tags",
    "product-reviews",
    "reports",
    "refunds",
    "taxes",
    "tax-classes",
    "webhooks",
    "settings",
    "setting-options",
    "payment-gateways",
    "shipping-zones",
    "shipping-zone-locations",
    "shipping-zone-methods",
    "shipping-methods",
    "system-status",
    "system-status-tools",
    "data",
)

_ROUTE_RE = re.compile(
    r"^(GET|POST|PUT|PATCH|DELETE)\s+(?:/wp-json)?(/(?:wp/v2|wc/v3|wp-site-health/v1)\S*)"
)
_TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def _text(fragment: str) -> str:
    """Collapse a markup fragment to plain text, dropping anchor zero-width joiners."""
    plain = html.unescape(_TAG_RE.sub(" ", fragment)).replace("\u200b", "")
    return " ".join(plain.split())


def _codes(fragment: str) -> list[str]:
    return [_text(value) for value in re.findall(r"<code[^>]*>(.*?)</code>", fragment, re.S)]


def _first_code(match: re.Match[str] | None) -> str | None:
    """First <code> value in a matched fragment, or None when there is none."""
    if match is None:
        return None
    values = _codes(match.group(1))
    if values:
        return values[0]
    plain = _text(match.group(1)).strip().rstrip(".")
    return plain or None


def _routes(page: str) -> list[list[str]]:
    found: list[list[str]] = []
    for match in re.finditer(r"<code[^>]*>(.*?)</code>|<pre[^>]*>(.*?)</pre>", page, re.S):
        block = html.unescape(_TAG_RE.sub("", match.group(1) or match.group(2) or ""))
        for line in block.splitlines():
            route_match = _ROUTE_RE.match(" ".join(line.split()))
            if route_match:
                # The reference embeds route-regex fragments in its path
                # parameters (``<plugin>?)``, ``<user_id>)``). Drop them.
                route = route_match.group(2).replace("?)", "").replace(")", "")
                entry = [route_match.group(1), route]
                if entry not in found:
                    found.append(entry)
    return found


# ------------------------------------------------------------- WordPress


def _wordpress_schema(page: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for table in re.findall(r'<table class="attributes">(.*?)</table>', page, re.S):
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            names = _codes(row)
            if not names:
                continue
            type_match = re.search(r"JSON data type:\s*([^<,]+)", row)
            context_match = re.search(r'<p class="context">(.*?)</p>', row, re.S)
            contexts = _codes(context_match.group(1)) if context_match else []
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            raw_description = cells[1] if len(cells) > 1 else ""
            description = _text(
                re.sub(
                    r'<p class="(?:type|context|default)">.*?</p>', "", raw_description, flags=re.S
                )
            )
            fields.append(
                {
                    "name": names[0],
                    "description": description,
                    "json_type": _text(type_match.group(1)) if type_match else "",
                    "contexts": contexts,
                    "read_only": "readonly" in _text(row).lower(),
                }
            )
    return fields


def _wordpress_sections(page: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    headings = [
        (match.start(), _text(match.group(1)))
        for match in re.finditer(r'<h2 id="[^"]*"[^>]*>(.*?)</h2>', page, re.S)
    ]
    for table_match in re.finditer(r'<table class="arguments">(.*?)</table>', page, re.S):
        heading = ""
        for position, title in headings:
            if position < table_match.start():
                heading = title
        arguments: list[dict[str, Any]] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_match.group(1), re.S):
            names = _codes(row)
            if not names:
                continue
            default_match = re.search(r'<p class="default">\s*Default:\s*(.*?)</p>', row, re.S)
            options_match = re.search(r"One of:\s*(.*?)(?:</p>|</td>)", row, re.S)
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            arguments.append(
                {
                    "name": names[0],
                    "description": _text(cells[1]) if len(cells) > 1 else "",
                    "default": _first_code(default_match),
                    "options": _codes(options_match.group(1)) if options_match else [],
                }
            )
        if arguments:
            sections.append({"heading": heading, "fields": arguments})
    return sections


# ----------------------------------------------------------- WooCommerce

_PIPE_ROW_RE = re.compile(r"\|\s*<code[^>]*>(.*?)</code>\s*\|\s*([A-Za-z\- ]+?)\s*\|(.*?)\|", re.S)


def _markdown_pipe_tables(page: str) -> list[dict[str, Any]]:
    """Recover an properties table the docs failed to render out of Markdown."""
    tables: list[dict[str, Any]] = []
    headings = [
        (match.start(), _text(match.group(1)))
        for match in re.finditer(r"<h[23456][^>]*>(.*?)</h[23456]>", page, re.S)
    ]
    for block in re.finditer(r"<p>(.*?)</p>", page, re.S):
        raw = block.group(1)
        if "| Attribute | Type | Description |" not in _text(raw):
            continue
        rows: list[dict[str, Any]] = []
        for name_html, type_text, description_html in _PIPE_ROW_RE.findall(raw):
            name = _text(name_html)
            if not name or name.lower() == "attribute":
                continue
            description = _text(description_html)
            options_match = re.search(r"Options:\s*(.*?)(?:\.\s|\.$|$)", description_html, re.S)
            default_match = re.search(r"Default is\s*(.*?)(?:\.|$)", description_html, re.S)
            rows.append(
                {
                    "name": name,
                    "description": description,
                    "type": _text(type_text),
                    "options": [
                        value
                        for value in (_codes(options_match.group(1)) if options_match else [])
                        if value not in {"", "and", "or"}
                    ],
                    "default": _first_code(default_match),
                    "read_only": "READ-ONLY" in description,
                    "mandatory": "MANDATORY" in description,
                }
            )
        if not rows:
            continue
        heading = ""
        for position, title in headings:
            if position < block.start():
                heading = title
        tables.append({"heading": heading, "fields": rows})
    return tables


def _woocommerce_tables(page: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    properties: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    headings = [
        (match.start(), _text(match.group(1)))
        for match in re.finditer(r"<h[23456][^>]*>(.*?)</h[23456]>", page, re.S)
    ]
    for table_match in re.finditer(r"<table>(.*?)</table>", page, re.S):
        table = table_match.group(1)
        head_match = re.search(r"<thead>(.*?)</thead>", table, re.S)
        header = _text(head_match.group(1)) if head_match else ""
        if not header.startswith(("Attribute Type", "Parameter Type")):
            continue
        rows: list[dict[str, Any]] = []
        body = re.search(r"<tbody>(.*?)</tbody>", table, re.S)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else table, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 3:
                continue
            names = _codes(cells[0])
            if not names:
                continue
            description = _text(cells[2])
            options_match = re.search(r"Options:\s*(.*?)(?:\.\s|\.$|$)", cells[2], re.S)
            default_match = re.search(r"Default is\s*(.*?)(?:\.|$)", cells[2], re.S)
            rows.append(
                {
                    "name": names[0],
                    "description": description,
                    "type": _text(cells[1]),
                    "options": [
                        value
                        for value in (_codes(options_match.group(1)) if options_match else [])
                        if value not in {"", "and", "or"}
                    ],
                    "default": _first_code(default_match),
                    "read_only": "READ-ONLY" in description,
                    "mandatory": "MANDATORY" in description,
                }
            )
        if not rows:
            continue
        heading = ""
        for position, title in headings:
            if position < table_match.start() and not title.lower().startswith(
                ("available parameters", "parameters")
            ):
                heading = title
        if header.startswith("Attribute Type"):
            properties.append({"heading": heading, "fields": rows})
        else:
            sections.append({"heading": heading, "fields": rows})
    if not properties:
        properties = _markdown_pipe_tables(page)
    return properties, sections


# ----------------------------------------------------------------- driver


def extract() -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for slug in WORDPRESS_SLUGS:
        url = f"{WORDPRESS_BASE}{slug}/"
        page = fetch(url)
        pages.append(
            {
                "provider": "wordpress",
                "slug": slug,
                "url": url,
                "routes": _routes(page),
                "schema": _wordpress_schema(page),
                "sections": _wordpress_sections(page),
            }
        )
    for slug in WOOCOMMERCE_SLUGS:
        url = f"{WOOCOMMERCE_BASE}{slug}/"
        page = fetch(url)
        properties, sections = _woocommerce_tables(page)
        pages.append(
            {
                "provider": "woocommerce",
                "slug": slug,
                "url": url,
                "routes": _routes(page),
                "properties": properties,
                "sections": sections,
            }
        )
    return {"schema": "flow-steward.wordpress-woocommerce.reference.v1", "pages": pages}


def _dump(payload: dict[str, Any]) -> str:
    import yaml

    return (
        "# Extracted from the official WordPress and WooCommerce REST references by\n"
        "# tests/reference/refresh_reference.py. Do not edit by hand.\n"
        + yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=100)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = _dump(extract())
    if arguments.check:
        current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.is_file() else ""
        if current != rendered:
            print("contracts/rest_reference.yaml is out of date", file=sys.stderr)
            return 1
        print(json.dumps({"status": "current", "snapshot": str(SNAPSHOT)}))
        return 0
    SNAPSHOT.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": "written", "snapshot": str(SNAPSHOT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
