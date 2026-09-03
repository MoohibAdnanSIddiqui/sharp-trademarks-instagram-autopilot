"""Configuration: settings.yaml + Brand Style Bible + environment overrides.

Precedence (highest first):
    1. Environment variable  (UPPER_SNAKE_CASE of the dotted path, or a shortcut)
    2. config/settings.yaml
    3. Hard-coded fallback in the caller

Secrets are NEVER read from settings.yaml — only from the environment.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

try:  # optional: only needed for local development
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "config" / "settings.yaml"
BIBLE_PATH = ROOT / "config" / "brand_style_bible.json"

# Short, memorable env names that map onto dotted config paths.
_ENV_SHORTCUTS: dict[str, str] = {
    "DRY_RUN": "publishing.dry_run",
    "AUTO_PUBLISH": "publishing.auto_publish",
    "POSTS_PER_DAY": "schedule.posts_per_day",
    "POST_INTERVAL_HOURS": "schedule.post_interval_hours",
    "TIMEZONE": "schedule.timezone",
    "LOG_LEVEL": "logging.level",
    "GEMINI_MODEL": "gemini.model",
    "MEDIA_HOST_PROVIDER": "media_host.provider",
    "GITHUB_REPOSITORY": "media_host.github.repo",
    "LEGAL_POSITIONING": "brand.legal_positioning",
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(raw: str) -> Any:
    low = raw.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.strip().startswith(("[", "{")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def _set_path(tree: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = tree
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def _apply_env_overrides(tree: dict) -> dict:
    for env_name, dotted in _ENV_SHORTCUTS.items():
        if (raw := os.getenv(env_name)) not in (None, ""):
            _set_path(tree, dotted, _coerce(raw))
    # Also accept the fully-qualified form, e.g. PUBLISHING__DRY_RUN
    for key, raw in os.environ.items():
        if "__" in key and key.isupper() and raw != "":
            _set_path(tree, key.lower().replace("__", "."), _coerce(raw))
    return tree


class Settings:
    """Dotted-path access to settings.yaml with env overrides applied."""

    def __init__(self, tree: dict):
        self._tree = tree

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._tree
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, dotted: str) -> Any:
        value = self.get(dotted, _MISSING)
        if value is _MISSING:
            raise KeyError(f"Missing required setting: {dotted}")
        return value

    @property
    def raw(self) -> dict:
        return self._tree

    def __repr__(self) -> str:  # pragma: no cover
        return f"Settings(top_level={list(self._tree)})"


_MISSING = object()


@dataclass(frozen=True)
class Secrets:
    """Secrets live only in the environment. Never logged, never serialised."""

    gemini_api_key: str = ""
    ig_user_id: str = ""
    ig_access_token: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    ig_api_host: str = "graph.facebook.com"
    ig_api_version: str = "v23.0"
    github_token: str = ""
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_public_base_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    @classmethod
    def from_env(cls) -> Secrets:
        e = os.getenv
        return cls(
            gemini_api_key=e("GEMINI_API_KEY", "") or e("GOOGLE_API_KEY", ""),
            ig_user_id=e("IG_USER_ID", ""),
            ig_access_token=e("IG_ACCESS_TOKEN", ""),
            meta_app_id=e("META_APP_ID", ""),
            meta_app_secret=e("META_APP_SECRET", ""),
            ig_api_host=e("IG_API_HOST", "graph.facebook.com"),
            ig_api_version=e("IG_API_VERSION", "v23.0"),
            github_token=e("GITHUB_TOKEN", ""),
            s3_endpoint_url=e("S3_ENDPOINT_URL", ""),
            s3_bucket=e("S3_BUCKET", ""),
            s3_public_base_url=e("S3_PUBLIC_BASE_URL", ""),
            s3_access_key_id=e("S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=e("S3_SECRET_ACCESS_KEY", ""),
        )

    def missing_for(self, capability: str) -> list[str]:
        needs = {
            "generate": [("GEMINI_API_KEY", self.gemini_api_key)],
            "publish": [
                ("IG_USER_ID", self.ig_user_id),
                ("IG_ACCESS_TOKEN", self.ig_access_token),
            ],
            "refresh_token": [
                ("META_APP_ID", self.meta_app_id),
                ("META_APP_SECRET", self.meta_app_secret),
                ("IG_ACCESS_TOKEN", self.ig_access_token),
            ],
        }[capability]
        return [name for name, value in needs if not value]

    def __repr__(self) -> str:  # never leak secrets into logs
        present = [
            f.replace("_", " ")
            for f in ("gemini_api_key", "ig_access_token", "meta_app_secret")
            if getattr(self, f)
        ]
        return f"Secrets(configured={present})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    tree = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    return Settings(_apply_env_overrides(tree))


@lru_cache(maxsize=1)
def get_bible() -> dict:
    return json.loads(BIBLE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_secrets() -> Secrets:
    return Secrets.from_env()


def reset_caches() -> None:
    """Test hook — clears memoised config so env changes take effect."""
    get_settings.cache_clear()
    get_bible.cache_clear()
    get_secrets.cache_clear()
