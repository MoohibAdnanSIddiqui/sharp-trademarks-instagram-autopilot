#!/usr/bin/env python3
"""Sharp Trademarks Instagram Autopilot — command line entry point.

    python run.py doctor              check configuration and credentials
    python run.py plan [--date D]     plan the day's posts
    python run.py generate [--date D] render images for planned posts
    python run.py publish [--slot N]  publish (respects DRY_RUN / AUTO_PUBLISH)
    python run.py run [--slot N]      plan + generate + publish in one pass
    python run.py due                 publish only the slot that is due now
    python run.py analytics           collect Instagram insights
    python run.py review              analyse performance, adjust the plan
    python run.py refresh-token       refresh the long-lived access token
    python run.py calendar [--days N] print the upcoming plan
    python run.py preview             render all visual systems to a contact sheet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.content.database import ContentDB  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.utils.config import get_secrets, get_settings  # noqa: E402
from app.utils.logging import get_logger, setup_logging  # noqa: E402


def _bootstrap() -> None:
    s = get_settings()
    setup_logging(
        level=str(s.get("logging.level", "INFO")),
        as_json=bool(s.get("logging.json", False)),
        file=s.get("logging.file"),
    )


def cmd_doctor(_: argparse.Namespace) -> int:
    s, sec = get_settings(), get_secrets()
    ok = True

    print("\n  Configuration")
    print(f"    timezone            {s.get('schedule.timezone')}")
    print(f"    posts per day       {s.get('schedule.posts_per_day')} at {s.get('schedule.post_times')}")
    print(f"    legal positioning   {s.get('brand.legal_positioning')}")
    print(f"    dry_run             {s.get('publishing.dry_run')}")
    print(f"    auto_publish        {s.get('publishing.auto_publish')}")
    print(f"    media host          {s.get('media_host.provider')}")
    print(f"    gemini model        {s.get('gemini.model')}")

    print("\n  Assets")
    for name in ("logo_full.png", "logo_full_reversed.png", "logo_wordmark.png",
                 "logo_wordmark_reversed.png"):
        p = Path("assets/brand") / name
        print(f"    {'ok  ' if p.exists() else 'MISSING'} {name}")
        ok &= p.exists()
    for name in ("Manrope-Variable.ttf", "Inter-Variable.ttf"):
        p = Path("assets/fonts") / name
        print(f"    {'ok  ' if p.exists() else 'MISSING'} {name}")
        ok &= p.exists()

    print("\n  Content bank")
    from app.content.strategist import load_bank
    bank = load_bank()
    print(f"    {len(bank)} items across {len({i['content_pillar'] for i in bank})} pillars"
          f"  ({len(bank)//2} days at 2/day before any topic repeats)")

    print("\n  Credentials")
    for cap in ("generate", "publish"):
        missing = sec.missing_for(cap)
        print(f"    {'ok  ' if not missing else 'MISSING'} {cap:9s} {', '.join(missing) or 'configured'}")

    if not sec.missing_for("publish"):
        from app.instagram.publisher import InstagramError, InstagramPublisher
        try:
            api = InstagramPublisher()
            me = api.check_credentials()
            print(f"    ok   connected to @{me.get('username')} "
                  f"({me.get('account_type')}, {me.get('media_count')} posts)")
            limit = api.publishing_limit()
            if limit:
                print(f"    ok   API posts used in the last 24h: "
                      f"{limit.get('quota_usage')} / {(limit.get('config') or {}).get('quota_total')}")
        except InstagramError as exc:
            print(f"    FAIL Instagram: {exc}")
            ok = False

    creds_missing = sec.missing_for("generate") + sec.missing_for("publish")
    if not ok:
        print("\n  Some checks FAILED — see above.\n")
        return 1
    if creds_missing:
        print("\n  Assets, fonts and content bank are ready.")
        print("  Credentials not configured yet — the system will run in dry-run mode")
        print("  using the procedural brand texture. See README section 'Setup'.\n")
        return 0
    print("\n  All checks passed. Ready to publish.\n")
    return 0


def cmd_plan(a: argparse.Namespace) -> int:
    briefs = Pipeline().plan(a.date)
    for b in briefs:
        print(f"  slot {b.slot}  {b.publish_time[11:16]}  [{b.content_pillar}]  "
              f"{b.content_type}  {len(b.slides)} slide(s)")
        print(f"          {b.topic}")
        print(f"          hook: {b.hook}")
        print(f"          status: {b.status}")
    return 0


def cmd_generate(a: argparse.Namespace) -> int:
    p = Pipeline()
    date = a.date or p.today()
    rows = [r for r in p.db.recent(50) if r["date"] == date]
    briefs = [p.db.get(r["content_id"]) for r in rows] or p.plan(date)
    for b in briefs:
        if b is None:
            continue
        b = p.generate(b)
        print(f"  {b.content_id}  {b.status}  ->  {len(b.render_paths)} image(s)")
        for path in b.render_paths:
            print(f"      {path}")
    return 0


def cmd_publish(a: argparse.Namespace) -> int:
    for b in Pipeline().run_slot(a.date, a.slot):
        print(f"  {b.content_id}  {b.status}  {b.ig_media_id or ''} {b.permalink or ''}")
        for e in b.errors[-3:]:
            print(f"      ! {e}")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    return cmd_publish(a)


def cmd_due(a: argparse.Namespace) -> int:
    p = Pipeline()
    slot = p.due_slot()
    if slot is None:
        print("  no slot is due right now")
        return 0
    print(f"  slot {slot} is due")
    for b in p.run_slot(slot=slot):
        print(f"  {b.content_id}  {b.status}  {b.permalink or ''}")
    return 0


def cmd_analytics(_: argparse.Namespace) -> int:
    from app.analytics.collector import AnalyticsCollector
    n = AnalyticsCollector().run()
    print(f"  collected metrics for {n} post(s)")
    return 0


def cmd_review(_: argparse.Namespace) -> int:
    from app.analytics.strategist_feedback import StrategyReviewer
    print(json.dumps(StrategyReviewer().analyse(), indent=2))
    return 0


def cmd_refresh_token(_: argparse.Namespace) -> int:
    from app.instagram.token import refresh_long_lived_token
    data = refresh_long_lived_token()
    token = data["access_token"]
    print(f"  token refreshed, valid ~{data['expires_in_days']} days "
          f"({token[:6]}...{token[-4:]})")
    out = Path("data/.new_token")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(token)
    print(f"  written to {out} — the workflow stores it as a GitHub Secret and deletes it")
    return 0


def cmd_calendar(a: argparse.Namespace) -> int:
    from datetime import date as _date
    from datetime import timedelta
    p = Pipeline()
    start = _date.fromisoformat(p.today())
    for i in range(a.days):
        d = (start + timedelta(days=i)).isoformat()
        for b in p.strategist.plan_day(d):
            print(f"  {d}  slot{b.slot}  {b.content_pillar:26s} {b.content_type:13s} {b.topic}")
    return 0


def cmd_preview(_: argparse.Namespace) -> int:
    import subprocess
    return subprocess.run([sys.executable, "scripts/preview_templates.py"]).returncode


COMMANDS = {
    "doctor": cmd_doctor, "plan": cmd_plan, "generate": cmd_generate,
    "publish": cmd_publish, "run": cmd_run, "due": cmd_due,
    "analytics": cmd_analytics, "review": cmd_review,
    "refresh-token": cmd_refresh_token, "calendar": cmd_calendar,
    "preview": cmd_preview,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--date", help="YYYY-MM-DD (defaults to today in the configured timezone)")
    parser.add_argument("--slot", type=int, help="publish only this slot")
    parser.add_argument("--days", type=int, default=7, help="calendar horizon")
    args = parser.parse_args()
    _bootstrap()
    try:
        return COMMANDS[args.command](args)
    except Exception as exc:
        get_logger("run").exception("command %s failed: %s", args.command, exc)
        ContentDB().log_run(args.command, False, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
