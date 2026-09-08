# Sharp Trademarks — Instagram Autopilot

Plans, designs, writes, validates and publishes **2 brand-consistent Instagram
posts a day, 12 hours apart**, from GitHub Actions. Your computer does not need to
be on.

```
        BRAND STYLE BIBLE  ──────────────┐
        (colors, voice, rules, claims)   │
                                         ▼
  CONTENT BANK ──▶ STRATEGIST ──▶ CONTENT BRIEF (JSON)
  72 vetted        pillar balance,       │
  topics           cooldowns, format     │
                                         ├──▶ GEMINI ──▶ background artwork
                                         │               (atmosphere only)
                                         ▼
                                    PYTHON RENDERER
                          real logo · exact hexes · Manrope/Inter
                          exact layout · exact wording
                                         │
                                         ▼
                     COMPLIANCE GATE ──▶ IMAGE VALIDATOR
                     no pricing, no guarantees, no false authority
                                         │
                                         ▼
                    MEDIA HOST ──▶ INSTAGRAM GRAPH API ──▶ live post
                                         │
                                         ▼
                              ANALYTICS ──▶ STRATEGY REVIEW
                                         └──▶ adjusts the next plan
```

**The core design decision:** Gemini generates *atmosphere*. Python renders
*everything that must be correct* — the logo, the brand hexes, the typography, the
layout, the phone number, the legal wording. No generative model is ever trusted
with a fact, a claim, or the brand mark.

---

## What it will not do

These are enforced in code, not by convention. A post that breaks one of them
cannot be published.

- **No pricing.** Not in graphics, captions, alt text or hashtags. `$35`, `$149`,
  `$249`, "starting from" — all blocked. ("USPTO filing fees" with no amount is the
  single exception.)
- **No guarantees**, approval rates, success percentages or invented statistics.
- **No implied government affiliation or USPTO endorsement.**
- **No invented testimonials, ratings or review scores.**
- **No attorney-client claims.** Legal positioning is `hybrid`: attorney
  involvement may be stated; "we are your attorney" may not.
- **Never publishes the same slot twice**, however many times a workflow retries.
- **Never posts a legal-education slide without a "not legal advice" line.**

---

## Setup

### 1. Clone and check

```bash
git clone <your-repo> && cd sharp-trademarks-instagram-autopilot
pip install -r requirements.txt
python run.py doctor          # assets, fonts, bank, credentials
python run.py preview         # renders all 10 visual systems to a contact sheet
```

### 2. Instagram access — the part that needs you

Sharp Trademarks needs an **Instagram professional account** (Business or Creator).
Convert it in the Instagram app under *Settings → Account type and tools*.

