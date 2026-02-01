from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Literal

import cloudinary.uploader
from PIL import Image, UnidentifiedImageError
import pillow_heif

from app.utils.cloudinary_config import cloudinary_is_configured


# 🔴 CRITICAL: enable HEIC / HEIF support (Android camera photos)
pillow_heif.register_heif_opener()


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
    """
    Upload raw bytes to Cloudinary safely.

    - Supports HEIC / HEIF (Android camera)
    - Normalizes images to real JPEG
    - Uses temp files (Cloudinary-safe)
    """

    tmp_path: str | None = None

    try:
        # ---------------- IMAGE ----------------
        if resource_type == "image":
            try:
                img = Image.open(BytesIO(raw))
                img = img.convert("RGB")

                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp, format="JPEG", quality=90, optimize=True)
                    tmp.flush()
                    tmp_path = tmp.name

            except UnidentifiedImageError:
                raise RuntimeError(
                    "Unsupported image format. Please upload photos from Gallery or Camera."
                )
            except Exception as e:
                raise RuntimeError(f"Invalid image data: {e}")

        # ---------------- VIDEO ----------------
        else:
            ext = os.path.splitext(filename or "")[1].lower() or ".mp4"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(raw)
                tmp.flush()
                tmp_path = tmp.name

        # ---------------- CLOUDINARY ----------------
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
            raise RuntimeError("Cloudinary upload failed")

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
        cloudinary.uploader.destroy(pid, resource_type=resource_type, invalidate=False)
    except Exception:
        return
