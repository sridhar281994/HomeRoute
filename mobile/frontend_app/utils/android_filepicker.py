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
    PyJNIus-safe (NO jarray).
    """
    _log(f"Copying content URI → cache: {uri}")

    from jnius import autoclass  # type: ignore

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    OpenableColumns = autoclass("android.provider.OpenableColumns")
    File = autoclass("java.io.File")
    FileOutputStream = autoclass("java.io.FileOutputStream")
    ByteArray = autoclass("[B")  # byte[]

    activity = PythonActivity.mActivity
    ctx = activity.getApplicationContext()
    resolver = ctx.getContentResolver()
    uri_obj = Uri.parse(str(uri))

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

    cache_dir = ctx.getCacheDir()
    out_file = File(cache_dir, display_name)

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise OSError("Unable to read selected file.")

    outs = FileOutputStream(out_file)

    # ✅ CORRECT byte buffer (no jarray)
    buf = ByteArray(8192)

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
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                if uri:
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        # ---------- SAF picker ----------
        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

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
        saf_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        if saf_intent.resolveActivity(pm) is not None:
            chooser = Intent.createChooser(
                saf_intent,
                JavaString("Select file"),
            )
            Clock.schedule_once(
                lambda *_: act.startActivityForResult(chooser, req_code),
                0.15,
            )
            return True

        # ---------- Gallery fallback ----------
        _log("SAF picker missing, falling back to gallery")

        pick_intent = Intent(Intent.ACTION_PICK)
        pick_intent.setType("image/*")

        if pick_intent.resolveActivity(pm) is None:
            _log("No gallery app available")
            return False

        chooser = Intent.createChooser(
            pick_intent,
            JavaString("Select image"),
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
