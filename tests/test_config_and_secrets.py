"""Configuration must be overridable, and secrets must never reach a log."""
import logging

from app.utils.config import get_secrets, get_settings, reset_caches
from app.utils.logging import redact


def test_env_overrides_settings(monkeypatch):
    monkeypatch.setenv("POSTS_PER_DAY", "5")
    monkeypatch.setenv("TIMEZONE", "Asia/Karachi")
    reset_caches()
    s = get_settings()
    assert s.get("schedule.posts_per_day") == 5
    assert s.get("schedule.timezone") == "Asia/Karachi"
    reset_caches()


def test_booleans_are_coerced(monkeypatch):
    monkeypatch.setenv("AUTO_PUBLISH", "false")
    reset_caches()
    assert get_settings().get("publishing.auto_publish") is False
    reset_caches()


def test_secrets_never_appear_in_logs(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "EAAsupersecrettokenvalue1234567890")
    assert "supersecret" not in redact("token is EAAsupersecrettokenvalue1234567890")
    assert "REDACTED" in redact("token is EAAsupersecrettokenvalue1234567890")


def test_query_string_tokens_are_redacted():
    out = redact("GET /media?access_token=ABCDEFGHIJKLMNOP1234&fields=id")
    assert "ABCDEFGHIJKLMNOP1234" not in out


def test_secrets_repr_hides_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFAKEKEYFAKEKEYFAKEKEYFAKEKEY12")
    reset_caches()
    from app.utils.config import get_secrets
    assert "AIza" not in repr(get_secrets())
    reset_caches()


def test_pillar_mix_sums_to_one():
    reset_caches()
    mix = get_settings().get("content.pillar_mix")
    assert abs(sum(mix.values()) - 1.0) < 0.001, f"pillar_mix sums to {sum(mix.values())}"


def test_instagram_login_refresh_needs_only_the_token(monkeypatch):
    monkeypatch.setenv("IG_API_HOST", "graph.instagram.com")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "IGAAfake_token_value_for_tests")
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    reset_caches()
    assert get_secrets().missing_for("refresh_token") == []
    reset_caches()


def test_facebook_login_refresh_still_needs_app_credentials(monkeypatch):
    monkeypatch.setenv("IG_API_HOST", "graph.facebook.com")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "EAAfake_token_value_for_tests")
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    reset_caches()
    assert set(get_secrets().missing_for("refresh_token")) == {"META_APP_ID", "META_APP_SECRET"}
    reset_caches()
