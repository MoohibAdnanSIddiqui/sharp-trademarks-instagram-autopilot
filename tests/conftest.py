import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("AUTO_PUBLISH", "false")
os.environ.setdefault("MEDIA_HOST_PROVIDER", "local")

import pytest  # noqa: E402

from app.content.database import ContentDB  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return ContentDB(tmp_path / "test.db")


@pytest.fixture
def brief():
    from app.content.models import ContentBrief, Slide

    return ContentBrief(
        content_id="test-1", date="2030-01-01",
        publish_time="2030-01-01T09:00:00-05:00", slot=0,
        content_pillar="trust_and_service", objective="trust",
        content_type="single_image", topic="How the filing process works",
        topic_key="filing-how-process-works", hook="Three steps, no guesswork.",
        slides=[Slide(template_id="VS01_statement", headline="Three steps, no guesswork.",
                      subhead="We tell you where you are in the process.")],
        caption="Three steps, no guesswork.\n\nWe tell you where you are at each stage.",
        cta="Start at sharptrademarks.com.", hashtags=["#trademark", "#brandprotection"],
        alt_text="Sharp Trademarks graphic.",
    )
