"""Long-lived token refresh.

Meta long-lived tokens last around 60 days. This runs weekly so the token is
always fresh, and prints the new value ONLY as a masked confirmation — the
workflow writes the real value straight into a GitHub Secret via the API.
"""
from __future__ import annotations

import requests

from app.utils.config import get_secrets
from app.utils.logging import get_logger

log = get_logger(__name__)


def refresh_long_lived_token() -> dict:
    sec = get_secrets()
    missing = sec.missing_for("refresh_token")
    if missing:
        raise RuntimeError(f"cannot refresh token, missing: {', '.join(missing)}")

    if sec.ig_api_host == "graph.instagram.com":
        # Instagram Login: the token refreshes itself.
        url = "https://graph.instagram.com/refresh_access_token"
        params = {"grant_type": "ig_refresh_token", "access_token": sec.ig_access_token}
    else:
        # Facebook Login: exchange for a fresh long-lived token.
        url = f"https://graph.facebook.com/{sec.ig_api_version}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": sec.meta_app_id,
            "client_secret": sec.meta_app_secret,
            "fb_exchange_token": sec.ig_access_token,
        }

    resp = requests.get(url, params=params, timeout=45)
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"token refresh failed: {data.get('error', data)}")
    days = int(data.get("expires_in", 0)) // 86400
    log.info("token refreshed, valid for about %s days", days)
    return {"access_token": data["access_token"], "expires_in_days": days}
