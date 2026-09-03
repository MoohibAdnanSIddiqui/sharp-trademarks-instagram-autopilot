"""Instagram fetches media from a public URL, so every rendered JPEG must be
reachable on the open internet before it can be published.

Three providers:
  github_raw — default. Assets are committed to a public repo and served from
               raw.githubusercontent.com. Free, no extra infrastructure, and
               the same GitHub Actions run that renders them also pushes them.
  s3         — any S3-compatible bucket (Cloudflare R2 included).
  local      — dry run only; returns file:// URLs that are never published.
"""
from __future__ import annotations

import mimetypes
import subprocess
from pathlib import Path
from urllib.parse import quote

from app.utils.config import get_secrets, get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[2]


class MediaHostError(RuntimeError):
    pass


class MediaHost:
    def publish(self, paths: list[str]) -> list[str]:
        raise NotImplementedError


class LocalHost(MediaHost):
    """Dry-run only. A file:// URL will never be accepted by Instagram, which is
    exactly the behaviour we want if DRY_RUN is misconfigured."""

    def publish(self, paths: list[str]) -> list[str]:
        return [Path(p).resolve().as_uri() for p in paths]


class GitHubRawHost(MediaHost):
    def __init__(self) -> None:
        s = get_settings()
        cfg = s.get("media_host.github", {}) or {}
        self.repo = str(cfg.get("repo", "")).strip()
        self.branch = str(cfg.get("branch", "main"))
        self.subdir = str(cfg.get("path", "assets/generated")).strip("/")
        if not self.repo or self.repo.startswith("REPLACE_ME"):
            raise MediaHostError(
                "media_host.github.repo is not configured. Set it in config/settings.yaml "
                "or via the GITHUB_REPOSITORY environment variable."
            )

    def _url(self, rel: str) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.branch}/{quote(rel)}"

    def publish(self, paths: list[str]) -> list[str]:
        rels = []
        for p in paths:
            path = Path(p).resolve()
            try:
                rels.append(str(path.relative_to(ROOT)))
            except ValueError as exc:
                raise MediaHostError(f"{p} is outside the repository") from exc
        self._commit(rels)
        return [self._url(r) for r in rels]

    def _commit(self, rels: list[str]) -> None:
        """Commit and push the rendered assets. In GitHub Actions the checkout
        action already supplies credentials; locally this needs push rights."""
        try:
            subprocess.run(["git", "add", "--", *rels], cwd=ROOT, check=True,
                           capture_output=True, text=True)
            status = subprocess.run(["git", "status", "--porcelain", "--", *rels],
                                    cwd=ROOT, check=True, capture_output=True, text=True)
            if not status.stdout.strip():
                log.info("assets already committed — nothing to push")
                return
            subprocess.run(
                ["git", "-c", "user.name=sharp-autopilot",
                 "-c", "user.email=autopilot@users.noreply.github.com",
                 "commit", "-m", f"chore(assets): publish {len(rels)} rendered image(s)"],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            subprocess.run(["git", "push", "origin", f"HEAD:{self.branch}"],
                           cwd=ROOT, check=True, capture_output=True, text=True)
            log.info("pushed %s asset(s) to %s@%s", len(rels), self.repo, self.branch)
        except subprocess.CalledProcessError as exc:
            raise MediaHostError(
                f"could not publish assets to GitHub: {exc.stderr or exc.stdout}"
            ) from exc


class S3Host(MediaHost):
    def __init__(self) -> None:
        sec = get_secrets()
        missing = [
            n for n, v in (
                ("S3_BUCKET", sec.s3_bucket),
                ("S3_PUBLIC_BASE_URL", sec.s3_public_base_url),
                ("S3_ACCESS_KEY_ID", sec.s3_access_key_id),
                ("S3_SECRET_ACCESS_KEY", sec.s3_secret_access_key),
            ) if not v
        ]
        if missing:
            raise MediaHostError(f"S3 host missing: {', '.join(missing)}")
        self.sec = sec

    def publish(self, paths: list[str]) -> list[str]:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise MediaHostError("provider 's3' requires boto3 — add it to requirements.txt") from exc

        client = boto3.client(
            "s3",
            endpoint_url=self.sec.s3_endpoint_url or None,
            aws_access_key_id=self.sec.s3_access_key_id,
            aws_secret_access_key=self.sec.s3_secret_access_key,
        )
        urls = []
        for p in paths:
            path = Path(p)
            key = f"instagram/{path.parent.name}/{path.name}"
            ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            client.upload_file(str(path), self.sec.s3_bucket, key,
                               ExtraArgs={"ContentType": ctype, "CacheControl": "public, max-age=31536000"})
            urls.append(f"{self.sec.s3_public_base_url.rstrip('/')}/{key}")
        return urls


def get_media_host() -> MediaHost:
    provider = str(get_settings().get("media_host.provider", "github_raw")).lower()
    if provider == "local":
        return LocalHost()
    if provider == "s3":
        return S3Host()
    return GitHubRawHost()
