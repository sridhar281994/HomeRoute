from __future__ import annotations

from kivy.utils import platform


def share_text(*, subject: str, text: str) -> bool:
    """
    Share text via the platform share sheet.

    - Android: launches ACTION_SEND chooser.
    - Non-Android: returns False (caller can fall back to clipboard/UI message).

    Returns True if a native share UI was launched.
    """
    subj = str(subject or "").strip() or "Share"
    body = str(text or "").strip()

    if platform != "android":
        return False

    try:
        # pyjnius is included in buildozer requirements; keep imports inside try
        # so desktop/dev runs don't fail.
        from jnius import autoclass, cast  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")

        activity = PythonActivity.mActivity

        intent = Intent()
        intent.setAction(Intent.ACTION_SEND)
        intent.setType("text/plain")
        intent.putExtra(Intent.EXTRA_SUBJECT, cast("java.lang.CharSequence", String(subj)))
        intent.putExtra(Intent.EXTRA_TEXT, cast("java.lang.CharSequence", String(body)))

        chooser = Intent.createChooser(intent, cast("java.lang.CharSequence", String(subj)))
        activity.startActivity(chooser)
        return True
    except Exception:
        return False

