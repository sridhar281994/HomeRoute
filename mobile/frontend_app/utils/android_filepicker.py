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

    def _guess_ext_from_mime(mime: str) -> str:
        m = str(mime or "").strip().lower()
        if not m:
            return ""
        # Common image types
        if m in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if m == "image/png":
            return ".png"
        if m == "image/webp":
            return ".webp"
        if m == "image/gif":
            return ".gif"
        # Common video types
        if m == "video/mp4":
            return ".mp4"
        if m == "video/quicktime":
            return ".mov"
        if m.startswith("image/"):
            return ".jpg"
        if m.startswith("video/"):
            return ".mp4"
        return ""

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
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass

    if not display_name:
        display_name = f"picked_{int(time.time())}"

    # Sanitize name + ensure extension so is_image_path()/is_video_path() works after copy.
    display_name = display_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    base, ext = os.path.splitext(display_name)
    if not ext:
        mime = ""
        try:
            mime = str(resolver.getType(uri_obj) or "")
        except Exception:
            mime = ""
        ext = _guess_ext_from_mime(mime)
        if ext:
            display_name = f"{display_name}{ext}"

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
    Android system picker (SAF) for images/videos/files.

    - UI-thread safe
    - Android 10–14 compatible
    - No storage permission required
    - Returns content:// URIs
    """

    if platform != "android":
        return False

    try:
        from android import activity  # type: ignore
        from kivy.clock import Clock
        from jnius import autoclass, jarray  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Activity = autoclass("android.app.Activity")
        String = autoclass("java.lang.String")

        act = PythonActivity.mActivity
        pm = act.getPackageManager()

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)

        if len(mimes) == 1:
            intent.setType(mimes[0])
        else:
            intent.setType("*/*")
            arr = jarray("java.lang.String")([String(m) for m in mimes])
            intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        try:
            intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            intent.addFlags(Intent.FLAG_GRANT_PREFIX_URI_PERMISSION)
        except Exception:
            pass

        # 🔐 Check picker availability (OEM safety)
        if intent.resolveActivity(pm) is None:
            _log("No system picker available on this device")
            return False

        chooser = Intent.createChooser(intent, "Select file")
        req_code = 13579

        def _deliver(sel: list[str]) -> None:
            Clock.schedule_once(lambda *_: on_selection(list(sel or [])), 0)

        def _on_activity_result(requestCode, resultCode, data):
            if requestCode != req_code:
                return

            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass

            if resultCode != Activity.RESULT_OK or data is None:
                _deliver([])
                return

            out: list[str] = []

            clip = data.getClipData()
            if clip:
                for i in range(clip.getItemCount()):
                    uri = clip.getItemAt(i).getUri()
                    if uri:
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                if uri:
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        # 🔴 CRITICAL FIX: always launch on UI thread with delay
        Clock.schedule_once(lambda *_: act.startActivityForResult(chooser, req_code), 0.15)

        return True

    except Exception as e:
        _log(f"Picker failed: {e}")
        import traceback
        traceback.print_exc()
        return False
