from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Literal

import cloudinary.uploader
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

from app.utils.cloudinary_config import cloudinary_is_configured


ResourceType = Literal["image", "video"]

MAX_IMAGE_SIZE = 1600   # px
JPEG_QUALITY = 82       # balance between size & quality


def _cloudinary_folder() -> str:
    return (os.getenv("CLOUDINARY_FOLDER") or "quickrent4u").strip() or "quickrent4u"


def cloudinary_enabled() -> bool:
    return cloudinary_is_configured()

def _looks_like_image(raw: bytes) -> bool:
    if not raw or len(raw) < 16:
        return False

    sig = raw[:16]

    return (
        sig.startswith(b"\xFF\xD8\xFF") or          # JPEG
        sig.startswith(b"\x89PNG\r\n\x1a\n") or     # PNG
        sig.startswith(b"RIFF") or                  # WEBP
        sig[4:12] == b"ftypheic" or                  # HEIC
        sig[4:12] == b"ftypheif"
    )



def _optimize_image(raw: bytes) -> str | None:
    """
    Validate + optimize image.
    Returns temp file path or None if invalid.
    """

    if not _looks_like_image(raw):
        return None   # 🔴 skip silently

    try:
        img = Image.open(BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.LANCZOS)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(
            tmp,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )
        tmp.flush()
        return tmp.name

    except Exception:
        # fallback: raw upload
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.write(raw)
        tmp.flush()
        return tmp.name



def upload_bytes(
    *,
    raw: bytes,
    resource_type: ResourceType,
    public_id: str,
    filename: str,
    content_type: str,
) -> tuple[str, str]:

    tmp_path: str | None = None

    try:
        if resource_type == "image":
            tmp_path = _optimize_image(raw)

            # 🔴 INVALID IMAGE → SKIP SILENTLY
            if not tmp_path:
                return "", ""

        else:
            ext = os.path.splitext(filename or "")[1].lower() or ".mp4"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tmp.write(raw)
            tmp.flush()
            tmp_path = tmp.name

        # 🔴 EXTRA SAFETY
        if not tmp_path or not os.path.exists(tmp_path):
            return "", ""

        # ---------- Cloudinary ----------
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
            return "", ""

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
        pass
