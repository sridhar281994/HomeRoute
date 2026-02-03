from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Literal

from PIL import Image
import cloudinary.uploader

from app.utils.cloudinary_config import cloudinary_is_configured

ResourceType = Literal["image", "video"]


def _suffix_from_upload(*, filename: str, content_type: str, resource_type: ResourceType) -> str:
    """
    Pick a temp-file suffix for Cloudinary upload.

    Cloudinary detects by content, but extension helps when formats aren't
    supported by Pillow and we fall back to raw upload.
    """
    ext = os.path.splitext((filename or "").strip())[1].lower()
    if ext and len(ext) <= 12 and ext.startswith("."):
        return ext

    ct = (content_type or "").lower().strip()
    if resource_type == "image":
        if ct in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if ct == "image/png":
            return ".png"
        if ct == "image/webp":
            return ".webp"
        if ct == "image/gif":
            return ".gif"
        if ct == "image/avif":
            return ".avif"
        if ct in {"image/heic", "image/heif"}:
            return ".heic"
        return ".img"

    # video
    if ct == "video/mp4":
        return ".mp4"
    if ct == "video/quicktime":
        return ".mov"
    return ".bin"


def _cloudinary_folder() -> str:
    return (os.getenv("CLOUDINARY_FOLDER") or "quickrent4u").strip()


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
        raise RuntimeError("Cloudinary not configured")

    tmp_path = None

    try:
        # Image uploads: normalize to JPEG when Pillow can decode it.
        # If Pillow can't identify the image, fall back to raw upload so Cloudinary
        # can attempt decode (e.g. AVIF/HEIC without server-side Pillow support).
        if resource_type == "image":
            try:
                img = Image.open(BytesIO(raw))
                img.verify()          # validates structure
                img = Image.open(BytesIO(raw))
                img = img.convert("RGB")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp, format="JPEG", quality=85, optimize=True)
                    tmp.flush()
                    tmp_path = tmp.name
            except Exception:
                # Fallback: upload raw bytes as-is (Cloudinary may still reject corrupt inputs).
                suffix = _suffix_from_upload(
                    filename=filename,
                    content_type=content_type,
                    resource_type=resource_type,
                )
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(raw)
                    tmp.flush()
                    tmp_path = tmp.name
        else:
            ext = _suffix_from_upload(
                filename=filename,
                content_type=content_type,
                resource_type=resource_type,
            )
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
            invalidate=False,
        )

        url = res.get("secure_url")
        pid = res.get("public_id")

        if not url or not pid:
            raise RuntimeError("Cloudinary returned empty response")

        return url, pid

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def destroy(*, public_id: str, resource_type: ResourceType) -> None:
    try:
        cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=False,
        )
    except Exception:
        pass
