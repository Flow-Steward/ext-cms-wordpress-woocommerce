"""Pagination normalization from native WordPress and WooCommerce headers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MAX_LINK_HEADER_BYTES = 8192
MAX_LINK_URL_LENGTH = 2048
_LINK_ENTRY_RE = re.compile(r'<([^>]{1,2048})>\s*;\s*rel\s*=\s*"?([A-Za-z]{1,32})"?')


def _header(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            return str(getter(name) or "").strip()
        except Exception:  # pragma: no cover - defensive against odd header objects
            return ""
    if isinstance(headers, Mapping):
        return str(headers.get(name) or "").strip()
    return ""


def _bounded_int(value: str) -> int | None:
    text = value.strip()
    if not text or len(text) > 12 or not text.isdigit():
        return None
    return int(text)


def parse_link_header(raw: str) -> dict[str, str]:
    """Return the ``rel`` targets of a bounded RFC 5988 ``Link`` header."""
    text = str(raw or "")
    if not text or len(text.encode("utf-8", "ignore")) > MAX_LINK_HEADER_BYTES:
        return {}
    links: dict[str, str] = {}
    for target, rel in _LINK_ENTRY_RE.findall(text):
        url = target.strip()
        relation = rel.strip().lower()
        if not url or len(url) > MAX_LINK_URL_LENGTH or relation in links:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        links[relation] = url
    return links


def pagination_from_headers(
    headers: Any, *, page: int | None = None, per_page: int | None = None
) -> dict[str, Any]:
    """Normalize ``X-WP-Total``, ``X-WP-TotalPages``, and ``Link`` into one shape."""
    total = _bounded_int(_header(headers, "X-WP-Total"))
    total_pages = _bounded_int(_header(headers, "X-WP-TotalPages"))
    links = parse_link_header(_header(headers, "Link"))
    next_link = links.get("next") or None
    previous_link = links.get("prev") or links.get("previous") or None
    if total_pages is not None and page is not None:
        has_more = page < total_pages
    else:
        has_more = next_link is not None
    return {
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "per_page": per_page,
        "next_link": next_link,
        "previous_link": previous_link,
        "has_more": bool(has_more),
    }


__all__ = ["pagination_from_headers", "parse_link_header"]
