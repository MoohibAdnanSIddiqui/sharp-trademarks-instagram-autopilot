"""Planning must not repeat itself, and must not build empty slides."""
from app.content.database import ContentDB
from app.content.similarity import phash_distance, text_similarity
from app.content.strategist import Strategist


def test_thirty_days_of_planning_has_no_repeated_topic(tmp_path):
    db = ContentDB(tmp_path / "s.db")
    s = Strategist(db)
    keys = []
    for i in range(30):
        for b in s.plan_day(f"2030-0{1 + i // 28}-{(i % 28) + 1:02d}"):
            db.upsert(b)
            keys.append(b.topic_key)
    assert len(keys) == len(set(keys)), "a topic was reused inside the cooldown window"


def test_no_slide_inside_a_post_is_a_duplicate(tmp_path):
    db = ContentDB(tmp_path / "s.db")
    s = Strategist(db)
    for i in range(20):
        for b in s.plan_day(f"2030-03-{i + 1:02d}"):
            db.upsert(b)
            seen = set()
            for sl in b.slides:
                key = (sl.template_id, sl.headline, str(sl.fields))
                assert key not in seen, f"duplicate slide in {b.content_id}: {sl.template_id}"
                seen.add(key)


def test_structural_templates_always_have_their_content(tmp_path):
    db = ContentDB(tmp_path / "s.db")
    s = Strategist(db)
    for i in range(20):
        for b in s.plan_day(f"2030-04-{i + 1:02d}"):
            db.upsert(b)
            for sl in b.slides:
                if sl.template_id == "VS04_myth_fact":
                    assert sl.fields.get("myth") and sl.fields.get("fact")
                if sl.template_id == "VS10_timeline":
                    assert sl.fields.get("stages")
                if sl.template_id == "VS06_comparison":
                    assert sl.fields.get("left") and sl.fields.get("right")
                if sl.template_id == "VS05_checklist":
                    assert sl.fields.get("items")


def test_headlines_are_never_truncated_prefixes_of_their_body(tmp_path):
    db = ContentDB(tmp_path / "s.db")
    s = Strategist(db)
    for i in range(15):
        for b in s.plan_day(f"2030-05-{i + 1:02d}"):
            db.upsert(b)
            for sl in b.slides:
                if sl.headline and sl.body:
                    assert not sl.body.startswith(sl.headline[:40]), (
                        f"{sl.template_id}: body repeats the headline"
                    )


def test_planning_is_deterministic(tmp_path):
    a = Strategist(ContentDB(tmp_path / "a.db")).plan_day("2030-06-01")
    b = Strategist(ContentDB(tmp_path / "b.db")).plan_day("2030-06-01")
    assert [x.topic for x in a] == [x.topic for x in b]
    assert [x.content_type for x in a] == [x.content_type for x in b]


def test_similarity_catches_rewordings():
    assert text_similarity("Your LLC does not protect your name",
                           "An LLC will not protect your name") > 0.7
    assert text_similarity("Trademark vs copyright explained",
                           "What happens after you file") < 0.3


def test_phash_distance_is_symmetric_and_bounded():
    assert phash_distance("ff00", "ff00") == 0
    assert phash_distance("ff00", "0f00") > 0
    assert phash_distance("ff00", "toolong") == 999
