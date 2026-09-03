"""SQLite content memory. Every post the system has ever planned lives here.

Two guarantees this module exists to provide:
  1. Nothing is published twice — `ig_media_id` and the publish-claim row are unique.
  2. Nothing repeats — every planner decision consults this history first.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.content.models import ContentBrief, PostStatus
from app.utils.logging import get_logger

log = get_logger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS posts (
    content_id           TEXT PRIMARY KEY,
    date                 TEXT NOT NULL,
    publish_time         TEXT NOT NULL,
    slot                 INTEGER NOT NULL,
    content_pillar       TEXT NOT NULL,
    objective            TEXT NOT NULL,
    content_type         TEXT NOT NULL,
    topic                TEXT NOT NULL,
    topic_key            TEXT NOT NULL,
    hook                 TEXT NOT NULL,
    visual_concept       TEXT,
    template_ids         TEXT,
    image_prompts        TEXT,
    image_paths          TEXT,
    caption              TEXT,
    cta                  TEXT,
    hashtags             TEXT,
    alt_text             TEXT,
    status               TEXT NOT NULL,
    generation_attempts  INTEGER DEFAULT 0,
    ig_media_id          TEXT,
    permalink            TEXT,
    errors               TEXT,
    brief_json           TEXT,
    created_at           TEXT NOT NULL,
    published_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_date      ON posts(date);
CREATE INDEX IF NOT EXISTS idx_posts_status    ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_pillar    ON posts(content_pillar);
CREATE INDEX IF NOT EXISTS idx_posts_topic_key ON posts(topic_key);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_media_id
    ON posts(ig_media_id) WHERE ig_media_id IS NOT NULL AND ig_media_id != '';

-- One row per slot per day. Its existence is the idempotency lock that stops a
-- retried workflow run from publishing the same slot twice.
CREATE TABLE IF NOT EXISTS publish_claims (
    date        TEXT NOT NULL,
    slot        INTEGER NOT NULL,
    content_id  TEXT NOT NULL,
    claimed_at  TEXT NOT NULL,
    completed   INTEGER DEFAULT 0,
    PRIMARY KEY (date, slot)
);

CREATE TABLE IF NOT EXISTS image_hashes (
    content_id  TEXT NOT NULL,
    slide_index INTEGER NOT NULL,
    phash       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (content_id, slide_index),
    FOREIGN KEY (content_id) REFERENCES posts(content_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hash_phash ON image_hashes(phash);

CREATE TABLE IF NOT EXISTS metrics (
    content_id      TEXT NOT NULL,
    collected_at    TEXT NOT NULL,
    hours_since     INTEGER NOT NULL,
    reach           INTEGER,
    impressions     INTEGER,
    likes           INTEGER,
    comments        INTEGER,
    saved           INTEGER,
    shares          INTEGER,
    profile_visits  INTEGER,
    total_interactions INTEGER,
    raw             TEXT,
    PRIMARY KEY (content_id, hours_since),
    FOREIGN KEY (content_id) REFERENCES posts(content_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS strategy_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    window     TEXT NOT NULL,
    findings   TEXT NOT NULL,
    adjustments TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    command    TEXT NOT NULL,
    ok         INTEGER,
    detail     TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ContentDB:
    def __init__(self, path: str | Path = "data/content_history.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ---------------- writes ----------------------------------------
    def upsert(self, brief: ContentBrief) -> None:
        row = {
            "content_id": brief.content_id,
            "date": brief.date,
            "publish_time": brief.publish_time,
            "slot": brief.slot,
            "content_pillar": brief.content_pillar,
            "objective": brief.objective,
            "content_type": brief.content_type,
            "topic": brief.topic,
            "topic_key": brief.topic_key,
            "hook": brief.hook,
            "visual_concept": brief.visual_concept,
            "template_ids": json.dumps([s.template_id for s in brief.slides]),
            "image_prompts": json.dumps([s.image_prompt for s in brief.slides]),
            "image_paths": json.dumps([s.render_path for s in brief.slides]),
            "caption": brief.caption,
            "cta": brief.cta,
            "hashtags": json.dumps(brief.hashtags),
            "alt_text": brief.alt_text,
            "status": str(brief.status),
            "generation_attempts": brief.generation_attempts,
            "ig_media_id": brief.ig_media_id or None,
            "permalink": brief.permalink,
            "errors": json.dumps(brief.errors),
            "brief_json": brief.to_json(indent=0),
            "created_at": brief.created_at,
            "published_at": _now() if brief.status == PostStatus.PUBLISHED else None,
        }
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        updates = ", ".join(
            f"{c}=excluded.{c}" for c in row if c not in ("content_id", "created_at")
        )
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO posts ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(content_id) DO UPDATE SET {updates}",
                row,
            )

    def record_image_hash(self, content_id: str, slide_index: int, phash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO image_hashes VALUES (?,?,?,?)",
                (content_id, slide_index, phash, _now()),
            )

    def record_metrics(self, content_id: str, hours_since: int, metrics: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO metrics
                   (content_id, collected_at, hours_since, reach, impressions, likes,
                    comments, saved, shares, profile_visits, total_interactions, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    content_id, _now(), hours_since,
                    metrics.get("reach"), metrics.get("impressions"), metrics.get("likes"),
                    metrics.get("comments"), metrics.get("saved"), metrics.get("shares"),
                    metrics.get("profile_visits"), metrics.get("total_interactions"),
                    json.dumps(metrics),
                ),
            )

    def log_run(self, command: str, ok: bool, detail: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO run_log (started_at, command, ok, detail) VALUES (?,?,?,?)",
                (_now(), command, int(ok), detail[:2000]),
            )

    def save_strategy_note(self, window: str, findings: dict, adjustments: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO strategy_notes (created_at, window, findings, adjustments) VALUES (?,?,?,?)",
                (_now(), window, json.dumps(findings), json.dumps(adjustments)),
            )

    # ---------------- publish idempotency ---------------------------
    def claim_slot(self, date: str, slot: int, content_id: str) -> bool:
        """Atomically claim a (date, slot). False means someone already has it."""
        with self.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO publish_claims (date, slot, content_id, claimed_at) VALUES (?,?,?,?)",
                    (date, slot, content_id, _now()),
                )
                return True
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT content_id, completed FROM publish_claims WHERE date=? AND slot=?",
                    (date, slot),
                ).fetchone()
                # A stale, incomplete claim for the SAME brief may be retried.
                if existing and existing["content_id"] == content_id and not existing["completed"]:
                    return True
                log.warning(
                    "Slot %s/%s already claimed by %s (completed=%s) — refusing duplicate publish",
                    date, slot, existing["content_id"] if existing else "?",
                    existing["completed"] if existing else "?",
                )
                return False

    def complete_claim(self, date: str, slot: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE publish_claims SET completed=1 WHERE date=? AND slot=?", (date, slot)
            )

    def release_claim(self, date: str, slot: int) -> None:
        """Only for a claim that failed before any API call was made."""
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM publish_claims WHERE date=? AND slot=? AND completed=0", (date, slot)
            )

    # ---------------- reads -----------------------------------------
    def get(self, content_id: str) -> ContentBrief | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT brief_json FROM posts WHERE content_id=?", (content_id,)
            ).fetchone()
        return ContentBrief.from_dict(json.loads(row["brief_json"])) if row else None

    def recent(self, limit: int = 40, statuses: tuple[str, ...] | None = None) -> list[dict]:
        q = "SELECT * FROM posts"
        params: list[Any] = []
        if statuses:
            q += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params += list(statuses)
        q += " ORDER BY publish_time DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def recent_committed(self, limit: int = 40) -> list[dict]:
        """Posts that actually went out (or would have, in dry run)."""
        return self.recent(
            limit,
            statuses=(PostStatus.PUBLISHED, PostStatus.DRY_RUN, PostStatus.UPLOADED, PostStatus.VALIDATED),
        )

    def pillar_counts(self, days: int = 30) -> dict[str, int]:
        since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content_pillar, COUNT(*) n FROM posts "
                "WHERE date >= ? AND status NOT IN ('failed','skipped') GROUP BY content_pillar",
                (since,),
            ).fetchall()
        return {r["content_pillar"]: r["n"] for r in rows}

    def template_counts(self, last_n_posts: int = 20) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.recent_committed(last_n_posts):
            for tid in json.loads(row["template_ids"] or "[]"):
                counts[tid] = counts.get(tid, 0) + 1
        return counts

    def topic_used_since(self, topic_key: str, days: int) -> bool:
        since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM posts WHERE topic_key=? AND date >= ? "
                "AND status NOT IN ('failed','skipped') LIMIT 1",
                (topic_key, since),
            ).fetchone()
        return row is not None

    def recent_texts(self, limit: int = 60) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content_id, topic, topic_key, hook, caption FROM posts "
                "WHERE status NOT IN ('failed','skipped') ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def all_phashes(self, limit: int = 400) -> list[tuple[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content_id, phash FROM image_hashes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(r["content_id"], r["phash"]) for r in rows]

    def published_in_last_hours(self, hours: int) -> list[dict]:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content_id, published_at FROM posts "
                "WHERE status='published' AND published_at IS NOT NULL AND published_at >= ? "
                "ORDER BY published_at DESC",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def due_for_metrics(self, checkpoints: list[int]) -> list[tuple[str, int]]:
        """(content_id, hours_since) pairs whose metrics window has opened."""
        out: list[tuple[str, int]] = []
        now = datetime.now(UTC)
        with self.connect() as conn:
            posts = conn.execute(
                "SELECT content_id, published_at FROM posts "
                "WHERE status='published' AND ig_media_id IS NOT NULL AND published_at IS NOT NULL"
            ).fetchall()
            have = {
                (r["content_id"], r["hours_since"])
                for r in conn.execute("SELECT content_id, hours_since FROM metrics").fetchall()
            }
        for p in posts:
            published = datetime.fromisoformat(p["published_at"])
            age_h = (now - published).total_seconds() / 3600
            for cp in checkpoints:
                if age_h >= cp and (p["content_id"], cp) not in have:
                    out.append((p["content_id"], cp))
        return out

    def performance_rows(self, days: int = 30) -> list[dict]:
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.content_id, p.content_pillar, p.content_type, p.objective,
                          p.template_ids, p.hook, p.publish_time,
                          m.reach, m.likes, m.comments, m.saved, m.shares,
                          m.total_interactions, m.hours_since
                   FROM posts p JOIN metrics m ON m.content_id = p.content_id
                   WHERE p.status='published' AND p.published_at >= ?
                   AND m.hours_since = (SELECT MAX(hours_since) FROM metrics WHERE content_id=p.content_id)""",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]
