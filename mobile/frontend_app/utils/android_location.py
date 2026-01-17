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

