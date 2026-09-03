"""Turn performance data into bounded adjustments to the content plan.

Two rules keep this honest:
  * Nothing changes below `min_posts_for_insight` posts. Small samples produce
    confident nonsense.
  * A pillar's share can move by at most +/- 25% relative per review, and never
    outside a floor and ceiling. The plan drifts; it never lurches.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

from app.content.database import ContentDB
from app.utils.config import ROOT, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)
OVERRIDE_PATH = ROOT / "data" / "pillar_mix_override.json"

MAX_RELATIVE_MOVE = 0.25
FLOOR, CEILING = 0.03, 0.30


def _engagement(row: dict) -> float:
    """Saves and shares are weighted heavily: this account's job is to be kept
    and forwarded, not to collect passive likes."""
    reach = max(1, row.get("reach") or 0)
    score = (
        (row.get("saved") or 0) * 3.0
        + (row.get("shares") or 0) * 3.0
        + (row.get("comments") or 0) * 2.0
        + (row.get("likes") or 0) * 1.0
    )
    return score / reach


class StrategyReviewer:
    def __init__(self, db: ContentDB | None = None):
        self.db = db or ContentDB()
        self.settings = get_settings()
        self.min_posts = int(self.settings.get("analytics.min_posts_for_insight", 12))
        self.lookback = int(self.settings.get("analytics.lookback_days", 30))

    def analyse(self) -> dict:
        rows = self.db.performance_rows(self.lookback)
        findings: dict = {"sample_size": len(rows), "acted": False}
        if len(rows) < self.min_posts:
            findings["note"] = (
                f"{len(rows)} posts with metrics — below the {self.min_posts} needed. "
                "No plan changes made."
            )
            return findings

        by: dict[str, dict[str, list[float]]] = {
            "pillar": defaultdict(list), "format": defaultdict(list),
            "template": defaultdict(list), "objective": defaultdict(list),
            "hour": defaultdict(list),
        }
        for r in rows:
            e = _engagement(r)
            by["pillar"][r["content_pillar"]].append(e)
            by["format"][r["content_type"]].append(e)
            by["objective"][r["objective"]].append(e)
            for tid in json.loads(r["template_ids"] or "[]"):
                by["template"][tid].append(e)
            by["hour"][str(r["publish_time"])[11:13]].append(e)

        def summarise(bucket: dict[str, list[float]]) -> dict:
            return {
                k: {"n": len(v), "mean_engagement": round(statistics.mean(v), 5)}
                for k, v in sorted(bucket.items(), key=lambda kv: -statistics.mean(kv[1]))
                if len(v) >= 2
            }

        findings.update({k: summarise(v) for k, v in by.items()})
        findings["adjustments"] = self._adjust_pillars(by["pillar"])
        findings["acted"] = bool(findings["adjustments"])
        self.db.save_strategy_note(f"{self.lookback}d", findings, findings["adjustments"])
        return findings

    def _adjust_pillars(self, bucket: dict[str, list[float]]) -> dict:
        base = dict(self.settings.get("content.pillar_mix", {}) or {})
        eligible = {k: statistics.mean(v) for k, v in bucket.items() if len(v) >= 3}
        if len(eligible) < 3:
            return {}
        overall = statistics.mean(eligible.values())
        if overall <= 0:
            return {}

        moved = {}
        for pillar, share in base.items():
            if pillar not in eligible:
                continue
            ratio = eligible[pillar] / overall
            delta = max(-MAX_RELATIVE_MOVE, min(MAX_RELATIVE_MOVE, ratio - 1.0))
            new = min(CEILING, max(FLOOR, share * (1 + delta)))
            if abs(new - share) > 0.004:
                moved[pillar] = round(new, 4)

        if not moved:
            return {}
        merged = {**base, **moved}
        total = sum(merged.values())
        merged = {k: round(v / total, 4) for k, v in merged.items()}   # renormalise
        OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDE_PATH.write_text(json.dumps(merged, indent=2))
        log.info("pillar mix adjusted: %s", moved)
        return merged
