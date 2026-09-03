"""Duplicate prevention across text and imagery — no ML dependencies.

Text similarity blends three cheap, complementary signals:
  * word-shingle Jaccard   — catches reordered / lightly reworded sentences
  * character 4-gram cosine — catches morphological drift ("file" vs "filing")
  * token-overlap Dice      — catches short strings where shingles are sparse

Image similarity uses perceptual hashing (pHash) Hamming distance.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

_STOP = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "your", "you", "yours", "is", "are", "was", "be", "been", "it", "its", "that",
    "this", "these", "those", "as", "at", "by", "from", "can", "will", "do", "does",
    "not", "no", "if", "so", "what", "why", "how", "when", "who", "we", "our", "my",
}


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _STOP and len(w) > 2]


def _shingles(tokens: list[str], n: int = 2) -> set[str]:
    if len(tokens) < n:
        return set(tokens)
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _char_ngrams(text: str, n: int = 4) -> Counter:
    s = re.sub(r"\s+", " ", (text or "").lower().strip())
    return Counter(s[i : i + n] for i in range(max(0, len(s) - n + 1)))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _dice(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def text_similarity(x: str, y: str) -> float:
    """0.0 (unrelated) .. 1.0 (identical). Blended, weighted toward semantics."""
    if not x or not y:
        return 0.0
    if x.strip().lower() == y.strip().lower():
        return 1.0
    tx, ty = _tokens(x), _tokens(y)
    if not tx or not ty:
        return 0.0
    j = _jaccard(_shingles(tx), _shingles(ty))
    c = _cosine(_char_ngrams(x), _char_ngrams(y))
    d = _dice(set(tx), set(ty))
    return round(0.40 * j + 0.30 * c + 0.30 * d, 4)


def most_similar(candidate: str, corpus: list[str]) -> tuple[float, str]:
    best, best_text = 0.0, ""
    for other in corpus:
        s = text_similarity(candidate, other)
        if s > best:
            best, best_text = s, other
    return best, best_text


# ---------------------------------------------------------------- images
def image_phash(path: str | Path) -> str:
    import imagehash
    from PIL import Image

    with Image.open(path) as im:
        return str(imagehash.phash(im.convert("RGB"), hash_size=16))


def phash_distance(a: str, b: str) -> int:
    if len(a) != len(b):
        return 999
    try:
        ia, ib = int(a, 16), int(b, 16)
    except ValueError:
        return 999
    return bin(ia ^ ib).count("1")


class DuplicateGuard:
    """Single entry point the pipeline calls before committing new content."""

    def __init__(self, db, settings):
        self.db = db
        self.t_topic = float(settings.get("similarity.topic_threshold", 0.72))
        self.t_caption = float(settings.get("similarity.caption_threshold", 0.68))
        self.t_hook = float(settings.get("similarity.hook_threshold", 0.75))
        self.max_phash_dist = int(settings.get("similarity.image_phash_max_distance", 12))
        self.topic_cooldown_days = int(settings.get("content.topic_cooldown_days", 45))

    def check_text(self, topic: str, hook: str, caption: str, exclude_id: str = "") -> list[str]:
        """Returns a list of human-readable rejection reasons. Empty = clean."""
        reasons: list[str] = []
        rows = [r for r in self.db.recent_texts(80) if r["content_id"] != exclude_id]

        s, match = most_similar(topic, [r["topic"] for r in rows])
        if s >= self.t_topic:
            reasons.append(f"topic {s:.2f} similar to existing: {match!r}")

        s, match = most_similar(hook, [r["hook"] for r in rows])
        if s >= self.t_hook:
            reasons.append(f"hook {s:.2f} similar to existing: {match!r}")

        if caption:
            s, match = most_similar(caption, [r["caption"] or "" for r in rows])
            if s >= self.t_caption:
                reasons.append(f"caption {s:.2f} similar to an earlier caption")
        return reasons

    def check_topic_cooldown(self, topic_key: str) -> list[str]:
        if self.db.topic_used_since(topic_key, self.topic_cooldown_days):
            return [f"topic_key {topic_key!r} used within {self.topic_cooldown_days} days"]
        return []

    def check_image(self, path: str, exclude_id: str = "") -> list[str]:
        try:
            h = image_phash(path)
        except Exception:  # a hashing failure must never block publishing
            return []
        for content_id, other in self.db.all_phashes():
            if content_id == exclude_id:
                continue
            if phash_distance(h, other) <= self.max_phash_dist:
                return [f"image near-duplicate of {content_id} (phash distance <= {self.max_phash_dist})"]
        return []
