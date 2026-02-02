from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Literal

from PIL import Image
import cloudinary.uploader

from app.utils.cloudinary_config import cloudinary_is_configured

ResourceType = Literal["image", "video"]


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
        # ✅ STRICT IMAGE VALIDATION
        if resource_type == "image":
            try:
                img = Image.open(BytesIO(raw))
                img.verify()          # validates structure
                img = Image.open(BytesIO(raw))
                img = img.convert("RGB")
            except Exception:
                raise RuntimeError(
                    "Invalid image file. Please upload from Camera or Gallery."
                )

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                img.save(tmp, format="JPEG", quality=85, optimize=True)
                tmp.flush()
                tmp_path = tmp.name
        else:
            ext = os.path.splitext(filename or "")[1] or ".mp4"
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
