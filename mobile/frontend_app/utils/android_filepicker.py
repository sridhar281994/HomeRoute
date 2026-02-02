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


# ------------------------------------------------------------
# INTERNAL HELPERS
# ------------------------------------------------------------
def _strip_file_scheme(p: str) -> str:
    p = str(p or "").strip()
    if p.startswith("file://"):
        return p[len("file://"):]
    return p


def _validate_image_bytes(path: str) -> None:
    """
    HARD validation to prevent corrupted images reaching backend.
    This is the root fix for your Cloudinary / PIL errors.
    """
    _log(f"VALIDATE image → {path}")

    if not os.path.isfile(path):
        raise RuntimeError("File does not exist")

    size = os.path.getsize(path)
    _log(f"Image size = {size} bytes")

    if size < 1024:
        raise RuntimeError("Image too small / corrupted")

    with open(path, "rb") as f:
        head = f.read(16)

    _log(f"Header bytes = {head}")

    # JPEG
    if head.startswith(b"\xff\xd8\xff"):
        return
    # PNG
    if head.startswith(b"\x89PNG"):
        return
    # WEBP
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return

    raise RuntimeError("Invalid or unsupported image format")


# ------------------------------------------------------------
# URI → LOCAL CACHE COPY (SAFE + LOGGED)
# ------------------------------------------------------------
def _android_copy_content_uri_to_cache(uri: str) -> str:
    _log(f"BEGIN copy_content_uri → {uri}")

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

    # ---------- filename ----------
    display_name = ""
    cursor = None
    try:
        cursor = resolver.query(uri_obj, None, None, None, None)
        if cursor and cursor.moveToFirst():
            idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if idx >= 0:
                display_name = str(cursor.getString(idx) or "")
    except Exception as e:
        _log(f"Filename query failed: {e}")
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass

    if not display_name:
        display_name = f"picked_{int(time.time())}.jpg"

    display_name = display_name.replace("/", "_").replace("\\", "_").replace(":", "_")

    cache_dir = ctx.getCacheDir()
    out_file = File(cache_dir, display_name)

    if out_file.exists():
        root, ext = os.path.splitext(display_name)
        out_file = File(cache_dir, f"{root}_{int(time.time() * 1000)}{ext}")

    _log(f"Cache target → {out_file.getAbsolutePath()}")

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise OSError("ContentResolver.openInputStream returned NULL")

    outs = FileOutputStream(out_file)
    buf = Array.newInstance(ByteClass.TYPE, 8192)
    total = 0

    try:
        while True:
            n = ins.read(buf)
            if n == -1:
                break
            outs.write(buf, 0, n)
            total += n
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
    _log(f"Copied {total} bytes → {path}")

    # 🔴 CRITICAL: validate copied file
    _validate_image_bytes(path)

    return path


# ------------------------------------------------------------
# PATH NORMALIZATION
# ------------------------------------------------------------
def ensure_local_path(p: str) -> str:
    if not p:
        raise ValueError("Empty path")

    p = _strip_file_scheme(p)

    if platform == "android" and p.startswith("content://"):
        _log(f"Normalizing content URI → {p}")
        return _android_copy_content_uri_to_cache(p)

    return p


def ensure_local_paths(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in paths or []:
        try:
            lp = ensure_local_path(p)
            out.append(lp)
        except Exception as e:
            _log(f"Normalize failed → {p} | {e}")
    return out


# ------------------------------------------------------------
# FILE TYPE HELPERS (USED BY UI)
# ------------------------------------------------------------
def is_image_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_video_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


# ------------------------------------------------------------
# ANDROID GALLERY PICKER (FORENSIC LOGGING)
# ------------------------------------------------------------
def android_open_gallery(*, on_selection, multiple=False, mime_types=None) -> bool:
    _log("==== android_open_gallery START ====")

    if platform != "android":
        _log("ABORT: Not Android")
        return False

    try:
        from android import activity
        from kivy.clock import Clock
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Activity = autoclass("android.app.Activity")
        JavaString = autoclass("java.lang.String")

        act = PythonActivity.mActivity
        pm = act.getPackageManager()

        _log(f"Activity = {act}")
        _log(f"Multiple = {multiple}")

        mimes = [m for m in (mime_types or []) if m] or ["image/*"]
        _log(f"MIME types = {mimes}")

        req_code = 13579

        def _deliver(sel):
            _log(f"DELIVER {len(sel)} item(s)")
            for i, s in enumerate(sel):
                _log(f"  [{i}] {s}")
            Clock.schedule_once(lambda *_: on_selection(list(sel)), 0)

        def _on_activity_result(requestCode, resultCode, data):
            _log(f"onActivityResult rc={requestCode} result={resultCode} data={data}")

            if requestCode != req_code:
                _log("IGNORED: requestCode mismatch")
                return

            try:
                activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass

            if resultCode != Activity.RESULT_OK or data is None:
                _log("Picker cancelled / empty")
                _deliver([])
                return

            out = []
            clip = data.getClipData()

            if clip:
                _log(f"ClipData count = {clip.getItemCount()}")
                for i in range(clip.getItemCount()):
                    uri = clip.getItemAt(i).getUri()
                    _log(f"Clip[{i}] uri = {uri}")
                    if uri:
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                _log(f"Single uri = {uri}")
                if uri:
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        # ---------- OPEN_DOCUMENT ----------
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        intent.setType(mimes[0])
        intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )

        if intent.resolveActivity(pm) is not None:
            _log("Using ACTION_OPEN_DOCUMENT")
        else:
            _log("OPEN_DOCUMENT unavailable → GET_CONTENT")
            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
            intent.setType(mimes[0])

            if intent.resolveActivity(pm) is not None:
                _log("Using ACTION_GET_CONTENT")
            else:
                _log("GET_CONTENT unavailable → ACTION_PICK")
                intent = Intent(Intent.ACTION_PICK)
                intent.setType("image/*")

                if intent.resolveActivity(pm) is None:
                    _log("❌ NO PICKER AVAILABLE")
                    return False

        chooser = Intent.createChooser(intent, JavaString("Select image(s)"))
        _log("Launching picker")
        Clock.schedule_once(lambda *_: act.startActivityForResult(chooser, req_code), 0)
        return True

    except Exception as e:
        _log(f"PICKER CRASHED: {e}")
        import traceback
        traceback.print_exc()
        return False
