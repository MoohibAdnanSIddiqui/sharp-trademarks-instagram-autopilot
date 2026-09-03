"""The creative director, encoded.

Decides what goes out, in which pillar, in which format, on which visual system,
with which hook and caption — subject to every cooldown and balance rule in the
Style Bible. Deterministic given (date, history), so a re-run of the same day
produces the same plan rather than a second, different post.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.content.database import ContentDB
from app.content.models import ContentBrief, ContentFormat, PostStatus, Slide
from app.content.similarity import DuplicateGuard, text_similarity
from app.utils.config import get_bible, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[2]
BANK_DIR = ROOT / "config" / "bank"


def load_bank() -> list[dict]:
    items: list[dict] = []
    for path in sorted(BANK_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["items"]:
            item["content_pillar"] = data["pillar"]
            items.append(item)
    if not items:
        raise RuntimeError(f"content bank is empty — no JSON files in {BANK_DIR}")
    return items


# Caption openers rotate so the feed never develops a verbal tic.
HOOK_FRAMES = [
    "{hook}",
    "{hook}\n\nHere is what that actually means.",
    "Quick one, because it comes up constantly.\n\n{hook}",
    "{hook}\n\nAnd it costs people more than almost anything else in this process.",
    "If you take one thing from this account, take this:\n\n{hook}",
    "{hook}",
]

DISCLAIMER_PILLARS = {
    "trademark_education", "uspto_process", "myths_vs_facts",
    "search_and_clearance", "faq_and_objections", "monitoring_and_enforcement",
}


class Strategist:
    def __init__(self, db: ContentDB | None = None):
        self.settings = get_settings()
        self.bible = get_bible()
        self.db = db or ContentDB()
        self.guard = DuplicateGuard(self.db, self.settings)
        self.bank = load_bank()
        self.tz = ZoneInfo(self.settings.get("schedule.timezone", "America/New_York"))

    # ------------------------------------------------------------ timing
    def publish_times(self, date: str) -> list[datetime]:
        times = self.settings.get("schedule.post_times") or []
        per_day = int(self.settings.get("schedule.posts_per_day", 2))
        d = datetime.strptime(date, "%Y-%m-%d")
        if times and len(times) >= per_day:
            out = []
            for t in times[:per_day]:
                hh, mm = (int(x) for x in str(t).split(":"))
                out.append(d.replace(hour=hh, minute=mm, tzinfo=self.tz))
            return out
        interval = int(self.settings.get("schedule.post_interval_hours", 12))
        first = d.replace(hour=9, minute=0, tzinfo=self.tz)
        return [first + timedelta(hours=interval * i) for i in range(per_day)]

    # ------------------------------------------------------------ scoring
    def _pillar_mix(self) -> dict[str, float]:
        """Target mix, with any analytics-derived override applied.

        The reviewer writes data/pillar_mix_override.json only after enough
        posts have real metrics; until then settings.yaml governs.
        """
        base = dict(self.settings.get("content.pillar_mix", {}) or {})
        override = ROOT / "data" / "pillar_mix_override.json"
        if override.exists():
            try:
                learned = json.loads(override.read_text())
                if isinstance(learned, dict) and learned:
                    base.update({k: float(v) for k, v in learned.items() if k in base})
                    log.info("using analytics-adjusted pillar mix")
            except (json.JSONDecodeError, ValueError) as exc:
                log.warning("ignoring malformed pillar_mix_override.json: %s", exc)
        return base

    def _pillar_deficit(self) -> dict[str, float]:
        """How far each pillar is below its target share of the last 30 days."""
        target = self._pillar_mix()
        counts = self.db.pillar_counts(30)
        total = max(1, sum(counts.values()))
        return {
            pillar: share - (counts.get(pillar, 0) / total)
            for pillar, share in target.items()
        }

    def _recent_pillars(self, n: int) -> list[str]:
        return [r["content_pillar"] for r in self.db.recent_committed(n)]

    def _recent_templates(self, n: int) -> set[str]:
        used: set[str] = set()
        for row in self.db.recent_committed(n):
            used.update(json.loads(row["template_ids"] or "[]"))
        return used

    def score_item(self, item: dict, taken_this_run: set[str], recent_pillars: list[str],
                   deficits: dict[str, float]) -> float:
        pillar = item["content_pillar"]
        topic_key = ContentBrief.normalise_topic(item["topic"])

        if item["id"] in taken_this_run:
            return -1e9
        # Hard blocks
        if self.guard.check_topic_cooldown(topic_key):
            return -1e6
        cooldown = int(self.settings.get("content.pillar_cooldown_posts", 4))
        if pillar in recent_pillars[:cooldown]:
            return -1e5

        score = 100.0
        score += deficits.get(pillar, 0.0) * 400          # rebalance toward the plan
        # Prefer pillars not seen for a while
        if pillar in recent_pillars:
            score -= (len(recent_pillars) - recent_pillars.index(pillar)) * 0.5
        # Soft penalty for hooks close to anything recent
        recent_hooks = [r["hook"] for r in self.db.recent_texts(40)]
        worst = max((text_similarity(item["hook"], h) for h in recent_hooks), default=0.0)
        score -= worst * 120
        return score

    # ------------------------------------------------------------ assembly
    def _choose_format(self, item: dict, slot: int, date: str) -> str:
        mix = self.settings.get("content.format_mix", {}) or {}
        rng = random.Random(f"{date}:{slot}:{item['id']}")
        carousel_share = float(mix.get("carousel", 0.55))
        plan = item.get("template_plan") or []
        if len(plan) < 3:
            return ContentFormat.SINGLE_IMAGE
        return ContentFormat.CAROUSEL if rng.random() < carousel_share else ContentFormat.SINGLE_IMAGE

    # Each body template declares what it consumes and what it requires. The
    # planner only selects a template the item can actually feed, which is what
    # stops empty myth/fact panels and duplicated step slides.
    TEMPLATE_NEEDS = {
        "VS03_numbered_steps": {"points": 1, "requires": []},
        "VS02_split":          {"points": 2, "requires": []},
        "VS05_checklist":      {"points": 3, "requires": []},
        "VS08_question_answer":{"points": 1, "requires": []},
        "VS04_myth_fact":      {"points": 0, "requires": ["myth", "fact"]},
        "VS10_timeline":       {"points": 0, "requires": ["stages"]},
        "VS06_comparison":     {"points": 0, "requires": ["comparison"]},
        "VS07_quote_stat":     {"points": 0, "requires": []},
    }

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        """Word-safe trim. Never cuts a headline mid-word."""
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0]
        return cut.rstrip(" ,;:—-") or text[:limit]

    def _can_use(self, tid: str, item: dict, points_left: int) -> bool:
        need = self.TEMPLATE_NEEDS.get(tid)
        if need is None:
            return False
        if any(not item.get(k) for k in need["requires"]):
            return False
        return points_left >= need["points"]

    def _plan_carousel(self, item: dict, date: str, slot: int) -> list[str]:
        """Choose cover + body + closer, allocating distinct content to each."""
        cfg = self.settings.get("content.carousel", {}) or {}
        lo, hi = int(cfg.get("min_slides", 5)), int(cfg.get("max_slides", 8))
        plan = list(item.get("template_plan") or ["VS01_statement"])
        closer = "VS09_cta_close"

        cover = plan[0]
        # The cover consumes one point as its supporting line, unless it is a
        # self-contained panel that carries its own content.
        cover_points = 0 if cover in ("VS04_myth_fact", "VS07_quote_stat", "VS09_cta_close") else 1
        points_left = max(0, len(item.get("key_points", [])) - cover_points)

        candidates = [t for t in plan[1:] if t != closer]
        # Numbered steps is always available as filler; it varies by numeral.
        candidates += ["VS03_numbered_steps"] * 4

        body: list[str] = []
        used_structural: set[str] = set()
        for tid in candidates:
            if len(body) >= hi - 2:
                break
            if tid != "VS03_numbered_steps" and tid in used_structural:
                continue          # a structural panel repeated would be identical
            if not self._can_use(tid, item, points_left):
                continue
            body.append(tid)
            points_left -= self.TEMPLATE_NEEDS[tid]["points"]
            if tid != "VS03_numbered_steps":
                used_structural.add(tid)

        if len(body) + 2 < lo:
            return []             # not enough distinct content — post as a single image
        return [cover, *body, closer]

    def _templates_for(self, item: dict, fmt: str, date: str, slot: int) -> list[str]:
        plan = list(item.get("template_plan") or ["VS01_statement"])
        rng = random.Random(f"tpl:{date}:{slot}:{item['id']}")
        if fmt == ContentFormat.SINGLE_IMAGE:
            over_used = self._recent_templates(
                int(self.settings.get("content.template_cooldown_posts", 5))
            )
            usable = [
                t for t in plan
                if t != "VS09_cta_close"
                and (t == "VS01_statement" or self._can_use(t, item, len(item.get("key_points", []))))
            ] or ["VS01_statement"]
            fresh = [t for t in usable if t not in over_used]
            return [rng.choice(fresh or usable)]
        return self._plan_carousel(item, date, slot)

    def _build_slides(self, item: dict, templates: list[str]) -> list[Slide]:
        points = list(item.get("key_points", []))
        pillar_label = item["content_pillar"].replace("_", " ")
        slides: list[Slide] = []
        cursor = 0
        step_no = 1

        def take(n: int) -> list[str]:
            nonlocal cursor
            chunk = points[cursor : cursor + n]
            cursor += len(chunk)
            return chunk

        for idx, tid in enumerate(templates):
            slide = Slide(template_id=tid)
            first = idx == 0

            if tid == "VS09_cta_close":
                slide.headline = item.get("cta", "Protect the name before you build on it.")

            elif tid == "VS04_myth_fact":
                slide.eyebrow = "myth check"
                slide.fields = {"myth": item.get("myth", ""), "fact": item.get("fact", "")}
                if first:
                    take(0)

            elif tid == "VS07_quote_stat":
                slide.eyebrow = "worth remembering"
                slide.headline = item["hook"]

            elif tid == "VS10_timeline":
                slide.eyebrow = "the sequence"
                slide.headline = item.get("timeline_title", "How it runs")
                slide.fields = {"stages": item.get("stages", [])[:5]}

            elif tid == "VS06_comparison":
                cmp_data = item.get("comparison") or {}
                slide.eyebrow = "what covers what"
                slide.headline = self._trim(item.get("comparison_title", item["topic"]), 58)
                slide.fields = cmp_data

            elif tid == "VS05_checklist":
                chunk = take(3) or points[:3]
                slide.eyebrow = pillar_label if first else "the short version"
                slide.headline = (
                    item["hook"] if first
                    else item.get("checklist_title", "What this means in practice")
                )
                slide.fields = {"items": [{"text": p, "ok": True} for p in chunk]}

            elif tid == "VS08_question_answer":
                chunk = take(1)
                slide.eyebrow = "you asked"
                slide.headline = item.get("question") or self._trim(item["topic"], 62) + "?"
                slide.body = chunk[0] if chunk else (points[0] if points else "")

            elif tid == "VS02_split":
                chunk = take(2)
                slide.eyebrow = pillar_label
                slide.headline = item["hook"] if first else (chunk[0] if chunk else item["topic"])
                if first:
                    slide.body = chunk[0] if chunk else ""
                else:
                    slide.body = chunk[1] if len(chunk) > 1 else ""

            elif first:
                slide.eyebrow = pillar_label
                slide.headline = item["hook"]
                got = take(1)
                slide.subhead = got[0] if got else ""

            else:  # VS03_numbered_steps
                slide.template_id = "VS03_numbered_steps"
                chunk = take(1)
                text = chunk[0] if chunk else ""
                head, sep, tail = text.partition(" — ")
                slide.eyebrow = "step" if item["content_pillar"] == "uspto_process" else "point"
                # No truncation: the renderer auto-fits the type size instead, so a
                # headline is never a cut-off prefix of the body beneath it.
                slide.headline = head if sep else text
                slide.body = tail
                slide.fields = {"number": step_no}
                step_no += 1

            slides.append(slide)

        # Any body slide that ended up with no content at all is dropped rather
        # than published empty.
        return [
            s for i, s in enumerate(slides)
            if i == 0 or s.template_id == "VS09_cta_close"
            or s.headline or s.body or s.fields
        ]

    # ------------------------------------------------------------ copy
    def build_caption(self, item: dict, date: str, slot: int) -> tuple[str, str]:
        rng = random.Random(f"cap:{date}:{slot}:{item['id']}")
        frame = HOOK_FRAMES[rng.randrange(len(HOOK_FRAMES))]
        opener = frame.format(hook=item["hook"])
        body = item.get("caption_body", "")
        parts = [opener, body]
        if item["content_pillar"] in DISCLAIMER_PILLARS:
            variants = self.bible["legal_positioning"]["disclaimer_variants"]
            parts.append(variants[rng.randrange(len(variants))])
        caption = "\n\n".join(p.strip() for p in parts if p and p.strip())
        cta = item.get("cta", "Start with a search at sharptrademarks.com.")
        return caption, cta

    def build_hashtags(self, item: dict, date: str, slot: int) -> list[str]:
        cfg = self.settings.get("content.hashtags", {}) or {}
        if not cfg.get("enabled", True):
            return []
        h = self.bible["hashtags"]
        rng = random.Random(f"tag:{date}:{slot}:{item['id']}")
        lo, hi = int(cfg.get("min", 8)), int(cfg.get("max", 14))
        target = rng.randint(lo, hi)

        pillar_pool = {
            "trademark_education": ["legal", "business"],
            "costly_mistakes": ["business", "legal"],
            "myths_vs_facts": ["business", "branding"],
            "search_and_clearance": ["legal", "branding"],
            "naming_and_branding": ["branding", "business"],
            "uspto_process": ["legal", "business"],
            "monitoring_and_enforcement": ["commerce", "legal"],
            "faq_and_objections": ["business", "branding"],
            "trust_and_service": ["business", "commerce"],
        }.get(item["content_pillar"], ["business", "branding"])

        tags = list(h["core"])
        for pool_name in pillar_pool:
            pool = list(h["pools"].get(pool_name, []))
            rng.shuffle(pool)
            tags += pool
        # de-duplicate, drop banned, truncate
        seen: set[str] = set()
        out: list[str] = []
        banned = set(h.get("banned", []))
        for t in tags:
            if t in seen or t in banned:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= target:
                break
        return out

    def build_alt_text(self, item: dict, slides: list[Slide]) -> str:
        first = slides[0] if slides else None
        headline = (first.headline if first else item["hook"])[:110]
        return (f"Sharp Trademarks graphic on deep navy. Headline reads: {headline}. "
                f"Topic: {item['topic']}.")[:990]

    # ------------------------------------------------------------ plan
    def plan_day(self, date: str) -> list[ContentBrief]:
        blackout = set(self.settings.get("schedule.blackout_dates", []) or [])
        if date in blackout:
            log.info("%s is a configured blackout date — no posts planned", date)
            return []

        times = self.publish_times(date)
        deficits = self._pillar_deficit()
        recent_pillars = self._recent_pillars(12)
        taken: set[str] = set()
        briefs: list[ContentBrief] = []

        for slot, when in enumerate(times):
            scored = sorted(
                ((self.score_item(i, taken, recent_pillars, deficits), i) for i in self.bank),
                key=lambda p: p[0], reverse=True,
            )
            best_score, item = scored[0]
            if best_score <= -1e5:
                # Everything is on cooldown: fall back to the least recently used topic.
                log.warning("all bank items on cooldown for slot %s — using LRU fallback", slot)
                used = {r["topic_key"]: r["date"] for r in self.db.recent_texts(200)}
                item = min(
                    (i for i in self.bank if i["id"] not in taken),
                    key=lambda i: used.get(ContentBrief.normalise_topic(i["topic"]), "0000-00-00"),
                )
            taken.add(item["id"])
            recent_pillars.insert(0, item["content_pillar"])

            fmt = self._choose_format(item, slot, date)
            templates = self._templates_for(item, fmt, date, slot)
            if not templates:                       # too little distinct content
                fmt = ContentFormat.SINGLE_IMAGE
                templates = self._templates_for(item, fmt, date, slot)
            slides = self._build_slides(item, templates)
            caption, cta = self.build_caption(item, date, slot)

            brief = ContentBrief(
                content_id=ContentBrief.make_id(date, slot, item["id"]),
                date=date,
                publish_time=when.isoformat(),
                slot=slot,
                content_pillar=item["content_pillar"],
                objective=item.get("objective", "education"),
                content_type=fmt,
                topic=item["topic"],
                topic_key=ContentBrief.normalise_topic(item["topic"]),
                hook=item["hook"],
                visual_concept=item.get("visual_concept", ""),
                slides=slides,
                caption=caption,
                cta=cta,
                hashtags=self.build_hashtags(item, date, slot),
                alt_text=self.build_alt_text(item, slides),
                brand_requirements=[
                    "logo composited by Python, never generated",
                    "exact brand hexes #0d9488 / #101f3d / #ffffff",
                    "Manrope headline, Inter body",
                    "no pricing anywhere",
                ],
                negative_constraints=self.bible["imagery"]["forbidden"],
                status=PostStatus.PLANNED,
            )
            briefs.append(brief)
        return briefs
