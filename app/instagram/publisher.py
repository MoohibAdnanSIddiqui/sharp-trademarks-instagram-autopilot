"""Instagram Graph API publishing.

Only the official API is used. No password, no browser automation, no
unofficial library. The flow is Meta's documented two-step:

    POST /{ig-user-id}/media          -> creation_id (a container)
    POST /{ig-user-id}/media_publish  -> the live media id

Carousels add a layer: each slide becomes an is_carousel_item container, then a
CAROUSEL parent container holds the children, then the parent is published.

Two safety properties matter more than anything else here:
  * A retry never publishes twice. The (date, slot) claim in the database is
    taken before the first API call and only released if nothing was sent.
  * A container is never published until Instagram reports it FINISHED.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from app.content.models import ContentBrief
from app.utils.config import get_secrets, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)

# Meta returns these when the problem is transient.
_RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class InstagramError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None,
                 subcode: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.retryable = retryable


@dataclass
class PublishResult:
    media_id: str
    permalink: str = ""


class InstagramPublisher:
    def __init__(self) -> None:
        s = get_settings()
        sec = get_secrets()
        self.user_id = sec.ig_user_id
        self.token = sec.ig_access_token
        self.base = f"https://{sec.ig_api_host}/{sec.ig_api_version}"
        self.timeout = 60
        self.max_retries = 4
        self.container_poll_seconds = 5
        self.container_max_wait = 300
        self.dry_run = bool(s.get("publishing.dry_run", True))

    # ------------------------------------------------------------- http
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        params = kwargs.pop("params", {}) or {}
        params["access_token"] = self.token
        last: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(method, url, params=params, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last = InstagramError(f"network error: {exc}", retryable=True)
            else:
                try:
                    payload = resp.json()
                except ValueError:
                    payload = {}
                if resp.ok and "error" not in payload:
                    return payload
                err = payload.get("error", {})
                code = err.get("code")
                message = err.get("message", f"HTTP {resp.status_code}")
                retryable = resp.status_code in _RETRYABLE_HTTP or code in _RETRYABLE_CODES
                last = InstagramError(
                    f"{message} (code={code}, subcode={err.get('error_subcode')})",
                    code=code, subcode=err.get("error_subcode"), retryable=retryable,
                )
                if not retryable:
                    raise last
            wait = min(60, 2 ** attempt)
            log.warning("instagram %s %s failed (attempt %s): %s — retrying in %ss",
                        method, path, attempt, last, wait)
            time.sleep(wait)
        raise last or InstagramError("request failed")

    # ------------------------------------------------------- diagnostics
    def check_credentials(self) -> dict:
        """Confirm the token works and points at the expected account."""
        if not self.user_id or not self.token:
            raise InstagramError("IG_USER_ID and IG_ACCESS_TOKEN must both be set")
        return self._request("GET", self.user_id,
                             params={"fields": "id,username,account_type,media_count"})

    def publishing_limit(self) -> dict:
        """Meta's own count of API posts used in the rolling 24-hour window."""
        try:
            data = self._request("GET", f"{self.user_id}/content_publishing_limit",
                                 params={"fields": "config,quota_usage"})
            return (data.get("data") or [{}])[0]
        except InstagramError as exc:
            log.warning("could not read publishing limit: %s", exc)
            return {}

    # --------------------------------------------------------- containers
    def _create_container(self, image_url: str, *, caption: str = "",
                          is_carousel_item: bool = False, alt_text: str = "") -> str:
        params: dict[str, str] = {"image_url": image_url}
        if is_carousel_item:
            params["is_carousel_item"] = "true"
        else:
            if caption:
                params["caption"] = caption
            if alt_text:
                params["alt_text"] = alt_text[:1000]
        data = self._request("POST", f"{self.user_id}/media", params=params)
        if "id" not in data:
            raise InstagramError(f"container creation returned no id: {data}")
        return data["id"]

    def _create_carousel(self, children: list[str], caption: str) -> str:
        params = {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
        }
        data = self._request("POST", f"{self.user_id}/media", params=params)
        if "id" not in data:
            raise InstagramError(f"carousel container returned no id: {data}")
        return data["id"]

    def _await_ready(self, container_id: str) -> None:
        """Instagram fetches the image asynchronously. Publishing an unfinished
        container is the most common cause of a silent failure."""
        waited = 0
        while waited < self.container_max_wait:
            data = self._request("GET", container_id,
                                 params={"fields": "status_code,status"})
            status = data.get("status_code", "")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(
                    f"container {container_id} ended as {status}: {data.get('status', '')}"
                )
            time.sleep(self.container_poll_seconds)
            waited += self.container_poll_seconds
        raise InstagramError(f"container {container_id} was not ready after {waited}s")

    def _publish(self, creation_id: str) -> str:
        data = self._request("POST", f"{self.user_id}/media_publish",
                             params={"creation_id": creation_id})
        if "id" not in data:
            raise InstagramError(f"publish returned no media id: {data}")
        return data["id"]

    def _permalink(self, media_id: str) -> str:
        try:
            return self._request("GET", media_id, params={"fields": "permalink"}).get("permalink", "")
        except InstagramError:
            return ""

    # ------------------------------------------------------------- api
    def publish_brief(self, brief: ContentBrief, image_urls: list[str]) -> PublishResult:
        if not image_urls:
            raise InstagramError("no image URLs to publish")
        if any(u.startswith("file://") for u in image_urls):
            raise InstagramError(
                "refusing to publish file:// URLs — media_host.provider is 'local'. "
                "Instagram can only fetch publicly reachable HTTPS URLs."
            )
        caption = brief.caption_full

        if len(image_urls) == 1:
            container = self._create_container(image_urls[0], caption=caption,
                                               alt_text=brief.alt_text)
            self._await_ready(container)
            media_id = self._publish(container)
        else:
            children = []
            for url in image_urls[:10]:
                cid = self._create_container(url, is_carousel_item=True)
                children.append(cid)
            for cid in children:
                self._await_ready(cid)
            parent = self._create_carousel(children, caption)
            self._await_ready(parent)
            media_id = self._publish(parent)

        log.info("published media %s for %s", media_id, brief.content_id)
        return PublishResult(media_id=media_id, permalink=self._permalink(media_id))
