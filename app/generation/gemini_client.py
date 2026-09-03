"""Gemini image generation with retries, model fallback and a hard safety net.

Design notes
------------
* Two call paths. The modern `client.interactions.create` path is primary; the
  `models.generate_content` path is the fallback. The Gemini SDK has changed
  shape more than once, and this pipeline runs unattended twice a day — one
  broken call signature must not stop the feed.
* If both paths fail, the caller falls back to the procedural brand texture in
  the renderer. A post always ships.
* Prompts are BUILT here from the Style Bible, never freehand, so every image
  inherits the same composition, palette and negative constraints.
"""
from __future__ import annotations

import base64
import random
import time
from pathlib import Path

from app.utils.config import get_bible, get_secrets, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)

_ASPECT = {(1080, 1350): "4:5", (1080, 1080): "1:1", (1080, 1920): "9:16"}


class GeminiUnavailable(RuntimeError):
    """Raised when every path and every retry has been exhausted."""


class GeminiImageClient:
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.get("gemini.model", "gemini-3.1-flash-image")
        self.fallback_model = s.get("gemini.fallback_model", "gemini-2.5-flash-image")
        self.image_size = s.get("gemini.image_size", "2K")
        self.aspect = s.get("gemini.aspect_ratio", "4:5")
        self.timeout = int(s.get("gemini.timeout_seconds", 120))
        self.max_retries = int(s.get("gemini.max_retries", 4))
        self._client = None

    # ---------------------------------------------------------- client
    @property
    def client(self):
        if self._client is None:
            from google import genai

            key = get_secrets().gemini_api_key
            if not key:
                raise GeminiUnavailable("GEMINI_API_KEY is not set")
            self._client = genai.Client(api_key=key)
        return self._client

    # ---------------------------------------------------------- prompts
    def build_prompt(self, visual_concept: str, background: str = "navy") -> str:
        """Compose a Style-Bible-constrained prompt. Never called with raw user text."""
        b = get_bible()
        img = b["imagery"]
        comp = img["composition_defaults"]
        ground = (
            "deep navy #101f3d dominant, teal #0d9488 used sparingly as accent light"
            if background == "navy"
            else "near-white and cool light grey dominant, teal #0d9488 as a restrained accent"
        )
        return "\n".join(
            [
                "Editorial background artwork for a professional brand-protection company.",
                f"SUBJECT: {visual_concept.strip()}",
                f"PALETTE: {ground}. {img['color_direction']}",
                f"COMPOSITION: {comp['negative_space']}. Focal interest {comp['focal_placement']}.",
                f"LIGHT: {comp['lighting']}. Depth of field: {comp['depth_of_field']}.",
                f"FINISH: {comp['grain']} grain, matte, premium print quality, no gloss.",
                "ABSOLUTELY NO TEXT of any kind: no letters, words, numbers, captions, "
                "signage, watermarks, labels or logos anywhere in the image.",
                "AVOID: " + "; ".join(img["forbidden"]) + ".",
                "The image is a BACKGROUND only. Leave the upper-left half visually calm "
                "and uncluttered so headline typography can be placed over it later.",
            ]
        )

    # ---------------------------------------------------------- generate
    def generate(self, prompt: str, out_path: str | Path, reference_images: list[str] | None = None) -> str:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            model = self.model if attempt <= max(1, self.max_retries - 1) else self.fallback_model
            for path_name, fn in (("interactions", self._via_interactions), ("generate_content", self._via_generate_content)):
                try:
                    data = fn(prompt, model, reference_images or [])
                    if data and len(data) > 2048:
                        out.write_bytes(data)
                        log.info("gemini ok: model=%s path=%s attempt=%s bytes=%s",
                                 model, path_name, attempt, len(data))
                        return str(out)
                    raise RuntimeError(f"{path_name} returned no usable image data")
                except Exception as exc:  # try the other path before backing off
                    last_error = exc
                    log.warning("gemini %s failed (attempt %s, model %s): %s",
                                path_name, attempt, model, exc)
            sleep = min(60, (2 ** attempt) + random.uniform(0, 1.5))
            log.info("gemini backoff %.1fs", sleep)
            time.sleep(sleep)

        raise GeminiUnavailable(f"image generation failed after {self.max_retries} attempts: {last_error}")

    # ---- path A: interactions API ---------------------------------
    def _via_interactions(self, prompt: str, model: str, refs: list[str]) -> bytes:
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for ref in refs[:3]:
            p = Path(ref)
            if p.exists():
                parts.append({
                    "type": "image",
                    "data": base64.b64encode(p.read_bytes()).decode(),
                    "mime_type": "image/png" if p.suffix.lower() == ".png" else "image/jpeg",
                })
        result = self.client.interactions.create(
            model=model,
            input=parts,
            response_format={
                "type": "image",
                "aspect_ratio": self.aspect,
                "image_size": self.image_size,
                "mime_type": "image/jpeg",
            },
            timeout=self.timeout,
        )
        return self._extract(result)

    # ---- path B: generate_content API -----------------------------
    def _via_generate_content(self, prompt: str, model: str, refs: list[str]) -> bytes:
        from google.genai import types

        contents: list = [prompt]
        for ref in refs[:3]:
            p = Path(ref)
            if p.exists():
                contents.append(
                    types.Part.from_bytes(
                        data=p.read_bytes(),
                        mime_type="image/png" if p.suffix.lower() == ".png" else "image/jpeg",
                    )
                )
        resp = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=self.aspect,
                    image_size=self.image_size,
                ),
            ),
        )
        return self._extract(resp)

    # ---- response shape tolerance ---------------------------------
    @staticmethod
    def _extract(result) -> bytes:
        """Pull image bytes out of whichever response shape the SDK returned."""
        oi = getattr(result, "output_image", None)
        if oi is not None:
            data = getattr(oi, "data", None) or getattr(oi, "image_bytes", None)
            if isinstance(data, (bytes, bytearray)):
                return bytes(data)
            if isinstance(data, str):
                return base64.b64decode(data)

        for cand in getattr(result, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
                if inline is not None:
                    data = getattr(inline, "data", None)
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                    if isinstance(data, str):
                        return base64.b64decode(data)
                blob = getattr(part, "as_image", None)
                if callable(blob):
                    try:
                        im = blob()
                        raw = getattr(im, "image_bytes", None)
                        if raw:
                            return bytes(raw)
                    except Exception:
                        pass

        for attr in ("output", "outputs", "images"):
            seq = getattr(result, attr, None) or []
            for item in seq if isinstance(seq, (list, tuple)) else []:
                data = getattr(item, "data", None) or getattr(item, "image_bytes", None)
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
                if isinstance(data, str):
                    return base64.b64decode(data)

        raise RuntimeError("no image payload found in Gemini response")


def aspect_for(width: int, height: int) -> str:
    return _ASPECT.get((width, height), "4:5")
