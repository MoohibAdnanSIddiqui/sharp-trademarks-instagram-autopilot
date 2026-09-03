"""Render one sample of every visual system and stitch a contact sheet.
Run: python scripts/preview_templates.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image

from app.branding.renderer import TEMPLATES, Renderer
from app.content.models import ContentBrief, Slide

SAMPLES = {
 "VS01_statement": Slide(template_id="VS01_statement", eyebrow="brand protection",
    headline="Your LLC does not protect your business name",
    subhead="An LLC registers your company with one state. It says nothing about who may use the name in your market."),
 "VS02_split": Slide(template_id="VS02_split", eyebrow="trademark basics",
    headline="A trademark protects how customers recognise you",
    body="Not the product itself. Not the idea behind it. The name, logo or slogan that tells a buyer this came from you and not someone else."),
 "VS03_numbered_steps": Slide(template_id="VS03_numbered_steps", eyebrow="step",
    headline="Search before you file",
    body="A conflicting mark already on the register is the most common reason an application never makes it past examination.",
    fields={"number": 2}),
 "VS04_myth_fact": Slide(template_id="VS04_myth_fact", eyebrow="myth check",
    fields={"myth": "If nobody else is using the name, it is free to take.",
            "fact": "Unregistered businesses can hold common-law rights in a name simply by using it in commerce first."}),
 "VS05_checklist": Slide(template_id="VS05_checklist", eyebrow="before you file",
    headline="Have these five things ready",
    fields={"items": [
        {"text": "The exact mark, spelled the way you will use it", "ok": True},
        {"text": "The goods or services it will cover", "ok": True},
        {"text": "Proof you are using it in commerce", "ok": True},
        {"text": "The legal owner's name and address", "ok": True},
        {"text": "A guess at what class you belong to", "ok": False}]}),
 "VS06_comparison": Slide(template_id="VS06_comparison", eyebrow="what covers what",
    headline="Trademark or copyright?",
    fields={"left": {"title": "Trademark", "items": ["Brand names", "Logos", "Slogans", "Product identity"]},
            "right": {"title": "Copyright", "items": ["Written work", "Photography", "Music and video", "Original artwork"]}}),
 "VS07_quote_stat": Slide(template_id="VS07_quote_stat", eyebrow="what we have seen",
    headline="The cheapest time to check a name is before you print the packaging.",
    subhead="500+ trademark applications filed"),
 "VS08_question_answer": Slide(template_id="VS08_question_answer", eyebrow="you asked",
    headline="Can I file a trademark myself?",
    body="You can. The USPTO accepts applications from owners directly. The risk is not the form — it is the description of goods and services, the classes you choose, and the specimen you submit. Those three decide whether the application survives examination."),
 "VS09_cta_close": Slide(template_id="VS09_cta_close",
    headline="Start with a search, not a guess."),
 "VS10_timeline": Slide(template_id="VS10_timeline", eyebrow="after you file",
    headline="What happens next",
    fields={"stages": [
        {"label": "Filing receipt", "detail": "You get a serial number confirming the date"},
        {"label": "Examination", "detail": "An examining attorney reviews your application"},
        {"label": "Office Action", "detail": "Issued only if something needs fixing"},
        {"label": "Publication", "detail": "Others get a window to oppose"},
        {"label": "Registration", "detail": "The certificate issues"}]}),
}

def main():
    r = Renderer()
    brief = ContentBrief(content_id="preview", date="preview",
        publish_time="2026-09-04T09:00:00-04:00", slot=0,
        content_pillar="trademark_education", objective="education",
        content_type="single_image", topic="preview", topic_key="preview",
        hook="preview", cta="Start with a search, not a guess.",
        slides=[SAMPLES[k] for k in TEMPLATES])
    paths = r.render_brief(brief)
    print(f"rendered {len(paths)} templates")

    cols, thumb_w = 5, 340
    ims = [Image.open(p) for p in paths]
    tw, th = thumb_w, int(thumb_w * 1350 / 1080)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 14, rows * th + (rows + 1) * 14), (28, 32, 38))
    for i, im in enumerate(ims):
        x = 14 + (i % cols) * (tw + 14)
        y = 14 + (i // cols) * (th + 14)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
    out = Path("assets/generated/_template_contact_sheet.jpg")
    sheet.save(out, "JPEG", quality=90)
    print("contact sheet ->", out)

if __name__ == "__main__":
    main()
