"""Deterministic branding engine.

Gemini supplies atmosphere. THIS module supplies the brand: exact colours,
exact typography, the real logo, exact layout, exact wording. Nothing that must
be correct is ever left to a generative model.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.branding.palette import PALETTE as P
from app.branding.typography import draw_block, fit, font, layout, text_width
from app.content.models import ContentBrief, Slide
from app.utils.config import get_bible, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "assets" / "brand"

W, H = 1080, 1350
M = 84                      # safe margin
CW = W - 2 * M              # content width = 912
FOOTER_Y = H - M - 30


# --------------------------------------------------------------- helpers
def _load(name: str) -> Image.Image | None:
    p = BRAND / name
    return Image.open(p).convert("RGBA") if p.exists() else None


def _fit_cover(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale-and-crop to fill the box without distortion."""
    bw, bh = box
    scale = max(bw / img.width, bh / img.height)
    new = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    left = (new.width - bw) // 2
    top = (new.height - bh) // 2
    return new.crop((left, top, left + bw, top + bh))


def _tint_to_brand(img: Image.Image, strength: float = 0.55) -> Image.Image:
    """Pull any generated image toward the navy/teal palette so a stray warm
    background can never break the feed's colour discipline."""
    img = ImageEnhance.Color(img.convert("RGB")).enhance(0.35)
    grade = Image.new("RGB", img.size, P.navy)
    img = Image.blend(img, grade, strength * 0.45)
    return ImageEnhance.Contrast(img).enhance(1.06)


def _procedural_field(size: tuple[int, int], background: str, seed: int) -> Image.Image:
    """Fallback texture drawn from the emblem's own geometry: concentric arcs and
    rising bars. Used when Gemini is unavailable, so the pipeline never stalls."""
    w, h = size
    base = Image.new("RGB", size, P.navy if background == "navy" else P.mist)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = (seed * 2654435761) % (2**32)

    def nxt(mod: int) -> int:
        nonlocal rng
        rng = (1103515245 * rng + 12345) % (2**31)
        return rng % mod

    cx, cy = w * (0.62 + nxt(18) / 100), h * (0.66 + nxt(14) / 100)
    accent = P.teal if background == "navy" else P.teal
    for i in range(9):
        r = int(min(w, h) * (0.20 + i * 0.085))
        a = max(8, 60 - i * 6)
        start = nxt(360)
        d.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=start, end=start + 120 + nxt(140),
            fill=(*accent, a), width=max(2, 10 - i),
        )
    bw_ = int(w * 0.055)
    for i in range(4):
        bh_ = int(h * (0.10 + i * 0.075))
        x = int(cx - bw_ * 2.6 + i * bw_ * 1.45)
        d.rectangle([x, cy - bh_, x + bw_, cy], fill=(*accent, 26 + i * 7))
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    out = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
    return out


def _background(slide: Slide, background: str, seed: int, box: tuple[int, int] = (W, H)) -> Image.Image:
    src = slide.image_path
    if src and Path(src).exists():
        try:
            img = _fit_cover(Image.open(src).convert("RGB"), box)
            return _tint_to_brand(img)
        except Exception as exc:
            log.warning("background load failed (%s), using procedural field", exc)
    return _procedural_field(box, background, seed)


def _canvas(background: str) -> Image.Image:
    return Image.new("RGB", (W, H), P.navy if background == "navy" else P.paper)


def _apply_texture(canvas: Image.Image, texture: Image.Image, opacity: float) -> Image.Image:
    tex = texture.convert("RGB").resize((W, H), Image.LANCZOS)
    return Image.blend(canvas, tex, max(0.0, min(1.0, opacity)))


def _vignette(img: Image.Image, background: str, strength: float = 0.55) -> Image.Image:
    """Darken (navy) or lighten (paper) the type side so text always has contrast."""
    grad = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(grad)
    for i in range(H):
        t = i / H
        d.line([(0, i), (W, i)], fill=int(255 * strength * (1 - t * 0.35)))
    overlay = Image.new("RGB", (W, H), P.navy if background == "navy" else P.paper)
    return Image.composite(overlay, img, grad)


