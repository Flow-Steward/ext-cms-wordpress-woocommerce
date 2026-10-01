"""Artifact bridge for the native WordPress media endpoint.

The only reason an artifact handle appears anywhere in this extension is that
``POST /wp-json/wp/v2/media`` takes a file body. Nothing here optimizes,
enriches, translates, generates, or synchronizes media: the bytes the caller
already staged are streamed straight into the native endpoint.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from flowsteward_extension_sdk import (
    ArtifactAccessError,
    find_artifact_descriptor,
    stream_artifact_bytes,
)

from . import errors
from .errors import ExtensionError
from .transport import MAX_UPLOAD_BYTES

MEDIA_BINDING_KEY = "wordpress_media_artifact"
CHUNK_BYTES = 1024 * 1024
STREAM_TIMEOUT_SECONDS = 30.0


def media_upload_source(
    payload: Mapping[str, Any],
    artifact_handle: str,
    *,
    artifact_streamer: Callable[..., Iterable[bytes]] = stream_artifact_bytes,
) -> tuple[Iterator[bytes], int, str]:
    """Resolve the declared input artifact grant into a bounded byte stream."""
    try:
        descriptor = find_artifact_descriptor(
            payload,
            artifact_id=artifact_handle,
            binding_key=MEDIA_BINDING_KEY,
            role="input",
        )
        access = descriptor.get("access")
        size = descriptor.get("size_bytes")
        max_size = access.get("max_size_bytes") if isinstance(access, Mapping) else None
        if (
            descriptor.get("role") != "input"
            or descriptor.get("binding_key") != MEDIA_BINDING_KEY
            or not isinstance(access, Mapping)
            or access.get("transport") != "presigned_url"
            or access.get("mode") not in {"read", "read_write"}
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or isinstance(max_size, bool)
            or not isinstance(max_size, int)
            or max_size <= 0
            or size > max_size
        ):
            raise ArtifactAccessError("invalid input grant")
        if size > MAX_UPLOAD_BYTES:
            raise ExtensionError(errors.INVALID_PAYLOAD, "The media upload exceeds its safe limit")
        descriptor_content_type = descriptor.get("content_type")
        content_type = (
            descriptor_content_type
            if isinstance(descriptor_content_type, str) and 3 <= len(descriptor_content_type) <= 255
            else ""
        )
        stream = artifact_streamer(
            payload,
            artifact_id=artifact_handle,
            binding_key=MEDIA_BINDING_KEY,
            chunk_size=CHUNK_BYTES,
            timeout_seconds=STREAM_TIMEOUT_SECONDS,
        )
        return iter(stream), size, content_type
    except ExtensionError:
        raise
    except ArtifactAccessError as exc:
        raise ExtensionError(
            errors.ARTIFACT_INPUT_UNAVAILABLE, "The input artifact grant is unavailable"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive around the SDK boundary
        raise ExtensionError(
            errors.ARTIFACT_INPUT_UNAVAILABLE, "The input artifact grant is unavailable"
        ) from exc


__all__ = ["MEDIA_BINDING_KEY", "media_upload_source"]
