from __future__ import annotations

import json

from conftest import WOO_CREDENTIALS, connection_payload, json_response
from runtime import errors
from runtime.operations import handle_runtime


def test_export_products_reads_every_page_and_writes_one_jsonl_artifact(
    http, transport_factory
) -> None:
    http.queue(
        json_response(
            [{"id": 1, "name": "One", "post_password": "provider-only"}, {"id": 2}],
            headers={"X-WP-Total": "5", "X-WP-TotalPages": "3"},
        ),
        json_response(
            [{"id": 3}, {"id": 4}],
            headers={"X-WP-Total": "5", "X-WP-TotalPages": "3"},
        ),
        json_response(
            [{"id": 5}],
            headers={"X-WP-Total": "5", "X-WP-TotalPages": "3"},
        ),
    )
    written: list[bytes] = []

    def artifact_writer(payload, chunks, **kwargs):
        body = b"".join(chunks)
        written.append(body)
        return {
            "artifact_handle": "artifact:catalog",
            "size_bytes": len(body),
            "sha256": "sha256-value",
        }

    response = handle_runtime(
        connection_payload(
            "wc_export_products",
            {"status": "publish", "per_page": 2},
            **WOO_CREDENTIALS,
        ),
        transport_factory=transport_factory,
        artifact_writer=artifact_writer,
    )

    assert response["ok"] is True
    assert response["result"] == {
        "artifact_handle": "artifact:catalog",
        "filename": "woocommerce-products.jsonl",
        "content_type": "application/x-ndjson",
        "item_count": 5,
        "page_count": 3,
        "total_reported": 5,
        "size_bytes": len(written[0]),
        "sha256": "sha256-value",
        "artifacts": {
            "woocommerce-products.jsonl": {
                "artifact_handle": "artifact:catalog",
                "mime_type": "application/x-ndjson",
                "size_bytes": len(written[0]),
                "sha256": "sha256-value",
            }
        },
    }
    rows = [json.loads(line) for line in written[0].splitlines()]
    assert [row["id"] for row in rows] == [1, 2, 3, 4, 5]
    assert "post_password" not in rows[0]
    assert [request["url"] for request in http.requests] == [
        "https://shop.example/wp-json/wc/v3/products?page=1&per_page=2&status=publish&order=asc&orderby=id",
        "https://shop.example/wp-json/wc/v3/products?page=2&per_page=2&status=publish&order=asc&orderby=id",
        "https://shop.example/wp-json/wc/v3/products?page=3&per_page=2&status=publish&order=asc&orderby=id",
    ]


def test_export_products_refuses_partial_page_controls_before_outbound_io(
    http, transport_factory
) -> None:
    response = handle_runtime(
        connection_payload("wc_export_products", {"page": 2}, **WOO_CREDENTIALS),
        transport_factory=transport_factory,
        artifact_writer=lambda *_args, **_kwargs: {},
    )

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_export_products_normalizes_artifact_write_failure(http, transport_factory) -> None:
    http.queue(
        json_response(
            [{"id": 1}],
            headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"},
        )
    )

    def failed_writer(*_args, **_kwargs):
        raise RuntimeError("storage internals must not escape")

    response = handle_runtime(
        connection_payload("wc_export_products", {}, **WOO_CREDENTIALS),
        transport_factory=transport_factory,
        artifact_writer=failed_writer,
    )

    assert response["ok"] is False
    assert response["error_code"] == errors.ARTIFACT_OUTPUT_UNAVAILABLE
    assert response["error"] == "The product catalog artifact could not be saved"