# --------------------------------------------------------------- chrome
def _draw_eyebrow(d: ImageDraw.ImageDraw, text: str, y: int, background: str) -> int:
    if not text:
        return y
    b = layout(text, family="body", size=26, weight="SemiBold", max_width=CW,
               tracking=0.14, upper=True, line_factor=1.0, max_lines=1)
    d.rectangle([M, y + 8, M + 46, y + 12], fill=P.teal)
    draw_block(d, b, M + 66, y, P.teal if background == "paper" else P.teal_300)
    return y + 52


def _draw_rule(d: ImageDraw.ImageDraw, y: int, width: int = 132, thickness: int = 6) -> int:
    d.rectangle([M, y, M + width, y + thickness], fill=P.teal)
    return y + thickness


def _optical_start(content_h: float, top: int = M, bottom: int = FOOTER_Y - 60,
                   bias: float = 0.44) -> int:
    """Y at which to begin a measured block so it sits optically centred.

    `bias` < 0.5 lifts the group slightly above true centre, which is where the
    eye expects it. This is what removes the dead space at the foot of
    text-light slides without letting text-heavy slides collide with the footer.
    """
    free = max(0.0, (bottom - top) - content_h)
    return int(top + free * bias)


def _draw_footer(img: Image.Image, background: str, brief: ContentBrief,
                 index: int, total: int, with_logo: bool) -> None:
    d = ImageDraw.Draw(img)
    bible = get_bible()
    site = bible["brand"]["website"]
    handle = bible["brand"]["handle"]
    fg = P.secondary_on(background)

    d.rectangle([M, FOOTER_Y - 30, W - M, FOOTER_Y - 29], fill=P.rule_on(background))

    if with_logo:
        name = "logo_wordmark_reversed.png" if background == "navy" else "logo_wordmark.png"
        logo = _load(name)
        if logo:
            target_w = 244
            logo = logo.resize((target_w, max(1, int(logo.height * target_w / logo.width))), Image.LANCZOS)
            img.paste(logo, (M, FOOTER_Y - logo.height + 6), logo)
        else:
            draw_block(d, layout(site, size=26, weight="SemiBold", max_width=400, max_lines=1),
                       M, FOOTER_Y - 26, fg)
    else:
        draw_block(d, layout(site, size=26, weight="Medium", max_width=400, max_lines=1),
                   M, FOOTER_Y - 26, fg)

    hb = layout(handle, size=26, weight="Medium", max_width=400, max_lines=1)
    d.text((W - M - text_width(handle, hb.font), FOOTER_Y - 26), handle, font=hb.font, fill=fg)

    if total > 1:
        counter = f"{index + 1:02d}/{total:02d}"
        cb = layout(counter, size=26, weight="SemiBold", max_width=200, max_lines=1, tracking=0.08)
        cw = text_width(counter, cb.font, 0.08)
        d.text((W - M - cw, M - 4), counter, font=cb.font, fill=P.secondary_on(background))


def _draw_swipe_cue(d: ImageDraw.ImageDraw, background: str) -> None:
    y = FOOTER_Y - 96
    label = "SWIPE"
    b = layout(label, size=24, weight="SemiBold", max_width=200, tracking=0.16, max_lines=1)
    lw = text_width(label, b.font, 0.16)
    x = W - M - lw - 44
    draw_block(d, b, int(x), y, P.teal if background == "paper" else P.teal_300)
    ax = W - M - 30
    d.line([(ax - 4, y + 13), (ax + 16, y + 13)], fill=P.teal, width=4)
    d.polygon([(ax + 12, y + 5), (ax + 24, y + 13), (ax + 12, y + 21)], fill=P.teal)


def _check_glyph(d: ImageDraw.ImageDraw, x: int, y: int, size: int, ok: bool) -> None:
    r = size // 2
    cx, cy = x + r, y + r
    if ok:
        d.ellipse([x, y, x + size, y + size], outline=P.teal, width=4)
        d.line([(cx - r * 0.42, cy), (cx - r * 0.08, cy + r * 0.36)], fill=P.teal, width=5)
        d.line([(cx - r * 0.08, cy + r * 0.36), (cx + r * 0.46, cy - r * 0.38)], fill=P.teal, width=5)
    else:
        d.ellipse([x, y, x + size, y + size], outline=(176, 96, 96), width=4)
        o = r * 0.40
        d.line([(cx - o, cy - o), (cx + o, cy + o)], fill=(176, 96, 96), width=5)
        d.line([(cx + o, cy - o), (cx - o, cy + o)], fill=(176, 96, 96), width=5)


