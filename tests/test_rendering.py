"""Every visual system must produce a valid, Instagram-acceptable JPEG."""
import pytest
from PIL import Image

from app.branding.renderer import TEMPLATES, Renderer
from app.validation.image_checks import validate_image


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_template_renders_a_valid_jpeg(template_id, tmp_path, brief, monkeypatch):
    from app.content.models import Slide

    slide = Slide(
        template_id=template_id, eyebrow="brand protection",
        headline="A name you build on should be a name you own",
        subhead="Registration is what makes that true.",
        body="A trademark protects the name, logo or slogan customers use to identify you.",
        fields={
            "number": 3,
            "myth": "An LLC protects the name.",
            "fact": "It registers a company with one state.",
            "items": [{"text": "The exact mark", "ok": True},
                      {"text": "Your goods and services", "ok": True},
                      {"text": "A guess at the class", "ok": False}],
            "left": {"title": "Trademark", "items": ["Names", "Logos", "Slogans"]},
            "right": {"title": "Copyright", "items": ["Writing", "Photos", "Music"]},
            "stages": [{"label": "Filing", "detail": "A serial number is issued"},
                       {"label": "Examination", "detail": "An attorney reviews it"}],
        },
    )
    brief.slides = [slide]
    r = Renderer()
    monkeypatch.setattr(r, "out_root", tmp_path)
    paths = r.render_brief(brief)

    assert len(paths) == 1
    result = validate_image(paths[0])
    assert result.ok, f"{template_id}: {result}"
    with Image.open(paths[0]) as im:
        assert im.size == (1080, 1350)
        assert im.format == "JPEG"


def test_long_headline_never_overflows(tmp_path, brief, monkeypatch):
    from app.content.models import Slide

    brief.slides = [Slide(
        template_id="VS01_statement",
        headline="Registering a limited liability company with your state of formation "
                 "protects the corporate entity itself and not the brand name under "
                 "which you actually trade in the marketplace",
        subhead="This is a deliberately long supporting line used to prove the layout "
                "engine shrinks type rather than letting it collide with the footer.",
    )]
    r = Renderer()
    monkeypatch.setattr(r, "out_root", tmp_path)
    assert validate_image(r.render_brief(brief)[0]).ok


def test_rejects_a_non_jpeg(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGB", (1080, 1350), (13, 148, 136)).save(p, "PNG")
    assert not validate_image(p).ok


def test_rejects_a_flat_image(tmp_path):
    p = tmp_path / "flat.jpg"
    Image.new("RGB", (1080, 1350), (16, 31, 61)).save(p, "JPEG", quality=92)
    r = validate_image(p)
    assert not r.ok and any("flat" in e for e in r.errors)
