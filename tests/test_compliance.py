"""The rules that must never regress: no pricing, no guarantees, no false
authority, and a disclaimer on every legal-education post."""
import pytest

from app.validation.compliance import ComplianceValidator

BLOCKED = [
    "Register your trademark starting from $35.",
    "Trademark search from $149 today.",
    "Monitoring is $249 per quarter.",
    "We guarantee your application will be approved.",
    "100% approval rate on every filing.",
    "Our success rate is 98%.",
    "Sharp Trademarks is a law firm associated with the Federal Office.",
    "We are USPTO-endorsed.",
    "Rated 4.9 out of 5 by 150 clients.",
    "Risk-free trademark registration.",
    "We are your attorney and will represent you in court.",
]

ALLOWED = [
    "Our attorneys review every application before it is filed.",
    "USPTO filing fees are set by the government and are separate.",
    "500+ trademark applications filed.",
    "Educational information, not legal advice.",
    "A trademark protects the name customers use to find you.",
]


@pytest.mark.parametrize("text", BLOCKED)
def test_blocked_claims_are_rejected(text):
    assert not ComplianceValidator().check_text(text, "t").ok, f"should have blocked: {text}"


@pytest.mark.parametrize("text", ALLOWED)
def test_allowed_claims_pass(text):
    r = ComplianceValidator().check_text(text, "t")
    assert r.ok, f"should have allowed: {text} -> {r}"


def test_legal_education_post_requires_disclaimer(brief):
    brief.content_pillar = "trademark_education"
    r = ComplianceValidator().validate(brief)
    assert not r.ok
    assert any("not-legal-advice" in e for e in r.errors)

    brief.caption += "\n\nEducational information, not legal advice."
    assert ComplianceValidator().validate(brief).ok


def test_caption_length_limit(brief):
    brief.caption = "word " * 500
    r = ComplianceValidator().validate(brief)
    assert not r.ok and any("2200" in e for e in r.errors)


def test_banned_hashtags_rejected(brief):
    brief.hashtags = ["#trademark", "#follow4follow"]
    assert not ComplianceValidator().validate(brief).ok


def test_carousel_slide_count_enforced(brief):
    from app.content.models import Slide
    brief.content_type = "carousel"
    brief.slides = [Slide(template_id="VS01_statement", headline=f"s{i}") for i in range(12)]
    r = ComplianceValidator().validate(brief)
    assert not r.ok and any("2-10" in e for e in r.errors)


def test_every_bank_item_is_compliant():
    """The whole content bank must pass, or an autonomous run could publish it."""
    import os
    import tempfile

    from app.content.database import ContentDB
    from app.content.strategist import Strategist
    with tempfile.TemporaryDirectory() as d:
        s = Strategist(ContentDB(os.path.join(d, "t.db")))
        v = ComplianceValidator()
        failures = []
        for item in s.bank:
            blob = " ".join([
                item["hook"], item.get("caption_body", ""), item.get("cta", ""),
                " ".join(item.get("key_points", [])),
                item.get("myth", ""), item.get("fact", ""),
            ])
            r = v.check_text(blob, item["id"])
            if not r.ok:
                failures.append((item["id"], r.errors))
        assert not failures, f"non-compliant bank items: {failures}"
