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
# 🔥 IMAGE NORMALIZATION (CRITICAL FIX)
# ------------------------------------------------------------
def _normalize_image_to_jpeg(path: str) -> str:
    """
    Converts ANY Android image (HEIC / AVIF / Google Photos proxy)
    into a REAL JPEG so PIL + Cloudinary always succeed.
    """
    try:
        from PIL import Image

        _log(f"Normalizing image → JPEG: {path}")

        img = Image.open(path)
        img = img.convert("RGB")

        out = path.rsplit(".", 1)[0] + "_normalized.jpg"
        img.save(out, "JPEG", quality=90, optimize=True)

        _log(f"Normalized image saved: {out}")
        return out
    except Exception as e:
        _log(f"Image normalization failed: {e}")
        raise RuntimeError("Invalid image file. Please choose another image.")


# ------------------------------------------------------------
# ANDROID content:// → LOCAL CACHE
# ------------------------------------------------------------
def _android_copy_content_uri_to_cache(uri: str) -> str:
    """
    Copy Android content:// URI into app cache.
    PyJNIus-safe and OEM-safe.
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

    # ---------- filename ----------
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
        out_file = File(cache_dir, f"{root}_{int(time.time()*1000)}{ext}")

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


# ------------------------------------------------------------
# PATH NORMALIZER (🔥 FIX WIRED HERE 🔥)
# ------------------------------------------------------------
def ensure_local_path(p: str) -> str:
    p = str(p or "").strip()
    if not p:
        raise ValueError("Empty path")

    p = _strip_file_scheme(p)

    if platform != "android":
        return p

    if p.startswith("content://"):
        local_path = _android_copy_content_uri_to_cache(p)

        # 🔥 ALWAYS normalize images before upload
        if is_image_path(local_path):
            return _normalize_image_to_jpeg(local_path)

        return local_path

    return p


def ensure_local_path(p: str) -> str:
    p = str(p or "").strip()
    if not p:
        raise ValueError("Empty path")

    p = _strip_file_scheme(p)

    # Non-Android → return as-is
    if platform != "android":
        return p

    # Android content:// URI
    if p.startswith("content://"):
        local_path = _android_copy_content_uri_to_cache(p)

        # 🔥 TRY normalization, but DO NOT BREAK UI if Pillow missing
        if is_image_path(local_path):
            try:
                return _normalize_image_to_jpeg(local_path)
            except Exception as e:
                _log(f"Normalization skipped, using original file: {e}")
                return local_path

        return local_path

    return p


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
        ".avif",
        ".heic",
        ".heif",
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
# ANDROID SYSTEM PICKER
# ------------------------------------------------------------
def android_open_gallery(
    *,
    on_selection,
    multiple: bool = False,
    mime_types: list[str] | None = None,
) -> bool:
    """
    Android SAF picker with OEM fallback.
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
                                uri, Intent.FLAG_GRANT_READ_URI_PERMISSION
                            )
                        except Exception:
                            pass
                        out.append(str(uri.toString()))
            else:
                uri = data.getData()
                if uri:
                    try:
                        resolver.takePersistableUriPermission(
                            uri, Intent.FLAG_GRANT_READ_URI_PERMISSION
                        )
                    except Exception:
                        pass
                    out.append(str(uri.toString()))

            _deliver(out)

        activity.bind(on_activity_result=_on_activity_result)

        mimes = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if not mimes:
            mimes = ["image/*"]

        saf_intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        saf_intent.addCategory(Intent.CATEGORY_OPENABLE)
        saf_intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))

        if len(mimes) == 1:
            saf_intent.setType(mimes[0])
        else:
            saf_intent.setType("*/*")
            arr = Array.newInstance(JavaString, len(mimes))
            for i, m in enumerate(mimes):
                Array.set(arr, i, JavaString(m))
            saf_intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)

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

        get_intent = Intent(Intent.ACTION_GET_CONTENT)
        get_intent.addCategory(Intent.CATEGORY_OPENABLE)
        get_intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        get_intent.setType(mimes[0])
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

def _on_images_selected(self, uris):
    print("RAW URIS:", uris)

    if not uris:
        self.show_toast("No image selected")
        return

    # 🔥 CRITICAL: convert content:// → real files
    local_files = ensure_local_paths(uris)

    print("LOCAL FILES:", local_files)

    if not local_files:
        self.show_toast("Invalid image selected")
        return

    # Store files for upload
    self.selected_images = local_files

    # ✅ THIS MESSAGE WAS NEVER SHOWN BEFORE BECAUSE local_files WAS EMPTY
    self.show_toast(f"{len(local_files)} image selected")

