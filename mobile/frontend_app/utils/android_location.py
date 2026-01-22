from __future__ import annotations

from kivy.utils import platform


def get_last_known_location() -> tuple[float, float] | None:
    """
    Best-effort last known location (Android only).
    Requires location permissions to already be granted.
    """
    if platform != "android":
        return None
    try:
        from jnius import autoclass, cast  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        act = PythonActivity.mActivity
        lm = cast("android.location.LocationManager", act.getSystemService(Context.LOCATION_SERVICE))
        providers = lm.getProviders(True)
        best = None
        for i in range(providers.size()):
            p = providers.get(i)
            loc = lm.getLastKnownLocation(p)
            if loc is None:
                continue
            if best is None or loc.getAccuracy() < best.getAccuracy():
                best = loc
        if best is None:
            return None
        return float(best.getLatitude()), float(best.getLongitude())
    except Exception:
        return None


def open_location_settings() -> None:
    """
    Best-effort: open Android Location settings so the user can enable GPS.
    No-op on non-Android platforms.
    """
    if platform != "android":
        return
    try:
        from jnius import autoclass  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")

        act = PythonActivity.mActivity
        intent = Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)
        act.startActivity(intent)
    except Exception:
        # Never crash UI if Intent fails.
        return

