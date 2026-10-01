"""Health command for the WordPress & WooCommerce extension."""

from __future__ import annotations

import json


def check_health() -> dict[str, object]:
    from runtime.catalog import REST_OPERATIONS

    return {
        "extension_id": "flowsteward.wordpress-woocommerce",
        "ok": True,
        "status": "healthy",
        "declared_operations": len(REST_OPERATIONS) + 1,
    }


if __name__ == "__main__":
    print(json.dumps(check_health(), separators=(",", ":"), sort_keys=True))
