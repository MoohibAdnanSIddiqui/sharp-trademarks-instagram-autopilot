"""Technical and brand checks on the finished JPEG, before it is ever uploaded."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.utils.config import get_settings
from app.validation.compliance import ValidationResult

# Instagram's accepted feed aspect range is roughly 4:5 to 1.91:1.
MIN_RATIO, MAX_RATIO = 0.79, 1.92
BRAND_RGB = np.array([[13, 148, 136], [16, 31, 61], [255, 255, 255]], dtype=np.float32)


def validate_image(path: str | Path) -> ValidationResult:
    r = ValidationResult()
    p = Path(path)
    if not p.exists():
        r.fail(f"{p.name}: file does not exist")
        return r

    s = get_settings()
    max_bytes = int(s.get("image.max_bytes", 8_000_000))
    size = p.stat().st_size
    if size > max_bytes:
        r.fail(f"{p.name}: {size/1e6:.1f}MB exceeds the {max_bytes/1e6:.0f}MB limit")
    if size < 15_000:
        r.fail(f"{p.name}: only {size} bytes — render probably failed")

    try:
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            fmt, (w, h) = im.format, im.size
            arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    except Exception as exc:
        r.fail(f"{p.name}: unreadable image ({exc})")
        return r

    if fmt != "JPEG":
        r.fail(f"{p.name}: format is {fmt}; Instagram accepts JPEG only")
    if w < 640:
        r.fail(f"{p.name}: width {w}px is below Instagram's 640px minimum")
    ratio = w / h
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        r.fail(f"{p.name}: aspect ratio {ratio:.3f} outside Instagram's accepted range")

    # --- brand checks -------------------------------------------------
    small = arr[::7, ::7].reshape(-1, 3)
    dist = np.linalg.norm(small[:, None, :] - BRAND_RGB[None, :, :], axis=2).min(axis=1)
    on_brand = float((dist < 90).mean())
    if on_brand < 0.55:
        r.warn(f"{p.name}: only {on_brand:.0%} of pixels sit near the brand palette")

    # A frame that is nearly one flat colour usually means the render failed.
    # Standard deviation must be measured WITHIN each channel: a solid navy fill
    # has a large spread across R/G/B but no spatial variation at all.
    spatial_std = float(small.std(axis=0).mean())
    if spatial_std < 6.0:
        r.fail(f"{p.name}: image is almost entirely flat — render likely failed")

    # Warm-cast guard: the palette forbids warm colour dominating the frame.
    warm = float(((small[:, 0] - small[:, 2]) > 45).mean())
    if warm > 0.12:
        r.warn(f"{p.name}: {warm:.0%} of pixels have a warm cast; palette is cool-only")
    return r


def validate_all(paths: list[str]) -> ValidationResult:
    out = ValidationResult()
    for p in paths:
        out.merge(validate_image(p))
    return out