# --------------------------------------------------------------- templates
# Each template returns a finished RGB image. Signature is uniform so the
# registry can dispatch on template_id alone.

def _t_statement(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "navy"
    img = _canvas(bg)
    img = _apply_texture(img, _background(slide, bg, seed), 0.30)
    img = _vignette(img, bg, 0.62)
    d = ImageDraw.Draw(img)

    head = fit(slide.headline, max_width=CW, max_height=560, start_size=104, min_size=54, max_lines=4)
    sub = (layout(slide.subhead, size=38, weight="Regular", max_width=CW - 40,
                  line_factor=1.44, max_lines=4) if slide.subhead else None)
    group = 52 + 26 + head.height + 40 + 6 + 34 + (sub.height if sub else 0)
    y = _optical_start(group, top=M, bottom=FOOTER_Y - 40, bias=0.40)

    y = _draw_eyebrow(d, slide.eyebrow or brief.content_pillar.replace("_", " "), y, bg)
    y += 26
    y = draw_block(d, head, M, y, P.paper)
    y += 40
    y = _draw_rule(d, y) + 34
    if sub:
        draw_block(d, sub, M, y, P.secondary_on(bg))
    _draw_footer(img, bg, brief, idx, total, with_logo=True)
    if total > 1 and idx == 0:
        _draw_swipe_cue(d, bg)
    return img


def _t_split(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    band_h = int(H * 0.44)
    img.paste(_background(slide, "navy", seed, (W, band_h)).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, band_h, W, band_h + 8], fill=P.teal)

    y = band_h + 8 + 56
    y = _draw_eyebrow(d, slide.eyebrow or "trademark basics", y, bg)
    y += 16
    head = fit(slide.headline, max_width=CW, max_height=300, start_size=78, min_size=46, max_lines=3)
    y = draw_block(d, head, M, y, P.navy)
    y += 30
    if slide.body or slide.subhead:
        body = layout(slide.body or slide.subhead, size=36, weight="Regular",
                      max_width=CW, line_factor=1.48, max_lines=5)
        draw_block(d, body, M, y, P.muted)
    _draw_footer(img, bg, brief, idx, total, with_logo=True)
    if total > 1 and idx == 0:
        _draw_swipe_cue(d, bg)
    return img


def _t_numbered_steps(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    d = ImageDraw.Draw(img)
    number = str(slide.fields.get("number", idx)).zfill(2)

    head = fit(slide.headline, max_width=CW, max_height=280, start_size=72, min_size=44, max_lines=3)
    body = (layout(slide.body, size=36, weight="Regular", max_width=CW,
                   line_factor=1.50, max_lines=6) if slide.body else None)
    nb = font("headline", 260, "ExtraBold")
    ink = d.textbbox((0, 0), number, font=nb)          # real glyph bounds
    numeral_h = ink[3] - ink[1]
    gap_after_numeral = 62
    group = (numeral_h + gap_after_numeral + 52 + 18 + head.height + 40 + 5 + 34
             + (body.height if body else 0))
    top = _optical_start(group, top=M, bottom=FOOTER_Y - 40, bias=0.42)

    d.text((M - 10 - ink[0], top - ink[1]), number, font=nb, fill=(226, 236, 241))

    y = top + numeral_h + gap_after_numeral
    y = _draw_eyebrow(d, slide.eyebrow or "step", y, bg)
    y += 18
    y = draw_block(d, head, M, y, P.navy)
    y += 40                                   # clearance for descenders
    y = _draw_rule(d, y, width=96, thickness=5) + 34
    if body:
        draw_block(d, body, M, y, P.muted)
    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


def _t_myth_fact(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "navy"
    img = _canvas(bg)
    img = _apply_texture(img, _background(slide, bg, seed), 0.16)
    d = ImageDraw.Draw(img)

    myth = slide.fields.get("myth", slide.subhead or "")
    fact = slide.fields.get("fact", slide.body or "")

    y = M
    if slide.eyebrow:
        y = _draw_eyebrow(d, slide.eyebrow, y, bg) + 20

    lbl = layout("MYTH", family="body", size=28, weight="Bold", max_width=300,
                 tracking=0.18, max_lines=1)
    draw_block(d, lbl, M, y, (150, 168, 190))
    y += 52
    mb = fit(myth, max_width=CW, max_height=330, start_size=64, min_size=40, max_lines=4,
             line_factor=1.14)
    end_y = draw_block(d, mb, M, y, (176, 192, 210))
    strike_y = y + int(mb.font.size * 0.47)
    for i in range(len(mb.lines)):
        lw = text_width(mb.lines[i], mb.font, mb.tracking)
        yy = strike_y + i * mb.leading
        d.line([(M, yy), (M + lw, yy)], fill=(110, 130, 155), width=3)

    mid = end_y + 56
    d.rectangle([M, mid, W - M, mid + 2], fill=P.navy_600)
    y = mid + 56

    lbl2 = layout("FACT", family="body", size=28, weight="Bold", max_width=300,
                  tracking=0.18, max_lines=1)
    d.rectangle([M, y + 9, M + 40, y + 13], fill=P.teal)
    draw_block(d, lbl2, M + 58, y, P.teal_300)
    y += 52
    fb = fit(fact, max_width=CW, max_height=FOOTER_Y - 90 - y, start_size=64, min_size=38,
             max_lines=5, line_factor=1.16)
    draw_block(d, fb, M, y, P.paper)

    _draw_footer(img, bg, brief, idx, total, with_logo=(idx == 0 or total == 1))
    return img


def _t_checklist(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    d = ImageDraw.Draw(img)

    items = slide.fields.get("items", [])[:6]
    head = fit(slide.headline, max_width=CW, max_height=250, start_size=72, min_size=44, max_lines=3)
    header_h = 52 + 18 + head.height + 26 + 5 + 44
    rows_h = min(FOOTER_Y - 60 - M - header_h, 150 * max(1, len(items)))
    top = _optical_start(header_h + rows_h, top=M, bottom=FOOTER_Y - 50, bias=0.40)

    y = _draw_eyebrow(d, slide.eyebrow or "checklist", top, bg) + 18
    y = draw_block(d, head, M, y, P.navy) + 26
    y = _draw_rule(d, y, width=96, thickness=5) + 44

    row_h = max(96, min(150, int(rows_h / max(1, len(items)))))
    for i, item in enumerate(items):
        text = item if isinstance(item, str) else item.get("text", "")
        ok = True if isinstance(item, str) else bool(item.get("ok", True))
        _check_glyph(d, M, y + 6, 46, ok)
        tb = layout(text, size=34, weight="Medium", max_width=CW - 84,
                    line_factor=1.34, max_lines=2)
        draw_block(d, tb, M + 76, y + 2, P.navy)
        if i < len(items) - 1:
            d.rectangle([M, y + row_h - 22, W - M, y + row_h - 21], fill=P.line)
        y += row_h
    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


def _t_comparison(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    d = ImageDraw.Draw(img)

    left = slide.fields.get("left", {})
    right = slide.fields.get("right", {})
    n_rows = max(len(left.get("items", [])), len(right.get("items", [])))
    head = fit(slide.headline, max_width=CW, max_height=210, start_size=68, min_size=42, max_lines=2)
    header_h = 52 + 18 + head.height + 40 + 72 + 34
    body_h = min(FOOTER_Y - 60 - M - header_h, 152 * max(1, n_rows))
    top = _optical_start(header_h + body_h, top=M, bottom=FOOTER_Y - 50, bias=0.40)

    y = _draw_eyebrow(d, slide.eyebrow or "compare", top, bg) + 18
    y = draw_block(d, head, M, y, P.navy) + 40
    col_w = (CW - 48) // 2
    lx, rx = M, M + col_w + 48

    for x, col, color in ((lx, left, P.navy), (rx, right, P.teal_700)):
        d.rectangle([x, y, x + col_w, y + 72], fill=color)
        tb = layout(col.get("title", ""), size=32, weight="Bold", max_width=col_w - 32,
                    max_lines=1, tracking=0.04, upper=True)
        draw_block(d, tb, x + 20, y + 20, P.paper)
    y += 72 + 34

    rows = n_rows
    row_h = max(84, min(152, int(body_h / max(1, rows))))
    d.rectangle([M + col_w + 23, y - 14, M + col_w + 25, y + row_h * rows - 24], fill=P.line)
    for i in range(rows):
        for x, col in ((lx, left), (rx, right)):
            items = col.get("items", [])
            if i < len(items):
                tb = layout(items[i], size=33, weight="Regular", max_width=col_w - 12,
                            line_factor=1.34, max_lines=3)
                draw_block(d, tb, x, y, P.navy if x == lx else P.navy)
        if i < rows - 1:
            d.rectangle([M, y + row_h - 26, W - M, y + row_h - 25], fill=P.line)
        y += row_h
    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


def _t_quote_stat(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "navy"
    img = _canvas(bg)
    img = _apply_texture(img, _background(slide, bg, seed), 0.22)
    img = _vignette(img, bg, 0.5)
    d = ImageDraw.Draw(img)

    body = fit(slide.headline, max_width=CW - 60, max_height=560, start_size=86,
               min_size=48, max_lines=6, line_factor=1.14)
    sub_h = 44 + 42 if slide.subhead else 0
    group = (52 + 30 if slide.eyebrow else 0) + body.height + sub_h
    y = _optical_start(group, top=M + 20, bottom=FOOTER_Y - 50, bias=0.42)
    if slide.eyebrow:
        y = _draw_eyebrow(d, slide.eyebrow, y, bg) + 30

    bar_top = y
    end = draw_block(d, body, M + 60, y, P.paper)
    d.rectangle([M, bar_top, M + 10, end - int(body.leading * 0.2)], fill=P.teal)

    if slide.subhead:
        sb = layout(slide.subhead, size=30, weight="Medium", max_width=CW - 60,
                    line_factor=1.4, max_lines=3)
        draw_block(d, sb, M + 60, end + 44, P.secondary_on(bg))
    _draw_footer(img, bg, brief, idx, total, with_logo=True)
    return img


def _t_question_answer(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    d = ImageDraw.Draw(img)

    q = fit(slide.headline, max_width=CW, max_height=300, start_size=74, min_size=44, max_lines=4)
    ab = (layout(slide.body, size=36, weight="Regular", max_width=CW,
                 line_factor=1.50, max_lines=8) if slide.body else None)
    qf = font("headline", 200, "ExtraBold")
    ink = d.textbbox((0, 0), "?", font=qf)
    glyph_h = ink[3] - ink[1]
    gap_after_glyph = 54
    group = glyph_h + gap_after_glyph + 52 + 18 + q.height + 36 + 2 + 40 + (ab.height if ab else 0)
    top = _optical_start(group, top=M, bottom=FOOTER_Y - 40, bias=0.42)

    d.text((M - 6 - ink[0], top - ink[1]), "?", font=qf, fill=(226, 236, 241))

    y = top + glyph_h + gap_after_glyph
    y = _draw_eyebrow(d, slide.eyebrow or "you asked", y, bg) + 18
    y = draw_block(d, q, M, y, P.navy) + 36
    d.rectangle([M, y, W - M, y + 2], fill=P.line)
    y += 40
    if ab:
        draw_block(d, ab, M, y, P.muted)
    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


def _t_cta_close(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "navy"
    img = _canvas(bg)
    img = _apply_texture(img, _background(slide, bg, seed), 0.18)
    d = ImageDraw.Draw(img)
    bible = get_bible()

    logo = _load("logo_full_reversed.png")
    logo_h = 0
    if logo:
        tw = 400
        logo = logo.resize((tw, max(1, int(logo.height * tw / logo.width))), Image.LANCZOS)
        logo_h = logo.height
    head_preview = fit(slide.headline or brief.cta, max_width=CW - 80, max_height=300,
                       start_size=64, min_size=38, max_lines=4, line_factor=1.2)
    group = logo_h + 90 + head_preview.height + 46 + 6 + 52 + 44
    top = _optical_start(group, top=M + 30, bottom=FOOTER_Y - 60, bias=0.42)
    if logo:
        img.paste(logo, ((W - tw) // 2, top), logo)

    y = top + logo_h + 90
    head = fit(slide.headline or brief.cta, max_width=CW - 80, max_height=300,
               start_size=64, min_size=38, max_lines=4, line_factor=1.2)
    for line in head.lines:
        lw = text_width(line, head.font, head.tracking)
        d.text(((W - lw) / 2, y), line, font=head.font, fill=P.paper)
        y += head.leading
    y += 46
    d.rectangle([(W - 132) // 2, y, (W + 132) // 2, y + 6], fill=P.teal)
    y += 52

    site = bible["brand"]["website"]
    sb = layout(site, size=36, weight="SemiBold", max_width=CW, max_lines=1, tracking=0.04)
    sw = text_width(site, sb.font, 0.04)
    draw_block(d, sb, int((W - sw) / 2), y, P.teal_300)

    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


def _t_timeline(slide: Slide, brief: ContentBrief, idx: int, total: int, seed: int) -> Image.Image:
    bg = "paper"
    img = _canvas(bg)
    d = ImageDraw.Draw(img)

    stages = slide.fields.get("stages", [])[:5]
    head = fit(slide.headline, max_width=CW, max_height=210, start_size=68, min_size=42, max_lines=2)
    header_h = 52 + 18 + head.height + 52
    body_h = min(FOOTER_Y - 60 - M - header_h, 175 * max(1, len(stages)))
    top = _optical_start(header_h + body_h, top=M, bottom=FOOTER_Y - 50, bias=0.40)

    y = _draw_eyebrow(d, slide.eyebrow or "timeline", top, bg) + 18
    y = draw_block(d, head, M, y, P.navy) + 52

    row_h = max(120, min(190, int(body_h / max(1, len(stages)))))
    spine_x = M + 21
    if stages:
        d.rectangle([spine_x - 2, y + 10, spine_x + 2, y + row_h * (len(stages) - 1) + 26],
                    fill=P.line)
    for _i, st in enumerate(stages):
        label = st.get("label", "") if isinstance(st, dict) else str(st)
        detail = st.get("detail", "") if isinstance(st, dict) else ""
        cy = y + 12
        d.ellipse([spine_x - 15, cy - 3, spine_x + 15, cy + 27], fill=P.paper, outline=P.teal, width=5)
        d.ellipse([spine_x - 6, cy + 6, spine_x + 6, cy + 18], fill=P.teal)
        lb = layout(label, family="headline", size=40, weight="Bold",
                    max_width=CW - 84, line_factor=1.18, max_lines=2)
        ny = draw_block(d, lb, M + 76, y, P.navy)
        if detail:
            db = layout(detail, size=31, weight="Regular", max_width=CW - 84,
                        line_factor=1.36, max_lines=2)
            draw_block(d, db, M + 76, ny + 8, P.muted)
        y += row_h
    _draw_footer(img, bg, brief, idx, total, with_logo=False)
    return img


TEMPLATES = {
    "VS01_statement": _t_statement,
    "VS02_split": _t_split,
    "VS03_numbered_steps": _t_numbered_steps,
    "VS04_myth_fact": _t_myth_fact,
    "VS05_checklist": _t_checklist,
    "VS06_comparison": _t_comparison,
    "VS07_quote_stat": _t_quote_stat,
    "VS08_question_answer": _t_question_answer,
    "VS09_cta_close": _t_cta_close,
    "VS10_timeline": _t_timeline,
}


class Renderer:
    def __init__(self) -> None:
        s = get_settings()
        self.quality = int(s.get("image.quality", 92))
        self.max_bytes = int(s.get("image.max_bytes", 8_000_000))
        self.out_root = ROOT / "assets" / "generated"

    def render_brief(self, brief: ContentBrief) -> list[str]:
        out_dir = self.out_root / brief.date / brief.content_id
        out_dir.mkdir(parents=True, exist_ok=True)
        total = len(brief.slides)
        paths: list[str] = []
        for i, slide in enumerate(brief.slides):
            fn = TEMPLATES.get(slide.template_id)
            if fn is None:
                log.warning("unknown template %s — falling back to VS01", slide.template_id)
                fn = _t_statement
            seed = abs(hash((brief.content_id, i))) % 100000
            img = fn(slide, brief, i, total, seed)
            path = out_dir / f"{i:02d}.jpg"
            self._save_jpeg(img, path)
            slide.render_path = str(path)
            paths.append(str(path))
        return paths

    def _save_jpeg(self, img: Image.Image, path: Path) -> None:
        """Instagram accepts JPEG only, and rejects anything over the size cap."""
        q = self.quality
        img = img.convert("RGB")
        while True:
            img.save(path, "JPEG", quality=q, optimize=True, progressive=True,
                     subsampling=0)  # 4:4:4 keeps small teal type crisp
            if path.stat().st_size <= self.max_bytes or q <= 60:
                return
            q -= 6
