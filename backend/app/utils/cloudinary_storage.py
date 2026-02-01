from __future__ import annotations

import os
import tempfile
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
def upload_bytes(
    *,
    raw: bytes,
    resource_type: ResourceType,
    public_id: str,
    filename: str,
    content_type: str,
) -> tuple[str, str]:
    """
    Upload raw bytes to Cloudinary using a temp file.
    This avoids SAF / BytesIO corruption issues.
    """

    ext = os.path.splitext(filename or "")[1]
    if not ext:
        ext = ".jpg" if resource_type == "image" else ".mp4"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(raw)
            tmp.flush()
            tmp_path = tmp.name

        res = cloudinary.uploader.upload(
            tmp_path,
            resource_type=resource_type,
            folder=_cloudinary_folder(),
            public_id=public_id,
            overwrite=False,
            type="upload",
            invalidate=False,
        )

        url = str((res or {}).get("secure_url") or "").strip()
        pid = str((res or {}).get("public_id") or "").strip()

        if not url or not pid:
            raise RuntimeError("Cloudinary upload failed")

        return url, pid

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


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

