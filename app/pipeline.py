"""End-to-end orchestration: plan -> generate -> render -> validate -> publish.

Every stage is separately runnable so a GitHub Actions workflow can fail at one
step without redoing the others, and so a human can inspect the output between
stages during the rollout.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.branding.renderer import Renderer
from app.content.database import ContentDB
from app.content.models import ContentBrief, PostStatus
from app.content.similarity import DuplicateGuard, image_phash
from app.content.strategist import Strategist
from app.generation.gemini_client import GeminiImageClient, GeminiUnavailable
from app.instagram.media_host import MediaHostError, get_media_host
from app.instagram.publisher import InstagramError, InstagramPublisher
from app.utils.config import ROOT, get_secrets, get_settings
from app.utils.logging import get_logger
from app.validation.compliance import ComplianceValidator, ValidationResult
from app.validation.image_checks import validate_all

log = get_logger(__name__)
CALENDAR = ROOT / "data" / "content_calendar.json"

# Templates whose slides are pure typography — a generated background would only
# reduce contrast, so they are rendered on flat brand colour.
FLAT_TEMPLATES = {
    "VS03_numbered_steps", "VS05_checklist", "VS06_comparison",
    "VS08_question_answer", "VS10_timeline",
}


class Pipeline:
    def __init__(self, db: ContentDB | None = None):
        self.settings = get_settings()
        self.db = db or ContentDB()
        self.strategist = Strategist(self.db)
        self.renderer = Renderer()
        self.validator = ComplianceValidator()
        self.guard = DuplicateGuard(self.db, self.settings)
        self.tz = ZoneInfo(self.settings.get("schedule.timezone", "America/New_York"))
        self.dry_run = bool(self.settings.get("publishing.dry_run", True))
        self.auto_publish = bool(self.settings.get("publishing.auto_publish", False))
        self.max_attempts = int(self.settings.get("publishing.max_generation_attempts", 3))

    def today(self) -> str:
        return datetime.now(self.tz).date().isoformat()

    # ------------------------------------------------------------- plan
    def plan(self, date: str | None = None) -> list[ContentBrief]:
        date = date or self.today()
        briefs = self.strategist.plan_day(date)
        for b in briefs:
            result = self.validator.validate(b)
            if not result.ok:
                b.status = PostStatus.FAILED
                b.add_error(f"compliance: {result}")
                log.error("plan rejected %s — %s", b.content_id, result)
            elif result.warnings:
                log.warning("%s warnings: %s", b.content_id, "; ".join(result.warnings))
            self.db.upsert(b)

        CALENDAR.parent.mkdir(parents=True, exist_ok=True)
        calendar = json.loads(CALENDAR.read_text()) if CALENDAR.exists() else {}
        calendar[date] = [
            {"content_id": b.content_id, "slot": b.slot, "pillar": b.content_pillar,
             "format": b.content_type, "topic": b.topic, "publish_time": b.publish_time,
             "status": str(b.status)}
            for b in briefs
        ]
        CALENDAR.write_text(json.dumps(calendar, indent=2))
        log.info("planned %s post(s) for %s", len(briefs), date)
        return briefs

    # --------------------------------------------------------- generate
    def generate(self, brief: ContentBrief) -> ContentBrief:
        """Generate backgrounds, render branded JPEGs, validate the result."""
        work_dir = ROOT / "assets" / "generated" / brief.date / brief.content_id / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)

        gemini: GeminiImageClient | None = None
        if get_secrets().gemini_api_key:
            gemini = GeminiImageClient()
        else:
            log.warning("GEMINI_API_KEY not set — using the procedural brand texture")

        for slide in brief.slides:
            if slide.template_id in FLAT_TEMPLATES:
                continue
            background = "paper" if slide.template_id == "VS02_split" else "navy"
            concept = brief.visual_concept or "Abstract concentric arcs over a deep field"
            slide.image_prompt = (
                gemini.build_prompt(concept, background) if gemini
                else f"[procedural fallback] {concept}"
            )
            if not gemini:
                continue
            target = work_dir / f"{brief.slides.index(slide):02d}_bg.jpg"
            try:
                slide.image_path = gemini.generate(
                    slide.image_prompt, target,
                    reference_images=[str(ROOT / "assets" / "brand" / "logo_mark.png")],
                )
            except GeminiUnavailable as exc:
                log.warning("gemini unavailable for %s: %s — procedural fallback",
                            brief.content_id, exc)
                brief.add_error(f"gemini: {exc}")

        for attempt in range(1, self.max_attempts + 1):
            brief.generation_attempts = attempt
            paths = self.renderer.render_brief(brief)
            image_result = validate_all(paths)
            if image_result.ok:
                dupes = self.guard.check_image(paths[0], exclude_id=brief.content_id)
                if dupes:
                    image_result.warn(dupes[0])
                break
            log.warning("render attempt %s failed validation: %s", attempt, image_result)
            brief.add_error(f"image validation: {image_result}")
        else:
            brief.status = PostStatus.FAILED
            self.db.upsert(brief)
            return brief

        for i, path in enumerate(brief.render_paths):
            try:
                self.db.record_image_hash(brief.content_id, i, image_phash(path))
            except Exception:
                pass

        compliance = self.validator.validate(brief)
        if not compliance.ok:
            brief.status = PostStatus.FAILED
            brief.add_error(f"compliance: {compliance}")
            log.error("%s failed compliance after render: %s", brief.content_id, compliance)
        else:
            brief.status = PostStatus.VALIDATED
        self.db.upsert(brief)
        return brief

    # ---------------------------------------------------------- publish
    def _rate_limit_ok(self, brief: ContentBrief) -> ValidationResult:
        r = ValidationResult()
        cap = int(self.settings.get("publishing.max_posts_per_24h", 4))
        recent = self.db.published_in_last_hours(24)
        if len(recent) >= cap:
            r.fail(f"local safety cap reached: {len(recent)} posts in the last 24h (cap {cap})")
        gap = int(self.settings.get("publishing.min_minutes_between_posts", 240))
        if recent:
            last = datetime.fromisoformat(recent[0]["published_at"])
            mins = (datetime.now(last.tzinfo) - last).total_seconds() / 60
            if mins < gap:
                r.fail(f"only {mins:.0f} minutes since the last post (minimum {gap})")
        return r

    def publish(self, brief: ContentBrief) -> ContentBrief:
        if brief.status == PostStatus.FAILED:
            log.error("refusing to publish %s — it failed an earlier stage", brief.content_id)
            return brief

        compliance = self.validator.validate(brief)
        if not compliance.ok:
            brief.status = PostStatus.FAILED
            brief.add_error(f"compliance at publish: {compliance}")
            self.db.upsert(brief)
            return brief

        if not brief.render_paths:
            brief.status = PostStatus.FAILED
            brief.add_error("no rendered images to publish")
            self.db.upsert(brief)
            return brief

        # Dry run stops here — deliberately before the idempotency claim, so a
        # dry run never consumes a slot the real run would need.
        if self.dry_run or not self.auto_publish:
            brief.status = PostStatus.DRY_RUN
            self.db.upsert(brief)
            log.info("DRY RUN — %s (%s, %s slide(s)) not sent. dry_run=%s auto_publish=%s",
                     brief.content_id, brief.content_type, len(brief.slides),
                     self.dry_run, self.auto_publish)
            return brief

        limits = self._rate_limit_ok(brief)
        if not limits.ok:
            brief.status = PostStatus.SKIPPED
            brief.add_error(f"rate limit: {limits}")
            self.db.upsert(brief)
            log.warning("skipping %s — %s", brief.content_id, limits)
            return brief

        if not self.db.claim_slot(brief.date, brief.slot, brief.content_id):
            brief.status = PostStatus.SKIPPED
            brief.add_error("slot already claimed — duplicate publish prevented")
            self.db.upsert(brief)
            return brief

        try:
            urls = get_media_host().publish(brief.render_paths)
        except MediaHostError as exc:
            self.db.release_claim(brief.date, brief.slot)   # nothing was sent to Meta
            brief.status = PostStatus.FAILED
            brief.add_error(f"media host: {exc}")
            self.db.upsert(brief)
            log.error("media hosting failed for %s: %s", brief.content_id, exc)
            return brief

        brief.status = PostStatus.UPLOADED
        self.db.upsert(brief)

        try:
            result = InstagramPublisher().publish_brief(brief, urls)
        except InstagramError as exc:
            # The claim is intentionally NOT released: a failure after the first
            # API call may still have created media. A human decides.
            brief.status = PostStatus.FAILED
            brief.add_error(f"instagram: {exc}")
            self.db.upsert(brief)
            log.error("publish failed for %s: %s", brief.content_id, exc)
            return brief

        brief.ig_media_id = result.media_id
        brief.permalink = result.permalink
        brief.status = PostStatus.PUBLISHED
        self.db.upsert(brief)
        self.db.complete_claim(brief.date, brief.slot)
        return brief

    # -------------------------------------------------------------- run
    def run_slot(self, date: str | None = None, slot: int | None = None) -> list[ContentBrief]:
        """Plan if needed, then generate and publish the slot(s) that are due."""
        date = date or self.today()
        planned = [
            r for r in self.db.recent(50)
            if r["date"] == date and r["status"] not in (PostStatus.FAILED, PostStatus.SKIPPED)
        ]
        briefs = ([ContentBrief.from_dict(json.loads(r["brief_json"])) for r in planned]
                  or self.plan(date))

        out = []
        for brief in sorted(briefs, key=lambda b: b.slot):
            if slot is not None and brief.slot != slot:
                continue
            if brief.status in (PostStatus.PUBLISHED,):
                log.info("%s already published — skipping", brief.content_id)
                out.append(brief)
                continue
            if brief.status != PostStatus.VALIDATED:
                brief = self.generate(brief)
            out.append(self.publish(brief))
        return out

    def due_slot(self, grace_minutes: int = 90) -> int | None:
        """Which slot is due right now, if any."""
        now = datetime.now(self.tz)
        for i, when in enumerate(self.strategist.publish_times(self.today())):
            if when <= now <= when + timedelta(minutes=grace_minutes):
                return i
        return None
