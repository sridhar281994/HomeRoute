from __future__ import annotations

from typing import Callable, Iterable

from kivy.utils import platform

_REQ_CODE = 0xF10A
_BOUND = False
_ACTIVE: dict[int, Callable[[list[str]], None]] = {}


def _to_py_str(x) -> str:
    try:
        return str(x.toString())
    except Exception:
        try:
            return str(x)
        except Exception:
            return ""


def open_android_gallery(
    *,
    on_selection: Callable[[list[str]], None],
    multiple: bool = False,
    mime_types: Iterable[str] = ("image/*",),
    title: str = "Select file",
) -> bool:
    """
    Native Android gallery/file picker fallback using Intent + activity result.

    Returns True if the Intent was launched, else False.
    `on_selection` receives a list of content:// URIs (or empty list on cancel).
    """
    if platform != "android":
        return False

    try:
        from android import activity  # type: ignore
        from jnius import autoclass, jarray  # type: ignore
    except Exception:
        return False

    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        Activity = autoclass("android.app.Activity")
    except Exception:
        return False

    # Bind only once, route results by requestCode.
    global _BOUND

    def _handler(_activity, request_code, result_code, intent):
        try:
            req = int(request_code)
        except Exception:
            return
        cb = _ACTIVE.pop(req, None)
        if cb is None:
            return

        # If nothing else is pending, unbind to avoid leaks.
        try:
            if not _ACTIVE:
                activity.unbind(on_activity_result=_handler)
                # pylint: disable=global-statement
                global _BOUND
                _BOUND = False
        except Exception:
            pass

        try:
            if int(result_code) != int(Activity.RESULT_OK):
                cb([])
                return
        except Exception:
            cb([])
            return

        uris: list[str] = []
        try:
            if intent is None:
                cb([])
                return
            clip = intent.getClipData()
            if clip is not None:
                try:
                    n = int(clip.getItemCount())
                except Exception:
                    n = 0
                for i in range(max(0, n)):
                    try:
                        item = clip.getItemAt(i)
                        uri = item.getUri() if item is not None else None
                        s = _to_py_str(uri) if uri is not None else ""
                        if s:
                            uris.append(s)
                    except Exception:
                        continue
            else:
                uri = intent.getData()
                s = _to_py_str(uri) if uri is not None else ""
                if s:
                    uris.append(s)
        except Exception:
            uris = []

        cb(uris)

    try:
        if not _BOUND:
            activity.bind(on_activity_result=_handler)
            _BOUND = True
    except Exception:
        return False

    _ACTIVE[int(_REQ_CODE)] = on_selection

    # ACTION_OPEN_DOCUMENT is SAF-friendly and returns content:// URIs.
    try:
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        m = [str(x).strip() for x in (mime_types or []) if str(x).strip()]
        if len(m) == 1:
            intent.setType(m[0])
        else:
            intent.setType("*/*")
            arr = jarray("Ljava.lang.String;")(len(m))
            for i, v in enumerate(m):
                arr[i] = String(v)
            intent.putExtra(Intent.EXTRA_MIME_TYPES, arr)
        if multiple:
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)

        chooser = Intent.createChooser(intent, String(str(title or "Select file")))
        PythonActivity.mActivity.startActivityForResult(chooser, int(_REQ_CODE))
        return True
    except Exception:
        try:
            _ACTIVE.pop(int(_REQ_CODE), None)
        except Exception:
            pass
        return False

