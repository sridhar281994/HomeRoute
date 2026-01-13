from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import google_play_package_name, google_play_service_account_file


class GooglePlayNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _publisher_client():
    """
    Lazily builds the Android Publisher client.

    We keep imports inside the function so deployments without the deps can still run
    (as long as they don't call subscription verification).
    """
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:  # pragma: no cover
        raise GooglePlayNotConfigured(f"Google Play validation deps missing: {e}") from e

    sa_file = google_play_service_account_file()
    pkg = google_play_package_name()
    if not pkg:
        raise GooglePlayNotConfigured("GOOGLE_PLAY_PACKAGE_NAME not configured")
    if not sa_file:
        raise GooglePlayNotConfigured("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE not configured")

    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def verify_subscription_with_google_play(*, purchase_token: str, product_id: str) -> dict[str, Any]:
    """
    Calls Google Play Developer API to verify a subscription purchase token.
    """
    pkg = google_play_package_name()
    if not pkg:
        raise GooglePlayNotConfigured("GOOGLE_PLAY_PACKAGE_NAME not configured")

    client = _publisher_client()
    result = (
        client.purchases()
        .subscriptions()
        .get(
            packageName=pkg,
            subscriptionId=product_id,
            token=purchase_token,
        )
        .execute()
    )
    return dict(result or {})

