from __future__ import annotations

import os
import time
from typing import Iterable

from kivy.utils import platform


def _strip_file_scheme(p: str) -> str:
    p = str(p or "").strip()
    if p.startswith("file://"):
        return p[len("file://") :]
    return p


def _android_copy_content_uri_to_cache(uri: str) -> str:
    """
    Copy an Android content:// URI to the app's cache directory.

    Needed because Android's file picker (SAF) often returns content URIs, while our
    upload code expects a real local filesystem path.
    """
    from jnius import autoclass, jarray  # type: ignore

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    OpenableColumns = autoclass("android.provider.OpenableColumns")
    File = autoclass("java.io.File")
    FileOutputStream = autoclass("java.io.FileOutputStream")

    activity = PythonActivity.mActivity
    ctx = activity.getApplicationContext()
    resolver = ctx.getContentResolver()
    uri_obj = Uri.parse(str(uri))

    # Best-effort display name (keeps extensions when provided by picker).
    display_name = ""
    cursor = None
    try:
        cursor = resolver.query(uri_obj, None, None, None, None)
        if cursor is not None and cursor.moveToFirst():
            idx = int(cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME))
            if idx >= 0:
                display_name = str(cursor.getString(idx) or "")
    except Exception:
        display_name = ""
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass

    if not display_name:
        display_name = f"picked_{int(time.time())}"

    cache_dir = ctx.getCacheDir()
    out_file = File(cache_dir, display_name)

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise OSError("Unable to read selected file.")

    outs = FileOutputStream(out_file)
    buf = jarray("b")(8192)
    try:
        while True:
            n = int(ins.read(buf))
            if n == -1:
                break
            outs.write(buf, 0, n)
        outs.flush()
    finally:
        try:
            ins.close()
        except Exception:
            pass
        try:
            outs.close()
        except Exception:
            pass

    return str(out_file.getAbsolutePath())


def ensure_local_path(p: str) -> str:
    """
    Normalize picker results into a readable local filesystem path.
    """
    p = str(p or "").strip()
    if not p:
        raise ValueError("Empty path")

    p = _strip_file_scheme(p)

    if platform != "android":
        return p

    if p.startswith("content://"):
        return _android_copy_content_uri_to_cache(p)

    return p


def ensure_local_paths(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in list(paths or []):
        try:
            lp = ensure_local_path(str(p))
            if lp and lp not in out:
                out.append(lp)
        except Exception:
            continue
    return out


def is_image_path(p: str) -> bool:
    ext = os.path.splitext(str(p).lower())[1]
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_video_path(p: str) -> bool:
    ext = os.path.splitext(str(p).lower())[1]
    return ext in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

