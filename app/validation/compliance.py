"""Legal, brand and pricing compliance gate.

Nothing reaches Instagram without passing this. It is deliberately blunt: a
FAIL blocks the post outright rather than degrading it, because an unattended
system publishing an unlawful claim is worse than an unattended system that
skips a slot.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.content.models import ContentBrief
from app.utils.config import get_bible, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)

# Money in any form. Deliberately broad — the brand rule is zero pricing.
_MONEY = re.compile(
    r"(\$\s?\d|\b\d+\s?(?:usd|dollars?)\b|\bstarting (?:from|at)\b|"
    r"\bper (?:quarter|month|year)\b|\bflat fee\b|\bfee schedule\b|"
    r"\bprice[sd]?\b|\bpricing\b|\bcosts? you\b|\baffordable rates\b)",
    re.I,
)
# The one permitted mention of government fees, with no amount attached.
_FEE_EXCEPTION = re.compile(r"\bUSPTO filing fees?\b|\bgovernment filing fees?\b|\bfiling fee\b", re.I)

_GUARANTEE = re.compile(
    r"\b(guarantee[ds]?|guaranteeing|100\s?%|risk[- ]free|never (?:rejected|refused)|"
    r"always approved|approval rate|success rate|we win|bulletproof)\b", re.I,
)
_PERCENT_CLAIM = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%", re.I)
_ENDORSEMENT = re.compile(
    r"\b(government[- ]approved|federally endorsed|official (?:uspto|government) "
    r"(?:partner|agency)|uspto[- ]endorsed|approved by the uspto|"
    r"associated with the federal office)\b", re.I,
)
_TESTIMONIAL = re.compile(
    r"\b(\d(?:\.\d)?\s?(?:out of|/)\s?5|\b\d\s?stars?\b|rated \d|trustpilot|"
    r"add your verified review platform)\b", re.I,
)


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def merge(self, other: ValidationResult) -> ValidationResult:
        self.ok = self.ok and other.ok
        self.errors += other.errors
        self.warnings += other.warnings
        return self

    def __str__(self) -> str:
        parts = []
        if self.errors:
            parts.append("ERRORS: " + " | ".join(self.errors))
        if self.warnings:
            parts.append("WARNINGS: " + " | ".join(self.warnings))
        return "; ".join(parts) or "clean"


class ComplianceValidator:
    def __init__(self) -> None:
        self.bible = get_bible()
        self.settings = get_settings()
        self.mode = self.settings.get("brand.legal_positioning", "hybrid")
        lp = self.bible["legal_positioning"]
        self.forbidden_framing = [f.lower() for f in lp["forbidden_framing"]]
        self.prohibited_claims = [c.lower() for c in self.bible["prohibited_claims"]]
        self.words_to_avoid = [w.lower() for w in self.bible["voice"]["words_to_avoid"]]
        self.banned_tags = set(self.bible["hashtags"].get("banned", []))
        self.verified = [f["claim"].lower() for f in self.bible["verified_facts"]]

    # ---------------------------------------------------------- text
    def check_text(self, text: str, where: str) -> ValidationResult:
        r = ValidationResult()
        low = (text or "").lower()

        # --- pricing: absolute ---
        for m in _MONEY.finditer(text or ""):
            span = text[max(0, m.start() - 40) : m.end() + 40]
            if _FEE_EXCEPTION.search(span) and not re.search(r"\$\s?\d|\b\d+\s?(?:usd|dollars)", m.group(0), re.I):
                continue          # "USPTO filing fees" with no amount is allowed
            r.fail(f"{where}: pricing language {m.group(0)!r} — the brand rule is zero pricing")

        # --- guarantees and outcome claims ---
        for m in _GUARANTEE.finditer(text or ""):
            r.fail(f"{where}: outcome/guarantee claim {m.group(0)!r}")
        for m in _PERCENT_CLAIM.finditer(text or ""):
            r.fail(f"{where}: unverifiable statistic {m.group(0)!r}")
        for m in _ENDORSEMENT.finditer(text or ""):
            r.fail(f"{where}: implies government affiliation or endorsement — {m.group(0)!r}")
        for m in _TESTIMONIAL.finditer(text or ""):
            r.fail(f"{where}: review/rating claim {m.group(0)!r} is not verified")

        # --- legal positioning ---
        if self.mode != "law_firm":
            for phrase in self.forbidden_framing:
                if phrase in low:
                    r.fail(f"{where}: forbidden legal framing {phrase!r} for mode {self.mode!r}")
        if self.mode == "strict" and re.search(r"\battorney|lawyer|law firm\b", low):
            r.fail(f"{where}: attorney reference not permitted in strict mode")

        for claim in self.prohibited_claims:
            if claim in low:
                r.fail(f"{where}: prohibited claim {claim!r}")

        # --- numeric claims must be on the verified list ---
        for m in re.finditer(r"\b(\d[\d,]{1,6}\+?)\s+([a-z][a-z ]{3,40})", low):
            fragment = f"{m.group(1)} {m.group(2)}".strip()
            if not any(fragment[:16] in v for v in self.verified):
                r.warn(f"{where}: numeric claim {fragment!r} is not on the verified-facts list")

        # --- voice ---
        for word in self.words_to_avoid:
            if re.search(rf"\b{re.escape(word)}\b", low):
                r.warn(f"{where}: off-voice word {word!r}")
        return r

    # ---------------------------------------------------------- brief
    def validate(self, brief: ContentBrief) -> ValidationResult:
        result = ValidationResult()

        result.merge(self.check_text(brief.caption, "caption"))
        result.merge(self.check_text(brief.cta, "cta"))
        result.merge(self.check_text(brief.hook, "hook"))
        result.merge(self.check_text(brief.alt_text, "alt_text"))
        for i, slide in enumerate(brief.slides):
            blob = " ".join(
                [slide.eyebrow, slide.headline, slide.subhead, slide.body, str(slide.fields)]
            )
            result.merge(self.check_text(blob, f"slide{i}"))

        # --- disclaimer requirement ---
        needs_disclaimer = brief.content_pillar in {
            "trademark_education", "uspto_process", "myths_vs_facts",
            "search_and_clearance", "faq_and_objections", "monitoring_and_enforcement",
        }
        if needs_disclaimer:
            variants = [v.lower() for v in self.bible["legal_positioning"]["disclaimer_variants"]]
            if not any(v in brief.caption.lower() for v in variants):
                result.fail("caption: legal-education post is missing the not-legal-advice line")

        # --- hashtags ---
        bad = [t for t in brief.hashtags if t in self.banned_tags]
        if bad:
            result.fail(f"hashtags: banned tags {bad}")
        if len(brief.hashtags) > 30:
            result.fail("hashtags: Instagram allows at most 30")
        if len(set(brief.hashtags)) != len(brief.hashtags):
            result.warn("hashtags: contains duplicates")

        # --- Instagram hard limits ---
        if len(brief.caption_full) > 2200:
            result.fail(f"caption: {len(brief.caption_full)} chars exceeds Instagram's 2200 limit")
        if brief.content_type == "carousel" and not (2 <= len(brief.slides) <= 10):
            result.fail(f"carousel must have 2-10 slides, has {len(brief.slides)}")
        if brief.content_type == "single_image" and len(brief.slides) != 1:
            result.fail(f"single image post must have exactly 1 slide, has {len(brief.slides)}")

        # --- empty content ---
        for i, slide in enumerate(brief.slides):
            if not (slide.headline or slide.body or slide.fields):
                result.fail(f"slide{i}: no content")
        return result
