from __future__ import annotations

from typing import Iterable, List

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
# ANDROID URI → JPEG BYTES (THE CORE FIX)
# ------------------------------------------------------------
def android_uri_to_jpeg_bytes(uri: str) -> bytes:
    """
    Android-native decode:
    content:// URI
        → ContentResolver.openInputStream
        → BitmapFactory.decodeStream
        → Bitmap.compress(JPEG)
        → bytes

    Works for:
    - Camera
    - Gallery
    - Google Photos
    - Android Photo Picker
    - HEIC / AVIF / WEBP
    """

    if platform != "android":
        raise RuntimeError("android_uri_to_jpeg_bytes called on non-Android")

    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    BitmapFactory = autoclass("android.graphics.BitmapFactory")
    Bitmap = autoclass("android.graphics.Bitmap")
    ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")

    act = PythonActivity.mActivity
    resolver = act.getContentResolver()

    uri_obj = Uri.parse(uri)
    ins = resolver.openInputStream(uri_obj)

    if ins is None:
        raise RuntimeError("Unable to open image stream")

    try:
        bmp = BitmapFactory.decodeStream(ins)
    finally:
        ins.close()

    if bmp is None:
        raise RuntimeError("Bitmap decode failed")

    baos = ByteArrayOutputStream()
    ok = bmp.compress(Bitmap.CompressFormat.JPEG, 90, baos)
    bmp.recycle()

    if not ok:
        raise RuntimeError("Bitmap compress failed")

    jpeg_bytes = bytes(baos.toByteArray())
    if len(jpeg_bytes) < 1024:
        raise RuntimeError("Decoded image too small")

    return jpeg_bytes


# ------------------------------------------------------------
# ANDROID SYSTEM PICKER (SAFE, MODERN)
# ------------------------------------------------------------
def android_open_gallery(
    *,
    on_selection,
    multiple: bool = False,
    mime_types: List[str] | None = None,
) -> bool:
    """
    Opens Android system picker.
    Returns ONLY content:// URIs.
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

        REQ_CODE = 13579

        def _deliver(items):
            Clock.schedule_once(lambda *_: on_selection(list(items or [])), 0)

        def _on_activity_result(requestCode, resultCode, data):
            if requestCode != REQ_CODE:
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

        mimes = [m.strip() for m in (mime_types or []) if m.strip()]
        if not mimes:
            mimes = ["image/*"]

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
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )

        if intent.resolveActivity(pm) is None:
            _log("No picker available")
            return False

        chooser = Intent.createChooser(
            intent,
            JavaString("Select image(s)"),
        )

        Clock.schedule_once(
            lambda *_: act.startActivityForResult(chooser, REQ_CODE),
            0.15,
        )
        return True

    except Exception as e:
        _log(f"Picker failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ------------------------------------------------------------
# EXAMPLE CALLBACK (CLIENT SIDE)
# ------------------------------------------------------------
def _on_images_selected(self, uris: Iterable[str]):
    _log(f"RAW URIS: {uris}")

    if not uris:
        self.show_toast("No image selected")
        return

    images: list[bytes] = []

    for uri in uris:
        try:
            jpeg_bytes = android_uri_to_jpeg_bytes(uri)
            images.append(jpeg_bytes)
        except Exception as e:
            _log(f"Image rejected: {e}")

    if not images:
        self.show_toast("Invalid image selected")
        return

    # STORE BYTES — NOT PATHS
    self.selected_images = images
    self.show_toast(f"{len(images)} image selected")
