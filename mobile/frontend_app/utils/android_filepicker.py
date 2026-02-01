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
    Copy Android content:// URI into app cache file.
    Fully PyJNIus-safe.
    """

    _log(f"Copying content URI → cache: {uri}")

    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    OpenableColumns = autoclass("android.provider.OpenableColumns")
    File = autoclass("java.io.File")
    FileOutputStream = autoclass("java.io.FileOutputStream")
    ByteClass = autoclass("java.lang.Byte")
    Array = autoclass("java.lang.reflect.Array")

    act = PythonActivity.mActivity
    ctx = act.getApplicationContext()
    resolver = ctx.getContentResolver()
    uri_obj = Uri.parse(str(uri))

    # -------- filename --------
    display_name = ""
    cursor = None
    try:
        cursor = resolver.query(uri_obj, None, None, None, None)
        if cursor and cursor.moveToFirst():
            idx = int(cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME))
            if idx >= 0:
                display_name = str(cursor.getString(idx) or "")
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass

    if not display_name:
        display_name = f"picked_{int(time.time())}"

    display_name = (
        display_name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )

    # ensure extension (important for your is_image_path logic)
    if "." not in display_name:
        try:
            mime = resolver.getType(uri_obj) or ""
            if mime.startswith("image/"):
                display_name += ".jpg"
            elif mime.startswith("video/"):
                display_name += ".mp4"
        except Exception:
            pass

    cache_dir = ctx.getCacheDir()
    # Ensure unique filename in cache (avoid overwriting when multiple selected share same DISPLAY_NAME).
    base = display_name
    name = base
    out_file = File(cache_dir, name)
    try:
        if out_file.exists():
            # Keep extension if any.
            root = name
            ext = ""
            if "." in name:
                root, ext = name.rsplit(".", 1)
                ext = "." + ext
            # Use URI hash + timestamp for uniqueness.
            stamp = int(time.time() * 1000)
            tag = abs(hash(str(uri))) % 100000
            name = f"{root}_{stamp}_{tag}{ext}"
            out_file = File(cache_dir, name)
    except Exception:
        # Best-effort: proceed with original name.
        out_file = File(cache_dir, base)

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise OSError("Unable to open input stream")

    outs = FileOutputStream(out_file)

    # ✅ SAFE byte[] buffer creation
    buf = Array.newInstance(ByteClass.TYPE, 8192)

    try:
        while True:
            n = ins.read(buf)
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

    path = str(out_file.getAbsolutePath())
    _log(f"Copied file path: {path}")
    return path



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

    if platform != "android":
        return False

    try:
        from android import activity
        from kivy.clock import Clock
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Activity = autoclass("android.app.Activity")
        JavaString = autoclass("java.lang.String")
        Array = autoclass("java.lang.reflect.Array")

        act = PythonActivity.mActivity
        pm = act.getPackageManager()
        resolver = act.getContentResolver()

        req_code = 13579

        def _deliver(sel):
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

            out = []

            clip = data.getClipData()
            if clip:
                for i in range(clip.getItemCount()):
                    uri = clip.getItemAt(i).getUri()
                    if uri:
                        try:
                            resolver.takePersistableUriPermission(
                                uri,
                                Intent.FLAG_GRANT_READ_URI_PERMISSION,
                            )
                        except Exception:
                            pass
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                if uri:
                    try:
                        resolver.takePersistableUriPermission(
                            uri,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION,
                        )
                    except Exception:
                        pass
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        # ---------- MIME handling ----------
        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        # ---------- 1️⃣ TRY SAF (best) ----------
        saf_intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        saf_intent.addCategory(Intent.CATEGORY_OPENABLE)

        if len(mimes) == 1:
            saf_intent.setType(mimes[0])
        else:
            saf_intent.setType("*/*")
            arr = Array.newInstance(JavaString, len(mimes))
            for i, m in enumerate(mimes):
                Array.set(arr, i, JavaString(m))
            saf_intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        saf_intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        saf_intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )

        if saf_intent.resolveActivity(pm) is not None:
            chooser = Intent.createChooser(
                saf_intent,
                JavaString("Select file(s)"),
            )
            Clock.schedule_once(
                lambda *_: act.startActivityForResult(chooser, req_code),
                0.15,
            )
            return True

        # ---------- 2️⃣ FALLBACK: ACTION_GET_CONTENT (OEM-safe) ----------
        _log("SAF not available, falling back to ACTION_GET_CONTENT")

        get_intent = Intent(Intent.ACTION_GET_CONTENT)
        get_intent.addCategory(Intent.CATEGORY_OPENABLE)

        if len(mimes) == 1:
            get_intent.setType(mimes[0])
        else:
            get_intent.setType("*/*")
            arr = Array.newInstance(JavaString, len(mimes))
            for i, m in enumerate(mimes):
                Array.set(arr, i, JavaString(m))
            get_intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        get_intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        get_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        if get_intent.resolveActivity(pm) is None:
            _log("No picker available on this device")
            return False

        chooser = Intent.createChooser(
            get_intent,
            JavaString("Select file(s)"),
        )

        Clock.schedule_once(
            lambda *_: act.startActivityForResult(chooser, req_code),
            0.15,
        )

        return True

    except Exception as e:
        _log(f"Picker failed: {e}")
        import traceback
        traceback.print_exc()
        return False
