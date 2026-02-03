from __future__ import annotations

import os
import time
from typing import Iterable

from kivy.utils import platform

LOG_TAG = "ANDROID_PICKER"


# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
def _log(msg: str) -> None:
    try:
        print(f"[{LOG_TAG}] {msg}")
    except Exception:
        pass


# ------------------------------------------------------------
# FILE:// STRIPPER
# ------------------------------------------------------------
def _strip_file_scheme(p: str) -> str:
    p = str(p or "").strip()
    if p.startswith("file://"):
        return p[len("file://"):]
    return p


# ------------------------------------------------------------
# ANDROID content:// → LOCAL CACHE (BYTES ONLY)
# ------------------------------------------------------------
def _android_copy_content_uri_to_cache(uri: str) -> str:
    """
    Copies content:// URI into app cache as REAL BYTES.
    No decoding. No normalization. No assumptions.
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

    # MIME (used only for extension hint)
    try:
        mime = str(resolver.getType(uri_obj) or "").strip()
    except Exception:
        mime = ""

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

    if "." not in display_name:
        if mime.startswith("image/"):
            display_name += ".jpg"
        elif mime.startswith("video/"):
            display_name += ".mp4"
        else:
            display_name += ".bin"

    cache_dir = ctx.getCacheDir()
    out_file = File(cache_dir, display_name)

    if out_file.exists():
        root, ext = os.path.splitext(display_name)
        out_file = File(
            cache_dir, f"{root}_{int(time.time() * 1000)}{ext}"
        )

    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise RuntimeError("Unable to open input stream")

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


# ------------------------------------------------------------
# PATH NORMALIZER (PRODUCTION-SAFE)
# ------------------------------------------------------------
def ensure_local_path(p: str) -> str:
    """
    Guarantees a REAL local file path with REAL bytes.
    Rejects cloud / preview / zero-byte images.
    """
    p = str(p or "").strip()
    if not p:
        raise ValueError("Empty path")

    p = _strip_file_scheme(p)

    if platform != "android":
        return p

    if p.startswith("content://"):
        local_path = _android_copy_content_uri_to_cache(p)

        # HARD GUARDS — DO NOT REMOVE
        if not os.path.exists(local_path):
            raise RuntimeError("File copy failed")

        size = os.path.getsize(local_path)
        if size < 1024:
            raise RuntimeError(
                "Selected image is not stored on device. "
                "Please download it or select from Files."
            )

        return local_path

    # file:///storage/... case
    if not os.path.exists(p):
        raise RuntimeError("Selected file does not exist")

    if os.path.getsize(p) < 1024:
        raise RuntimeError("Invalid or empty file")

    return p


def ensure_local_paths(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in paths or []:
        try:
            lp = ensure_local_path(p)
            if lp and lp not in out:
                out.append(lp)
        except Exception as e:
            _log(f"Path rejected: {p} → {e}")
    return out


# ------------------------------------------------------------
# FILE TYPE HELPERS
# ------------------------------------------------------------
def is_image_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
    }


def is_video_path(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mkv",
    }


# ------------------------------------------------------------
# ANDROID FILE-SYSTEM PICKER (NO GALLERY)
# ------------------------------------------------------------
def android_open_gallery(
    *,
    on_selection,
    multiple: bool = False,
    mime_types: list[str] | None = None,
) -> bool:
    """
    FILE-SYSTEM picker only.
    No Google Photos.
    No cloud providers.
    Stable on Android 11–14.
    """

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

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType(mimes[0])
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        if intent.resolveActivity(pm) is None:
            _log("No file picker available")
            return False

        chooser = Intent.createChooser(
            intent,
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


# ------------------------------------------------------------
# OPTIONAL CALLBACK EXAMPLE
# ------------------------------------------------------------
def _on_images_selected(self, uris):
    _log(f"RAW URIS: {uris}")

    if not uris:
        self.show_toast("No image selected")
        return

    local_files = ensure_local_paths(uris)

    _log(f"LOCAL FILES: {local_files}")

    if not local_files:
        self.show_toast(
            "Please select images stored on your device "
            "(not Google Photos cloud images)."
        )
        return

    self.selected_images = local_files
    self.show_toast(f"{len(local_files)} image selected")
