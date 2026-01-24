from __future__ import annotations

import os
from io import BytesIO
from typing import Literal

import cloudinary.uploader

from app.utils.cloudinary_config import cloudinary_is_configured  # ensures cloudinary.config() runs


ResourceType = Literal["image", "video"]


def _cloudinary_folder() -> str:
    # Optional folder to keep assets organized in Cloudinary.
    return (os.getenv("CLOUDINARY_FOLDER") or "quickrent4u").strip() or "quickrent4u"


def cloudinary_enabled() -> bool:
    """
    Cloudinary is enabled iff credentials are present.
    Keeps local /uploads behavior for dev environments without env vars.
    """
    return cloudinary_is_configured()


def upload_bytes(*, raw: bytes, resource_type: ResourceType, public_id: str, filename: str, content_type: str) -> tuple[str, str]:
    """
    Upload raw bytes to Cloudinary.

    Returns: (secure_url, public_id)
    """
    # Cloudinary's python SDK accepts file-like objects.
    f = BytesIO(raw)
    res = cloudinary.uploader.upload(
        f,
        resource_type=resource_type,
        folder=_cloudinary_folder(),
        public_id=public_id,
        overwrite=False,
        unique_filename=True,
        use_filename=True,
        filename_override=(filename or None),
        # Helps Cloudinary infer correctly when clients send octet-stream.
        format=None,
        type="upload",
        invalidate=False,
    )
    url = str((res or {}).get("secure_url") or "").strip()
    pid = str((res or {}).get("public_id") or public_id or "").strip()
    if not url:
        raise RuntimeError("Cloudinary upload failed (missing secure_url)")
    if not pid:
        raise RuntimeError("Cloudinary upload failed (missing public_id)")
    return url, pid


def destroy(*, public_id: str, resource_type: ResourceType) -> None:
    """
    Best-effort delete of a Cloudinary asset.
    """
    pid = (public_id or "").strip()
    if not pid:
        return
    try:
        cloudinary.uploader.destroy(pid, resource_type=resource_type, invalidate=False)
    except Exception:
        # Best-effort cleanup; do not break API flows.
        return

