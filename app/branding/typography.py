"""Measured text layout for Pillow. Everything the renderer draws goes through here,
so spacing, wrapping and optical alignment are identical on every asset."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "assets" / "fonts"

HEADLINE_FILE = FONTS / "Manrope-Variable.ttf"
BODY_FILE = FONTS / "Inter-Variable.ttf"


@lru_cache(maxsize=256)
def font(family: str, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    path = HEADLINE_FILE if family == "headline" else BODY_FILE
    f = ImageFont.truetype(str(path), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # static fallback — never fail a render over a weight
        pass
    return f


_MEASURE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def text_width(s: str, f: ImageFont.FreeTypeFont, tracking: float = 0.0) -> float:
    if not s:
        return 0.0
    w = _MEASURE.textlength(s, font=f)
    if tracking:
        w += tracking * f.size * (len(s) - 1)
    return w


def line_height(f: ImageFont.FreeTypeFont, factor: float) -> int:
    return int(round(f.size * factor))


@dataclass
class Block:
    """A laid-out run of text: the lines, their metrics and total height."""

    lines: list[str]
    font: ImageFont.FreeTypeFont
    leading: int
    tracking: float
    height: int


def wrap(text: str, f: ImageFont.FreeTypeFont, max_width: float, tracking: float = 0.0) -> list[str]:
    """Greedy wrap, with hard-splitting for words that exceed the measure."""
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        cur = ""
        for word in paragraph.split():
            trial = f"{cur} {word}".strip()
            if text_width(trial, f, tracking) <= max_width or not cur:
                cur = trial
                # a single word longer than the measure: break it
                while text_width(cur, f, tracking) > max_width and len(cur) > 1:
                    cut = len(cur) - 1
                    while cut > 1 and text_width(cur[:cut] + "-", f, tracking) > max_width:
                        cut -= 1
                    lines.append(cur[:cut] + "-")
                    cur = cur[cut:]
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


def layout(
    text: str,
    *,
    family: str = "body",
    size: int = 36,
    weight: str = "Regular",
    max_width: float = 900,
    line_factor: float = 1.42,
    tracking: float = 0.0,
    max_lines: int | None = None,
    upper: bool = False,
) -> Block:
    if upper:
        text = (text or "").upper()
    f = font(family, size, weight)
    lines = wrap(text, f, max_width, tracking)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while last and text_width(last + "…", f, tracking) > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip(" ,;:") + "…"
    lead = line_height(f, line_factor)
    return Block(lines, f, lead, tracking, lead * len(lines))


def fit(
    text: str,
    *,
    family: str = "headline",
    weight: str = "ExtraBold",
    max_width: float,
    max_height: float,
    start_size: int,
    min_size: int = 32,
    line_factor: float = 1.06,
    tracking: float = -0.015,
    max_lines: int = 4,
    step: int = 2,
) -> Block:
    """Shrink until the text fits BOTH the measure and the height budget.

    This is what stops a long headline from ever colliding with the logo — the
    layout decides the size, not the copywriter.
    """
    size = start_size
    while size >= min_size:
        f = font(family, size, weight)
        lines = wrap(text, f, max_width, tracking)
        lead = line_height(f, line_factor)
        if len(lines) <= max_lines and lead * len(lines) <= max_height:
            return Block(lines, f, lead, tracking, lead * len(lines))
        size -= step
    return layout(
        text, family=family, size=min_size, weight=weight, max_width=max_width,
        line_factor=line_factor, tracking=tracking, max_lines=max_lines,
    )


def draw_block(
    draw: ImageDraw.ImageDraw,
    block: Block,
    x: int,
    y: int,
    fill: tuple[int, int, int],
    align: str = "left",
    box_width: float | None = None,
) -> int:
    """Draw a laid-out block. Returns the y coordinate just below it."""
    cursor = y
    for line in block.lines:
        lx = float(x)
        if align in ("center", "right") and box_width:
            w = text_width(line, block.font, block.tracking)
            lx = x + (box_width - w) / (2 if align == "center" else 1)
        if block.tracking:
            for ch in line:
                draw.text((lx, cursor), ch, font=block.font, fill=fill)
                lx += _MEASURE.textlength(ch, font=block.font) + block.tracking * block.font.size
        else:
            draw.text((lx, cursor), line, font=block.font, fill=fill)
        cursor += block.leading
    return cursor
