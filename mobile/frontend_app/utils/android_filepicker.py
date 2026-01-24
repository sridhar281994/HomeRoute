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
        from kivy.clock import Clock
        from jnius import autoclass, jarray  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        Activity = autoclass("android.app.Activity")

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        # Use a request code that is unlikely to collide.
        req_code = 13579
        action_open_document = True

        def _deliver(sel: list[str]) -> None:
            try:
                Clock.schedule_once(lambda *_: on_selection(list(sel or [])), 0)
            except Exception:
                pass

        def _on_activity_result(requestCode, resultCode, data) -> None:  # noqa: N802 (android callback naming)
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

            # If we used ACTION_OPEN_DOCUMENT, persist read permission when possible.
            # This helps when we later open/copy content:// URIs.
            if action_open_document:
                try:
                    flags = int(data.getFlags())
                    take_flags = flags & int(
                        Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                    )
                except Exception:
                    take_flags = 0
            else:
                take_flags = 0

            try:
                resolver = PythonActivity.mActivity.getContentResolver()
            except Exception:
                resolver = None

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
                            if action_open_document and resolver is not None and take_flags:
                                try:
                                    resolver.takePersistableUriPermission(uri, take_flags)
                                except Exception:
                                    pass
                            out.append(str(uri.toString()))
                    except Exception:
                        continue
            else:
                try:
                    uri = data.getData()
                    if uri is not None:
                        if action_open_document and resolver is not None and take_flags:
                            try:
                                resolver.takePersistableUriPermission(uri, take_flags)
                            except Exception:
                                pass
                        out.append(str(uri.toString()))
                except Exception:
                    pass

            _deliver(out)

        try:
            activity.bind(on_activity_result=_on_activity_result)
        except Exception:
            return False

        def _make_intent(action: str):
            intent = Intent(action)
            intent.addCategory(Intent.CATEGORY_OPENABLE)

            # Always request read access for returned URIs.
            try:
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            except Exception:
                pass

            # ACTION_OPEN_DOCUMENT can grant persistable permission.
            if str(action) == str(Intent.ACTION_OPEN_DOCUMENT):
                try:
                    intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
                except Exception:
                    pass

            # Set a general type and optionally pass multiple MIME types.
            if len(mimes) <= 1:
                intent.setType(str(mimes[0]))
            else:
                # Many devices are picky about EXTRA_MIME_TYPES. Best-effort only.
                intent.setType("*/*")
                try:
                    arr = jarray("java.lang.String")([String(m) for m in mimes])
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)
                except Exception:
                    pass

            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
            return intent

        try:
            act = PythonActivity.mActivity
            # Prefer SAF document picker; fall back to GET_CONTENT on devices where
            # DocumentsUI isn't available or ACTION_OPEN_DOCUMENT fails.
            try:
                action_open_document = True
                intent = _make_intent(Intent.ACTION_OPEN_DOCUMENT)
                act.startActivityForResult(intent, req_code)
                return True
            except Exception:
                try:
                    action_open_document = False
                    intent = _make_intent(Intent.ACTION_GET_CONTENT)
                    act.startActivityForResult(intent, req_code)
                    return True
                except Exception:
                    raise
        except Exception:
            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass
            return False
    except Exception:
        return False