Then, at [developers.facebook.com](https://developers.facebook.com):

1. Create an app, type **Business**.
2. Add the **Instagram** product.
3. Connect the `@sharptrademarks` account.
4. Request these permissions:
   `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_insights`.
   (With Facebook Login instead: `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`.)
5. Generate a **long-lived access token** (~60 days) and note your numeric
   **Instagram user ID** — not the @handle.

App Review is required before the app can act on a live account. Until then, the
account owner as a test user can publish.

> **Never paste a token into a chat, a file, or a commit.** They go into GitHub
> Secrets and nowhere else.

### 3. Gemini key

Create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 4. GitHub Secrets

*Settings → Secrets and variables → Actions → Secrets:*

| Secret | What it is |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key |
| `IG_USER_ID` | numeric Instagram professional account ID |
| `IG_ACCESS_TOKEN` | long-lived access token |
| `META_APP_ID` | Meta app ID — **only needed on the Facebook Login path** |
| `META_APP_SECRET` | Meta app secret — **only needed on the Facebook Login path** |
| `GH_PAT` | *optional* — fine-grained PAT with **Secrets: read and write**, so the token refresh can write itself back |

*…→ Variables:*

| Variable | Start with | Go live with |
|---|---|---|
| `DRY_RUN` | `true` | `false` |
| `AUTO_PUBLISH` | `false` | `true` |
| `IG_API_HOST` | set to match your login path | `graph.instagram.com` for Instagram Login, `graph.facebook.com` for Facebook Login |

This deployment uses **Instagram Login**, so `IG_API_HOST` is
`graph.instagram.com` and the token refreshes against itself — `META_APP_ID`
and `META_APP_SECRET` are not required.

### 5. Point the media host at your repo

Instagram fetches media from a **public URL**, so rendered JPEGs are served from
`raw.githubusercontent.com`. In `config/settings.yaml`:

```yaml
media_host:
  provider: "github_raw"
  github:
    repo: "your-username/sharp-trademarks-instagram-autopilot"
```

The repo must be **public** for this to work. No secrets are ever committed — they
live in GitHub Secrets. If you would rather keep the repo private, switch
`provider` to `s3` and add the four `S3_*` secrets (Cloudflare R2 works).

---

## Rollout — do not skip the dry run

```bash
# 1. Look at the output before anyone else does
python run.py plan --date 2026-09-10
python run.py generate --date 2026-09-10
open assets/generated/2026-09-10/*/00.jpg

# 2. A full pass with nothing sent
DRY_RUN=true AUTO_PUBLISH=false python run.py run

# 3. Let the scheduled workflows run in dry-run for 3-4 days.
#    Read every caption. Look at every image.

# 4. One real post, by hand
DRY_RUN=false AUTO_PUBLISH=true python run.py publish --slot 0

# 5. Only then flip the repository Variables:
#    DRY_RUN=false, AUTO_PUBLISH=true
```

---

## Commands

| Command | What it does |
|---|---|
| `python run.py doctor` | configuration, assets, credentials, live account check |
| `python run.py plan` | plan today's posts |
| `python run.py generate` | generate backgrounds and render branded JPEGs |
| `python run.py publish` | publish (respects `DRY_RUN` / `AUTO_PUBLISH`) |
| `python run.py due` | publish only the slot due right now |
| `python run.py calendar --days 14` | print the upcoming plan |
| `python run.py analytics` | collect Instagram insights |
| `python run.py review` | analyse performance, adjust the pillar mix |
| `python run.py refresh-token` | refresh the long-lived token |
| `python run.py preview` | render all 10 visual systems |

## Workflows

| Workflow | Schedule | Does |
|---|---|---|
| `plan.yml` | daily, early | plans the day, commits the calendar |
| `publish.yml` | hourly | publishes only if a slot is due |
| `analytics.yml` | daily | collects insights; strategy review on Mondays |
| `refresh-token.yml` | weekly | refreshes the access token |
| `ci.yml` | on push | lint, tests, full dry run |

`publish.yml` runs **hourly and does nothing unless a post time is due**. A fixed
UTC cron would drift by an hour twice a year when the audience timezone changes for
daylight saving; reading local time from `settings.yaml` keeps the schedule correct
all year.

---

## Configuration

Business settings live in `config/settings.yaml`. Nothing is hard-coded, and every
value can be overridden by an environment variable, so CI changes behaviour without
touching code.

```yaml
schedule:
  timezone: "America/New_York"     # audience timezone, not yours
  posts_per_day: 2
  post_interval_hours: 12
  post_times: ["09:00", "21:00"]
  blackout_dates: []
publishing:
  auto_publish: false
  dry_run: true
  max_posts_per_24h: 4             # local cap, far below Instagram's 100
  min_minutes_between_posts: 240
```

Shortcut env vars: `DRY_RUN` `AUTO_PUBLISH` `POSTS_PER_DAY` `POST_INTERVAL_HOURS`
`TIMEZONE` `LOG_LEVEL` `GEMINI_MODEL` `MEDIA_HOST_PROVIDER` `LEGAL_POSITIONING`.
Any setting also works as `SECTION__KEY`, e.g. `PUBLISHING__MAX_POSTS_PER_24H=2`.

---

## How it stays original

| Guard | Rule |
|---|---|
| Topic cooldown | a topic cannot return within 45 days |
| Pillar cooldown | a pillar cannot repeat within 4 posts |
| Template cooldown | a visual system cannot repeat within 5 posts |
| Hook similarity | blended shingle + character n-gram + Dice, threshold 0.75 |
| Caption similarity | same measure, threshold 0.68 |
| Image similarity | perceptual hash, Hamming distance ≤ 12 |
| Within a carousel | a structural template is used at most once per post |

The content bank holds **72 vetted items across 9 pillars** — 36 days at two posts
a day before any topic could repeat. Add more in `config/bank/*.json`; `pytest`
will check every new item against the compliance rules.

## How it improves

`run.py review` runs weekly and scores each pillar, format, template, objective and
posting hour by an engagement measure that weights **saves and shares 3× above
likes** — this account's job is to be kept and forwarded.

Two rules keep it honest: **nothing changes below 12 posts with real metrics**, and
a pillar's share can move by at most ±25% relative per review, floored at 3% and
capped at 30%. The plan drifts; it never lurches.

---

## Why these dependencies

| Choice | Why |
|---|---|
| `google-genai` | the official Gemini SDK. Two call paths (`interactions` and `generate_content`) with automatic fallback, because the SDK has changed shape before and this runs unattended. |
| `requests` against the Graph API directly | every Instagram Python wrapper on PyPI is either unmaintained or wraps the *private* API. Publishing is two documented endpoints; a dependency here is risk, not leverage. |
| `Pillow` | deterministic typography, logo compositing, exact layout. |
| `ImageHash` | perceptual hashing for visual duplicate detection. |
| `numpy` | palette grading and image validation maths. |
| No headless browser, no `instagrapi`, no scraping | the brief was explicit and it is also the right call: unofficial automation risks the account. |

**Not used, deliberately:** any library that logs in with a username and password.

## Failure handling

- Exponential backoff on every Gemini and Instagram call; only Meta's documented
  transient error codes are retried.
- If Gemini is unavailable, the renderer falls back to a **procedural brand
  texture** built from the emblem's own geometry. A post always ships.
- If an image fails validation, it is re-rendered up to `max_generation_attempts`.
- A container is never published until Instagram reports it `FINISHED`.
- The `(date, slot)` claim is taken **before** the first API call. If the media host
  fails, the claim is released (nothing was sent). If Instagram fails *after* a call,
  the claim is **kept** — media may exist, and a human decides.
- A dry run stops before the claim, so it never consumes a slot the real run needs.
- Secrets are redacted from every log line by a logging filter, including tokens
  that appear inside URLs.

## Tests

```bash
pytest -q          # 53 tests
ruff check app run.py scripts tests
```

The suite exists to stop specific regressions: pricing leaking into a caption,
a duplicate publish, a repeated topic inside the cooldown window, an empty
Myth/Fact panel, a headline truncated into a prefix of its own body, a secret in a
log line, and every one of the 72 bank items staying compliant.

## Layout

```
app/
  branding/    palette, typography engine, 10 visual systems
  content/     models, SQLite memory, similarity, strategist
  generation/  Gemini client
  instagram/   publisher, media host, token refresh
  analytics/   collector, strategy reviewer
  validation/  compliance gate, image checks
  utils/       config, redacting logger
  pipeline.py  plan -> generate -> validate -> publish
assets/
  brand/       logo variants generated from the source file
  fonts/       Manrope + Inter (SIL OFL)
  generated/   rendered posts, by date
config/
  settings.yaml           business configuration
  brand_style_bible.json  machine-readable brand rules
  bank/                   72 vetted content items
data/
  content_history.db      committed on purpose — it is the system's memory
```

`data/content_history.db` is committed deliberately. Without it, duplicate
prevention and pillar balancing would reset on every Actions run.

---

## Open items for you

1. **Resolve the website's legal-status contradiction.** The mid-page line "a law
   firm associated with the Federal Office" conflicts with the footer disclaimer,
   and reads as a government-affiliation claim. The validator blocks it here; the
   site should not carry it either.
2. **Replace the review placeholder.** "Add your verified review platform & score
   here" is live on the site. Until a real, sourced rating exists, no rating appears
   in any post.
3. **Confirm the phone number.** The site shows `+1 (903) 248-5831`.
4. **Complete Meta App Review** before switching `AUTO_PUBLISH` to `true`.
