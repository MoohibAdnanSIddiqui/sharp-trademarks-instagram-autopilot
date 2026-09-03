"""Brand colours, resolved once from the Style Bible."""
from __future__ import annotations

from app.utils.config import get_bible


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


class Palette:
    def __init__(self) -> None:
        c = get_bible()["colors"]
        s = c["support"]
        self.teal = _hex(c["primary"]["hex"])
        self.navy = _hex(c["ink"]["hex"])
        self.paper = _hex(c["paper"]["hex"])
        self.navy_800 = _hex(s["navy_800"])
        self.navy_600 = _hex(s["navy_600"])
        self.teal_300 = _hex(s["teal_300"])
        self.teal_700 = _hex(s["teal_700"])
        self.mist = _hex(s["mist"])
        self.line = _hex(s["line"])
        self.muted = _hex(s["muted_text"])

    def on(self, background: str) -> tuple[int, int, int]:
        """Primary text colour for a given background family."""
        return self.paper if background == "navy" else self.navy

    def secondary_on(self, background: str) -> tuple[int, int, int]:
        return (150, 168, 190) if background == "navy" else self.muted

    def rule_on(self, background: str) -> tuple[int, int, int]:
        return self.navy_600 if background == "navy" else self.line


PALETTE = Palette()
