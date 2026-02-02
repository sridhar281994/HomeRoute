from __future__ import annotations

import os
import tempfile
from typing import Literal

import cloudinary.uploader
from app.utils.cloudinary_config import cloudinary_is_configured

ResourceType = Literal["image", "video"]


def _cloudinary_folder() -> str:
    return (os.getenv("CLOUDINARY_FOLDER") or "quickrent4u").strip() or "quickrent4u"


def cloudinary_enabled() -> bool:
    return cloudinary_is_configured()


def upload_bytes(
    *,
    raw: bytes,
    resource_type: ResourceType,
    public_id: str,
    filename: str,
    content_type: str,
) -> tuple[str, str]:

    if not raw:
        raise RuntimeError("Empty upload")
    if not cloudinary_enabled():
        raise RuntimeError("Cloudinary is not configured")

    tmp_path = None

    try:
        # -------- write to temp file (MANDATORY) --------
        ext = os.path.splitext(filename or "")[1].lower()
        if not ext:
            ext = ".jpg" if resource_type == "image" else ".mp4"

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(raw)
        tmp.flush()
        tmp_path = tmp.name

        # -------- Cloudinary upload --------
        res = cloudinary.uploader.upload(
            tmp_path,
            resource_type=resource_type,
            folder=_cloudinary_folder(),
            public_id=public_id,
            overwrite=False,
            type="upload",
            invalidate=False,
        )

        url = str(res.get("secure_url") or "").strip()
        pid = str(res.get("public_id") or "").strip()

        if not url or not pid:
            raise RuntimeError("Cloudinary upload returned empty response")

        return url, pid

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

def destroy(*, public_id: str, resource_type: ResourceType) -> None:
    pid = (public_id or "").strip()
    if not pid:
        return
    try:
        cloudinary.uploader.destroy(
            pid,
            resource_type=resource_type,
            invalidate=False,
        )
    except Exception:
        # best-effort cleanup
        pass

