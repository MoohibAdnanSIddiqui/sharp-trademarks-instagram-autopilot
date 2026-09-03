"""The machine-readable contract between the strategist and the execution engine.

A ContentBrief is the single JSON object that flows:
    strategist -> gemini -> renderer -> validator -> publisher -> database
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ContentFormat(StrEnum):
    SINGLE_IMAGE = "single_image"
    CAROUSEL = "carousel"


class Objective(StrEnum):
    EDUCATE = "education"
    MYTH_BUST = "myth_bust"
    PREVENT_MISTAKE = "prevent_mistake"
    BUILD_TRUST = "trust"
    ANSWER_OBJECTION = "objection"
    AWARENESS = "awareness"


class PostStatus(StrEnum):
    PLANNED = "planned"
    GENERATED = "generated"
    VALIDATED = "validated"
    UPLOADED = "uploaded"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


@dataclass
class Slide:
    """One rendered frame. `template_id` selects a visual system from the bible."""

    template_id: str
    eyebrow: str = ""
    headline: str = ""
    subhead: str = ""
    body: str = ""
    # Template-specific structured content, e.g.
    #   {"items": [...]}  {"myth": "...", "fact": "..."}
    #   {"left": {...}, "right": {...}}  {"steps": [...]}
    fields: dict[str, Any] = field(default_factory=dict)
    image_prompt: str = ""
    image_path: str = ""          # generated background, before compositing
    render_path: str = ""         # final branded JPEG
    background: str = "auto"      # navy | paper | auto

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContentBrief:
    content_id: str
    date: str                      # YYYY-MM-DD in the configured timezone
    publish_time: str              # ISO-8601 with offset
    slot: int                      # 0-based slot within the day

    content_pillar: str
    objective: str
    content_type: str              # ContentFormat
    topic: str
    topic_key: str                 # normalised key used for cooldown matching
    hook: str

    visual_concept: str = ""
    slides: list[Slide] = field(default_factory=list)

    caption: str = ""
    cta: str = ""
    hashtags: list[str] = field(default_factory=list)
    alt_text: str = ""

    brand_requirements: list[str] = field(default_factory=list)
    negative_constraints: list[str] = field(default_factory=list)

    status: str = PostStatus.PLANNED
    generation_attempts: int = 0
    ig_media_id: str = ""
    permalink: str = ""
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    # ---- helpers -----------------------------------------------------
    @staticmethod
    def make_id(date: str, slot: int, topic: str) -> str:
        digest = hashlib.sha1(f"{date}|{slot}|{topic}".encode()).hexdigest()[:8]
        return f"{date.replace('-', '')}-{slot}-{digest}"

    @staticmethod
    def normalise_topic(topic: str) -> str:
        """Stable key for cooldown comparison: lowercase, stopword-free, sorted."""
        stop = {
            "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "your",
            "you", "is", "are", "what", "why", "how", "does", "do", "it", "that",
            "this", "with", "can", "my", "be", "if", "not",
        }
        words = re.findall(r"[a-z0-9]+", topic.lower())
        keep = sorted({w for w in words if w not in stop and len(w) > 2})
        return "-".join(keep[:8])

    @property
    def caption_full(self) -> str:
        """Caption + CTA + hashtags exactly as Instagram will receive it."""
        parts = [self.caption.strip()]
        if self.cta and self.cta.strip() not in self.caption:
            parts.append(self.cta.strip())
        if self.hashtags:
            parts.append(" ".join(self.hashtags))
        return "\n\n".join(p for p in parts if p)

    @property
    def render_paths(self) -> list[str]:
        return [s.render_path for s in self.slides if s.render_path]

    def add_error(self, message: str) -> None:
        self.errors.append(f"{datetime.utcnow().isoformat(timespec='seconds')} {message}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["slides"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in self.slides]
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> ContentBrief:
        data = dict(data)
        data["slides"] = [Slide(**s) if isinstance(s, dict) else s for s in data.get("slides", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})
