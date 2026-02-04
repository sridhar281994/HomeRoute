from __future__ import annotations

from typing import Iterable, List
from kivy.utils import platform

LOG_TAG = "ANDROID_PICKER"


def _log(msg: str) -> None:
    try:
        print(f"[{LOG_TAG}] {msg}")
    except Exception:
        pass


# ------------------------------------------------------------
# ANDROID URI → JPEG BYTES (CORE FIX)
# ------------------------------------------------------------
def android_uri_to_jpeg_bytes(uri: str) -> bytes:
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

    uri_obj = Uri.parse(str(uri))
    ins = resolver.openInputStream(uri_obj)
    if ins is None:
        raise RuntimeError("Unable to open image stream")

    try:
        bmp = BitmapFactory.decodeStream(ins)
    finally:
        try:
            ins.close()
        except Exception:
            pass

    if bmp is None:
        raise RuntimeError("Bitmap decode failed")

    # Optional downscale to avoid OOM
    try:
        w = bmp.getWidth()
        h = bmp.getHeight()
        max_side = 2048
        if w > max_side or h > max_side:
            scale = float(max_side) / max(w, h)
            bmp = Bitmap.createScaledBitmap(bmp, int(w * scale), int(h * scale), True)
    except Exception:
        pass

    baos = ByteArrayOutputStream()
    ok = bmp.compress(Bitmap.CompressFormat.JPEG, 90, baos)
    bmp.recycle()

    if not ok:
        raise RuntimeError("Bitmap compress failed")

    data = bytes(baos.toByteArray())
    if len(data) < 1024:
        raise RuntimeError("Decoded image too small")

    return data


# ------------------------------------------------------------
# ANDROID SYSTEM PICKER
# ------------------------------------------------------------
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

        # ---------- Try modern SAF picker ----------
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
            chooser = Intent.createChooser(saf_intent, JavaString("Select image(s)"))
            Clock.schedule_once(lambda *_: act.startActivityForResult(chooser, REQ_CODE), 0.15)
            return True

        # ---------- Fallback: legacy picker ----------
        legacy_intent = Intent(Intent.ACTION_GET_CONTENT)
        legacy_intent.addCategory(Intent.CATEGORY_OPENABLE)
        legacy_intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, bool(multiple))
        legacy_intent.setType(mimes[0])
        legacy_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        if legacy_intent.resolveActivity(pm) is not None:
            chooser = Intent.createChooser(legacy_intent, JavaString("Select image(s)"))
            Clock.schedule_once(lambda *_: act.startActivityForResult(chooser, REQ_CODE), 0.15)
            return True

        _log("No picker available on this device")
        return False

    except Exception as e:
        _log(f"Picker failed: {e}")
        import traceback
        traceback.print_exc()
        return False
