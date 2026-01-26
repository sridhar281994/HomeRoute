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


def android_open_gallery(
    *,
    on_selection,
    multiple: bool = False,
    mime_types: list[str] | None = None,
) -> bool:
    """
    Android native gallery/document picker fallback using Intent.

    This is used when `plyer.filechooser` is unavailable or fails.

    - Returns True if an Intent was launched.
    - Calls `on_selection(list_of_uris_or_paths)` on the Kivy main thread.
    """
    if platform != "android":
        return False

    try:
        from android import activity  # type: ignore
        from android.permissions import Permission, request_permissions  # type: ignore
        from kivy.clock import Clock
        from jnius import autoclass, jarray  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        Activity = autoclass("android.app.Activity")

        # -----------------------------
        # Ensure runtime permissions
        # -----------------------------
        try:
            perms = []
            if hasattr(Permission, "READ_MEDIA_IMAGES"):
                perms.append(Permission.READ_MEDIA_IMAGES)
            if hasattr(Permission, "READ_EXTERNAL_STORAGE"):
                perms.append(Permission.READ_EXTERNAL_STORAGE)
            if perms:
                request_permissions(perms)
        except Exception:
            pass

        # -----------------------------
        # Build intent safely
        # -----------------------------
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.addCategory(Intent.CATEGORY_DEFAULT)

        # Required URI permissions for Android 11+
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        # Set a general type and optionally pass multiple MIME types.
        intent.setType(str(mimes[0]))
        if len(mimes) > 1:
            arr = jarray("java.lang.String")([String(m) for m in mimes])
            intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))

        # Wrap in chooser (OEM reliability fix)
        chooser = Intent.createChooser(intent, "Select file")

        # Use a request code that is unlikely to collide.
        req_code = 13579

        def _deliver(sel: list[str]) -> None:
            try:
                Clock.schedule_once(lambda *_: on_selection(list(sel or [])), 0)
            except Exception:
                pass

        def _on_activity_result(requestCode, resultCode, data) -> None:  # noqa: N802
            if int(requestCode) != int(req_code):
                return
            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass

            if int(resultCode) != int(Activity.RESULT_OK) or data is None:
                _deliver([])
                return

            out: list[str] = []
            try:
                clip = data.getClipData()
            except Exception:
                clip = None

            if clip is not None:
                try:
                    n = int(clip.getItemCount())
                except Exception:
                    n = 0
                for i in range(max(0, n)):
                    try:
                        item = clip.getItemAt(i)
                        uri = item.getUri()
                        if uri is not None:
                            out.append(str(uri.toString()))
                    except Exception:
                        continue
            else:
                try:
                    uri = data.getData()
                    if uri is not None:
                        out.append(str(uri.toString()))
                except Exception:
                    pass

            _deliver(out)

        # -----------------------------
        # Bind callback
        # -----------------------------
        try:
            activity.bind(on_activity_result=_on_activity_result)
        except Exception:
            return False

        # -----------------------------
        # Launch picker
        # -----------------------------
        try:
            act = PythonActivity.mActivity
            act.startActivityForResult(chooser, req_code)
            return True
        except Exception:
            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass
            return False

    except Exception:
        return False
