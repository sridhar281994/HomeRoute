from __future__ import annotations

import os
import time
from typing import Iterable

from kivy.utils import platform


LOG_TAG = "ANDROID_PICKER"


def _log(msg: str) -> None:
    try:
        print(f"[{LOG_TAG}] {msg}")
    except Exception:
        pass


def _strip_file_scheme(p: str) -> str:
    p = str(p or "").strip()
    if p.startswith("file://"):
        return p[len("file://") :]
    return p


def _android_copy_content_uri_to_cache(uri: str) -> str:
    """
    Copy an Android content:// URI to the app's cache directory.
    """
    _log(f"Copying content URI → cache: {uri}")

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

    display_name = ""
    cursor = None
    try:
        cursor = resolver.query(uri_obj, None, None, None, None)
        if cursor is not None and cursor.moveToFirst():
            idx = int(cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME))
            if idx >= 0:
                display_name = str(cursor.getString(idx) or "")
    except Exception as e:
        _log(f"Failed reading display name: {e}")
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

    out_path = str(out_file.getAbsolutePath())
    _log(f"Copied file path: {out_path}")
    return out_path


def ensure_local_path(p: str) -> str:
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
        except Exception as e:
            _log(f"Path normalize failed: {p} → {e}")
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
    """
    _log("android_open_gallery() called")

    if platform != "android":
        _log("Not running on Android → abort")
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
                _log(f"Requesting permissions: {perms}")
                request_permissions(perms)
        except Exception as e:
            _log(f"Permission request failed: {e}")

        # -----------------------------
        # Build intent safely
        # -----------------------------
        _log("Building picker intent")

        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.addCategory(Intent.CATEGORY_DEFAULT)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        _log(f"MIME types: {mimes}")

        intent.setType(str(mimes[0]))
        if len(mimes) > 1:
            arr = jarray("java.lang.String")([String(m) for m in mimes])
            intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        chooser = Intent.createChooser(intent, "Select file")
        req_code = 13579

        def _deliver(sel: list[str]) -> None:
            _log(f"Delivering selection: {sel}")
            try:
                Clock.schedule_once(lambda *_: on_selection(list(sel or [])), 0)
            except Exception as e:
                _log(f"Deliver callback failed: {e}")

        def _on_activity_result(requestCode, resultCode, data) -> None:  # noqa: N802
            _log(f"Activity result → request={requestCode}, result={resultCode}, data={data}")

            if int(requestCode) != int(req_code):
                _log("Ignoring unrelated activity result")
                return

            if int(resultCode) != int(Activity.RESULT_OK) or data is None:
                _log("Picker canceled or empty result")
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
                _log(f"ClipData count: {n}")
                for i in range(max(0, n)):
                    try:
                        item = clip.getItemAt(i)
                        uri = item.getUri()
                        if uri is not None:
                            out.append(str(uri.toString()))
                    except Exception as e:
                        _log(f"Clip read error: {e}")
            else:
                try:
                    uri = data.getData()
                    if uri is not None:
                        out.append(str(uri.toString()))
                except Exception as e:
                    _log(f"Data URI read error: {e}")

            _deliver(out)

        # -----------------------------
        # Register callback safely
        # -----------------------------
        try:
            _log("Registering activity result callback")
            activity.result_callback = _on_activity_result
        except Exception as e:
            _log(f"Callback registration failed: {e}")
            return False

        # -----------------------------
        # Launch picker
        # -----------------------------
        try:
            _log("Launching chooser intent")
            act = PythonActivity.mActivity
            act.startActivityForResult(chooser, req_code)
            _log("Picker launched successfully")
            return True
        except Exception as e:
            _log(f"startActivityForResult failed: {e}")
            return False

    except Exception as e:
        _log(f"android_open_gallery fatal error: {e}")
        return False
