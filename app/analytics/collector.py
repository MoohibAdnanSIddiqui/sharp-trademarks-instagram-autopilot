"""Pull Instagram insights for published posts at fixed checkpoints."""
from __future__ import annotations

from app.content.database import ContentDB
from app.instagram.publisher import InstagramError, InstagramPublisher
from app.utils.config import get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)

# Metric names differ by media type and change between API versions, so the
# collector asks for a superset and keeps whatever comes back.
IMAGE_METRICS = ["reach", "likes", "comments", "saved", "shares", "total_interactions", "profile_visits"]
CAROUSEL_METRICS = ["reach", "likes", "comments", "saved", "shares", "total_interactions"]


class AnalyticsCollector:
    def __init__(self, db: ContentDB | None = None):
        self.db = db or ContentDB()
        self.api = InstagramPublisher()
        self.checkpoints = list(get_settings().get("analytics.collect_after_hours", [24, 72, 168]))

    def _fetch(self, media_id: str, metrics: list[str]) -> dict:
        try:
            data = self.api._request("GET", f"{media_id}/insights",
                                     params={"metric": ",".join(metrics)})
        except InstagramError as exc:
            # A metric unsupported for this media type fails the whole call;
            # fall back to the minimal safe set rather than losing the row.
            log.warning("insights call failed (%s) — retrying with core metrics", exc)
            try:
                data = self.api._request("GET", f"{media_id}/insights",
                                         params={"metric": "reach,likes,comments,saved"})
            except InstagramError as exc2:
                log.error("insights unavailable for %s: %s", media_id, exc2)
                return {}
        out: dict[str, int] = {}
        for entry in data.get("data", []):
            values = entry.get("values") or [{}]
            out[entry.get("name", "")] = values[0].get("value", 0)
        return out

    def run(self) -> int:
        due = self.db.due_for_metrics(self.checkpoints)
        if not due:
            log.info("no posts due for metrics collection")
            return 0
        collected = 0
        for content_id, hours in due:
            brief = self.db.get(content_id)
            if not brief or not brief.ig_media_id:
                continue
            metrics = self._fetch(
                brief.ig_media_id,
                CAROUSEL_METRICS if brief.content_type == "carousel" else IMAGE_METRICS,
            )
            if metrics:
                self.db.record_metrics(content_id, hours, metrics)
                collected += 1
                log.info("metrics %sh for %s: %s", hours, content_id, metrics)
        return collected
