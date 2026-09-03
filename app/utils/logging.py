"""Structured logging with automatic secret redaction."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

_SECRET_ENV_KEYS = (
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "IG_ACCESS_TOKEN", "META_APP_SECRET",
    "META_APP_ID", "GITHUB_TOKEN", "S3_SECRET_ACCESS_KEY", "S3_ACCESS_KEY_ID",
)
# Catches tokens that appear in URLs/JSON even if they were never in os.environ.
_PATTERNS = [
    re.compile(r"(access_token=)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(client_secret=)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})\b"),
    re.compile(r"\b(EAA[0-9A-Za-z]{20,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b"),
]


def redact(text: str) -> str:
    if not text:
        return text
    for key in _SECRET_ENV_KEYS:
        val = os.getenv(key)
        if val and len(val) > 6:
            text = text.replace(val, "***REDACTED***")
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "***REDACTED***", text)
    return text


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str))


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        icon = {"DEBUG": "·", "INFO": "→", "WARNING": "!", "ERROR": "✗", "CRITICAL": "✗"}.get(
            record.levelname, "·"
        )
        base = f"{icon} {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return redact(base)


_CONFIGURED = False


def setup_logging(level: str = "INFO", as_json: bool | None = None, file: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    if as_json is None:
        as_json = bool(os.getenv("CI"))

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(_JsonFormatter() if as_json else _TextFormatter())
    stream.addFilter(_RedactingFilter())
    root.addHandler(stream)

    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(_JsonFormatter())
        fh.addFilter(_RedactingFilter())
        root.addHandler(fh)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
