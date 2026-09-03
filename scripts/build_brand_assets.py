"""Turn the supplied logo JPEG into the transparent, colour-normalised PNG assets
the renderer composites onto every post.

Run once (or whenever the source logo changes):
    python scripts/build_brand_assets.py assets/brand/_source_logo.jpg
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

BRAND_TEAL = (13, 148, 136)     # #0d9488
BRAND_NAVY = (16, 31, 61)       # #101f3d
WHITE = (255, 255, 255)

OUT = Path("assets/brand")

# Vertical bands in the 1254x1254 source, as fractions, so the script still works
# if the source is re-exported at another size.
BAND_MARK = (0.00, 0.635)       # circular emblem
BAND_WORD = (0.635, 1.00)       # SHARP + TRADEMARKS lockup


def _alpha_from_white(rgb: np.ndarray) -> np.ndarray:
    """Alpha = how far each pixel is from paper white. Keeps antialiased edges."""
    lum = rgb.max(axis=2).astype(np.float32)
    alpha = np.clip((250.0 - lum) / 250.0 * 1.35, 0.0, 1.0)
    return (alpha * 255).astype(np.uint8)


def _normalise_colours(rgb: np.ndarray) -> np.ndarray:
    """Snap the logo's near-teal / near-navy pixels to the exact brand hexes."""
    out = rgb.copy().astype(np.float32)
    r, g, b = out[..., 0], out[..., 1], out[..., 2]
    lum = out.max(axis=2)

    ink = lum < 245
    # teal: green+blue clearly dominate red
    teal = ink & ((g + b) - 2 * r > 40)
    navy = ink & ~teal

    for mask, target in ((teal, BRAND_TEAL), (navy, BRAND_NAVY)):
        if not mask.any():
            continue
        # preserve relative shading inside the shape, but re-hue it
        shade = (lum[mask] / max(lum[mask].max(), 1.0)).reshape(-1, 1)
        shade = 0.72 + 0.28 * shade          # gentle: avoid washing out
        out[mask] = np.array(target, dtype=np.float32) * shade
    return np.clip(out, 0, 255).astype(np.uint8)


def _trim(img: Image.Image, pad: int = 6) -> Image.Image:
    bbox = img.getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.width, x1 + pad), min(img.height, y1 + pad)
    return img.crop((x0, y0, x1, y1))


def _reversed_variant(img: Image.Image) -> Image.Image:
    """White-out version for dark/navy backgrounds: navy ink -> white, teal stays teal."""
    a = np.asarray(img).astype(np.int16)
    rgb, alpha = a[..., :3], a[..., 3]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    is_teal = ((g + b) - 2 * r) > 40
    out = rgb.copy()
    out[~is_teal] = WHITE
    # lift the teal so it reads on navy
    out[is_teal] = np.clip(out[is_teal] * 1.28 + 26, 0, 255)
    return Image.fromarray(
        np.dstack([out.astype(np.uint8), alpha.astype(np.uint8)]), "RGBA"
    )


def main(src: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    arr = np.asarray(im)

    alpha = _alpha_from_white(arr)
    rgb = _normalise_colours(arr)
    full = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")

    h = full.height
    pieces = {
        "logo_full": full,
        "logo_mark": full.crop((0, int(h * BAND_MARK[0]), full.width, int(h * BAND_MARK[1]))),
        "logo_wordmark": full.crop((0, int(h * BAND_WORD[0]), full.width, int(h * BAND_WORD[1]))),
    }

    for name, img in pieces.items():
        img = _trim(img)
        img.save(OUT / f"{name}.png")
        _reversed_variant(img).save(OUT / f"{name}_reversed.png")
        print(f"  {name}.png  {img.size}   + reversed")

    # square avatar-safe mark on white, used for profile-adjacent assets
    mark = _trim(pieces["logo_mark"])
    side = max(mark.size)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
    canvas.save(OUT / "logo_mark_square_white.png")
    print(f"  logo_mark_square_white.png  {canvas.size}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "assets/brand/_source_logo.jpg")
