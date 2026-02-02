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
    Copy Android content:// URI into app cache and return local file path.
    SAFE for multi-select and OEM ROMs.
    """
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

    # ---- filename ----
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

    display_name = display_name.replace("/", "_").replace("\\", "_").replace(":", "_")

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
    out_file = File(cache_dir, display_name)

    if out_file.exists():
        root, ext = os.path.splitext(display_name)
        stamp = int(time.time() * 1000)
        out_file = File(cache_dir, f"{root}_{stamp}{ext}")

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise OSError("Unable to open input stream")

    outs = FileOutputStream(out_file)
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
    _log(f"Copied to cache: {path}")
    return path


def ensure_local_path(p: str) -> str:
    p = _strip_file_scheme(p)
    if platform == "android" and p.startswith("content://"):
        return _android_copy_content_uri_to_cache(p)
    return p


def ensure_local_paths(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in paths or []:
        try:
            lp = ensure_local_path(p)
            if lp and lp not in out:
                out.append(lp)
        except Exception as e:
            _log(f"Normalize failed: {p} → {e}")
    return out


def is_image_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_video_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def android_open_gallery(*, on_selection, multiple=False, mime_types=None) -> bool:
    if platform != "android":
        _log("Platform is not Android → abort")
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

        _log(f"Device activity = {act}")
        _log(f"PackageManager = {pm}")

        req_code = 13579

        def _deliver(sel):
            _log(f"Delivering selection → count={len(sel or [])}")
            Clock.schedule_once(lambda *_: on_selection(list(sel or [])), 0)

        def _on_activity_result(requestCode, resultCode, data):
            _log(f"onActivityResult rc={requestCode} result={resultCode} data={data}")

            if requestCode != req_code:
                _log("Request code mismatch → ignored")
                return

            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception as e:
                _log(f"Unbind failed: {e}")

            if resultCode != Activity.RESULT_OK or data is None:
                _log("Picker cancelled or no data returned")
                _deliver([])
                return

            out = []
            clip = data.getClipData()

            if clip:
                _log(f"ClipData count = {clip.getItemCount()}")
                for i in range(clip.getItemCount()):
                    uri = clip.getItemAt(i).getUri()
                    _log(f"Clip uri[{i}] = {uri}")
                    if uri:
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                _log(f"Single uri = {uri}")
                if uri:
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        mimes = [m for m in (mime_types or []) if m]
        if not mimes:
            mimes = ["image/*"]

        _log(f"Requested mimes = {mimes}")
        _log(f"Multiple selection = {multiple}")

        # ---------------- 1️⃣ ACTION_OPEN_DOCUMENT ----------------
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))

        if len(mimes) == 1:
            intent.setType(mimes[0])
        else:
            intent.setType("*/*")
            arr = Array.newInstance(JavaString, len(mimes))
            for i, m in enumerate(mimes):
                Array.set(arr, i, JavaString(m))
            intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

        intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION |
            Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )

        if intent.resolveActivity(pm) is not None:
            _log("Using ACTION_OPEN_DOCUMENT")
        else:
            _log("ACTION_OPEN_DOCUMENT not available")

            # ---------------- 2️⃣ ACTION_GET_CONTENT ----------------
            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
            intent.setType(mimes[0])

            if intent.resolveActivity(pm) is not None:
                _log("Using ACTION_GET_CONTENT")
            else:
                _log("ACTION_GET_CONTENT not available")

                # ---------------- 3️⃣ ACTION_PICK ----------------
                intent = Intent(Intent.ACTION_PICK)
                intent.setType("image/*")

                if intent.resolveActivity(pm) is not None:
                    _log("Using ACTION_PICK (gallery)")
                else:
                    _log("❌ NO picker intent available on device")
                    return False

        chooser = Intent.createChooser(intent, JavaString("Select image(s)"))

        _log(f"Starting picker intent → {intent}")
        Clock.schedule_once(
            lambda *_: act.startActivityForResult(chooser, req_code),
            0
        )
        return True

    except Exception as e:
        _log(f"Picker crashed: {e}")
        import traceback
        traceback.print_exc()
        return False
