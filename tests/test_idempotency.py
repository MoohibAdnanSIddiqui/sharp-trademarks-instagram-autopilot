"""Publishing the same slot twice is the single worst failure mode."""
from app.content.models import ContentBrief, PostStatus


def _brief(cid="a", slot=0):
    return ContentBrief(
        content_id=cid, date="2030-01-01", publish_time="2030-01-01T09:00:00-05:00",
        slot=slot, content_pillar="trust_and_service", objective="trust",
        content_type="single_image", topic="t", topic_key="t", hook="h",
    )


def test_slot_can_only_be_claimed_once(db):
    assert db.claim_slot("2030-01-01", 0, "a") is True
    assert db.claim_slot("2030-01-01", 0, "b") is False


def test_same_brief_may_retry_an_incomplete_claim(db):
    assert db.claim_slot("2030-01-01", 0, "a") is True
    assert db.claim_slot("2030-01-01", 0, "a") is True


def test_completed_claim_blocks_even_the_same_brief(db):
    db.claim_slot("2030-01-01", 0, "a")
    db.complete_claim("2030-01-01", 0)
    assert db.claim_slot("2030-01-01", 0, "a") is False


def test_released_claim_can_be_retaken(db):
    db.claim_slot("2030-01-01", 0, "a")
    db.release_claim("2030-01-01", 0)
    assert db.claim_slot("2030-01-01", 0, "b") is True


def test_media_id_is_unique(db):
    import sqlite3

    import pytest
    b1, b2 = _brief("a", 0), _brief("b", 1)
    for b in (b1, b2):
        b.status = PostStatus.PUBLISHED
        b.ig_media_id = "SAME"
    db.upsert(b1)
    with pytest.raises(sqlite3.IntegrityError):
        db.upsert(b2)


def test_dry_run_never_consumes_a_slot(db, brief, monkeypatch):
    from app.pipeline import Pipeline
    p = Pipeline(db)
    p.dry_run = True
    brief.slides[0].render_path = "x.jpg"
    p.publish(brief)
    # the real run must still be able to claim it
    assert db.claim_slot(brief.date, brief.slot, brief.content_id) is True
