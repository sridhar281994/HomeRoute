from __future__ import annotations

import os
from io import BytesIO
from typing import Any

import cloudinary.uploader

# Ensure global config is applied on import.
from app.utils import cloudinary_config  # noqa: F401


def cloudinary_enabled() -> bool:
    """
    Cloudinary is enabled when the required env vars exist.
    """
    return bool(
        (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
        and (os.getenv("CLOUDINARY_API_KEY") or "").strip()
        and (os.getenv("CLOUDINARY_API_SECRET") or "").strip()
    )


def cloudinary_upload_bytes(
    *,
    raw: bytes,
    filename: str,
    content_type: str,
    folder: str,
    resource_type: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Upload raw bytes to Cloudinary and return the full Cloudinary response.

    - `resource_type`: "image" | "video" | "raw"
    """
    bio = BytesIO(raw)
    # Cloudinary inspects the file object's name to infer extension in some cases.
    try:
        setattr(bio, "name", str(filename or "upload.bin"))
    except Exception:
        pass

    opts: dict[str, Any] = {
        "resource_type": str(resource_type or "raw"),
        "folder": str(folder or "").strip().strip("/"),
        # Keep original filename in Cloudinary metadata for debugging.
        "use_filename": True,
        "unique_filename": True,
        "overwrite": False,
    }
    ct = str(content_type or "").strip().lower()
    if ct:
        # Helps Cloudinary when the stream has no filename.
        opts["content_type"] = ct
    if tags:
        opts["tags"] = list(tags)

    return dict(cloudinary.uploader.upload(bio, **opts))

