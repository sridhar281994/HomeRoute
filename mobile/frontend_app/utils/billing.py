from __future__ import annotations

from typing import Optional


class BillingUnavailable(RuntimeError):
    pass


_initialized = False


def init_billing() -> None:
    """
    Initializes the Kotlin BillingBridge via PyJNIus on Android.
    Safe to call multiple times.
    """
    global _initialized
    if _initialized:
        return
    try:
        from jnius import autoclass  # type: ignore
    except Exception as e:  # pragma: no cover
        raise BillingUnavailable(f"PyJNIus not available (not running on Android build?): {e}") from e

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    BillingBridge = autoclass("org.yourapp.billing.BillingBridge")
    activity = PythonActivity.mActivity
    BillingBridge.init(activity)
    _initialized = True


def buy_plan(product_id: str) -> None:
    """
    Launches purchase flow for a subscription productId.
    """
    init_billing()
    try:
        from jnius import autoclass  # type: ignore
    except Exception as e:  # pragma: no cover
        raise BillingUnavailable(f"PyJNIus not available: {e}") from e

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    BillingBridge = autoclass("org.yourapp.billing.BillingBridge")
    activity = PythonActivity.mActivity
    BillingBridge.buy(str(product_id), activity)

