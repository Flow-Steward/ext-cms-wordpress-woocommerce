#!/usr/bin/env python3
"""Read the markers the official references use inside a field description.

Both providers state a field's obligations in prose rather than in a structured
flag, and they use different conventions: WordPress appends ``Required: 1`` and
WooCommerce appends ``MANDATORY``. Reading them by hand at each call site is how
a marker gets missed on one provider and a piece of ordinary prose gets mistaken
for one on the other, so every reader goes through this module.

The rules are deliberately strict about what counts. ``Required to be true`` is
the commonest sentence in both references and says something about a field's
*value*, not about whether the field must be supplied — it is not a marker, and
a test pins that.
"""

from __future__ import annotations

import re

#: WordPress: ``Required: 1`` at the end of an argument description. Spacing and
#: capitalisation vary across pages, so both are tolerated.
_WORDPRESS_REQUIRED_RE = re.compile(r"\brequired\s*:\s*1\b", re.IGNORECASE)

#: WooCommerce: a standalone uppercase ``MANDATORY`` tag. Matched case-sensitively
#: because the lowercase word appears in ordinary prose.
_WOOCOMMERCE_MANDATORY_RE = re.compile(r"(?<![A-Za-z])MANDATORY(?![A-Za-z])")

#: WooCommerce marks a field it accepts but never returns as ``WRITE-ONLY``.
_WRITE_ONLY_RE = re.compile(r"(?<![A-Za-z])WRITE-ONLY(?![A-Za-z])")

#: WordPress says a property is ``never included`` in a response.
_NEVER_INCLUDED_RE = re.compile(r"\bnever\s+included\b", re.IGNORECASE)


def is_required(description: str) -> bool:
    """True when the description carries either provider's required marker."""
    text = str(description or "")
    return bool(_WORDPRESS_REQUIRED_RE.search(text) or _WOOCOMMERCE_MANDATORY_RE.search(text))


def is_write_only(description: str) -> bool:
    """True when WooCommerce documents the field as accepted but never returned."""
    return bool(_WRITE_ONLY_RE.search(str(description or "")))


def is_never_included(description: str) -> bool:
    """True when WordPress documents the property as never present in a response."""
    return bool(_NEVER_INCLUDED_RE.search(str(description or "")))


def is_response_suppressed(description: str) -> bool:
    """True when either provider says the field does not appear in a response."""
    text = str(description or "")
    return is_write_only(text) or is_never_included(text)


__all__ = [
    "is_never_included",
    "is_required",
    "is_response_suppressed",
    "is_write_only",
]
