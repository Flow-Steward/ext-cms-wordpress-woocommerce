"""The media artifact bridge: native multipart upload, and nothing else."""

from __future__ import annotations

import pytest
from conftest import connection_payload, json_response
from runtime import errors
from runtime.media import MEDIA_BINDING_KEY
from runtime.operations import handle_runtime

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 10


def _payload(operation_input: dict, *, artifact_plane: dict | None = None) -> dict:
    payload = connection_payload("wp_create_media", operation_input)
    if artifact_plane is not None:
        payload.update(artifact_plane)
    return payload


def _grant(content: bytes = PNG, *, binding_key: str = MEDIA_BINDING_KEY) -> dict:
    return {
        "artifacts": {
            "inputs": [
                {
                    "artifact_id": "artifact-1",
                    "artifact_handle": "artifact-1",
                    "binding_key": binding_key,
                    "role": "input",
                    "content_type": "image/png",
                    "size_bytes": len(content),
                    "access": {
                        "transport": "presigned_url",
                        "mode": "read",
                        "download_url": "https://artifacts.example.test/artifact-1",
                        "max_size_bytes": 67108864,
                    },
                }
            ]
        }
    }


def _streamer(content: bytes = PNG):
    return lambda *_args, **_kwargs: iter([content])


def test_a_missing_artifact_grant_is_reported_safely(http, transport_factory) -> None:
    response = handle_runtime(
        _payload({"artifact_handle": "artifact-1", "filename": "photo.png"}),
        transport_factory=transport_factory,
    )
    assert response["ok"] is False
    assert response["error_code"] == errors.ARTIFACT_INPUT_UNAVAILABLE
    assert http.requests == []


def test_a_grant_under_the_wrong_binding_key_is_refused(http, transport_factory) -> None:
    response = handle_runtime(
        _payload(
            {"artifact_handle": "artifact-1", "filename": "photo.png"},
            artifact_plane=_grant(binding_key="some_other_binding"),
        ),
        transport_factory=transport_factory,
    )
    assert response["error_code"] == errors.ARTIFACT_INPUT_UNAVAILABLE
    assert http.requests == []


@pytest.mark.parametrize("name", ["", ".", "..", "a/b.png", "a\\b.png", " leading.png", "x" * 300])
def test_unsafe_filenames_are_refused_before_io(http, transport_factory, name: str) -> None:
    response = handle_runtime(
        _payload({"artifact_handle": "artifact-1", "filename": name}),
        transport_factory=transport_factory,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_an_invalid_content_type_is_refused(http, transport_factory) -> None:
    response = handle_runtime(
        _payload(
            {
                "artifact_handle": "artifact-1",
                "filename": "photo.png",
                "content_type": "not a media type",
            }
        ),
        transport_factory=transport_factory,
    )
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_the_upload_is_one_native_multipart_post(http, transport_factory) -> None:
    http.queue(json_response({"id": 501, "source_url": "https://shop.example/x.png"}, status=201))
    response = handle_runtime(
        _payload(
            {
                "artifact_handle": "artifact-1",
                "filename": "photo.png",
                "title": "Spring photo",
                "alt_text": "A flower",
            },
            artifact_plane=_grant(),
        ),
        transport_factory=transport_factory,
        artifact_streamer=_streamer(),
    )

    assert response["ok"] is True
    assert response["external_effect_status"] == "succeeded"
    assert response["result"]["data"]["id"] == 501
    assert len(http.requests) == 1

    request = http.last
    assert request["method"] == "POST"
    assert request["url"] == "https://shop.example/wp-json/wp/v2/media"
    assert request["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    body = request["body"]
    assert b'name="file"; filename="photo.png"' in body
    assert b"Content-Type: image/png" in body
    assert b'name="title"' in body
    assert b"Spring photo" in body
    assert b'name="alt_text"' in body
    assert b"A flower" in body
    assert PNG in body
    assert int(request["headers"]["content-length"]) == len(body)


def test_the_declared_content_type_overrides_the_artifact_default(http, transport_factory) -> None:
    http.queue(json_response({"id": 1}, status=201))
    handle_runtime(
        _payload(
            {
                "artifact_handle": "artifact-1",
                "filename": "notes.pdf",
                "content_type": "application/pdf",
            },
            artifact_plane=_grant(),
        ),
        transport_factory=transport_factory,
        artifact_streamer=_streamer(),
    )
    assert b"Content-Type: application/pdf" in http.last["body"]


def test_media_is_the_only_operation_that_takes_an_artifact() -> None:
    from runtime.catalog import REST_OPERATIONS
    from runtime.io_shapes import input_field_names

    with_artifacts = [
        row.operation_id for row in REST_OPERATIONS if "artifact_handle" in input_field_names(row)
    ]
    assert with_artifacts == ["wp_create_media"]
