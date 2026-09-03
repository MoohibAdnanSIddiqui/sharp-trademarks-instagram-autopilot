# Architecture decisions

Why each significant choice was made, so a future change is deliberate.

---

### 1. Gemini generates atmosphere; Python renders everything that must be correct

**Decision.** Gemini produces abstract background artwork only. Python composites
the real logo, sets Manrope/Inter at exact sizes, fills exact brand hexes, lays out
the grid, and renders every word.

**Why.** Image models do not reliably reproduce a specific logo, a phone number, or
a legal sentence, and there is no way to verify what they produced without a human
looking. Anything that must be correct is therefore generated deterministically.
The prompt sent to Gemini explicitly forbids text, letterforms, numbers and logos.

**Consequence.** The feed is visually consistent by construction rather than by
luck, and a Gemini outage degrades to a procedural brand texture instead of
stopping the schedule.

---

### 2. Pre-vetted content bank, not per-post text generation

**Decision.** 72 fully-authored, compliance-checked items in `config/bank/*.json`.
Hooks, captions and CTAs are assembled from them with rotating structures.

**Why.** Text is the highest legal-risk surface in this business. An unattended
system that improvises legal explanations at 3am will eventually improvise a claim
that should not be made. Vetted content plus structural variation gives most of the
freshness with none of that exposure — and `pytest` asserts every item still passes
the compliance gate.

**Consequence.** Adding topics is a data change, not a code change. The bank is
36 days deep at two posts a day; extend it as the account grows.

---

### 3. Direct `requests` calls to the Graph API, not an Instagram library

**Decision.** No Instagram wrapper library.

**Why.** Every popular Python Instagram package is either unmaintained or wraps
Instagram's *private* mobile API, which requires a password and risks the account.
Official publishing is two documented endpoints plus a status poll. A dependency
here would add supply-chain risk and API-version lag in exchange for roughly sixty
lines of code.

---

### 4. Idempotency is a database row, not a retry flag

**Decision.** A `(date, slot)` claim is inserted before the first API call. The
primary key makes a second claim impossible.

**Why.** Duplicate publishing is the worst failure mode: it is public, immediate,
and cannot be undone quietly. Workflow retries, overlapping schedules and manual
re-runs all converge on the same guard.

**Subtlety.** If the media host fails, the claim is released — nothing reached
Meta. If Instagram fails *after* a call, the claim is deliberately kept: media may
have been created, and a human should decide rather than a retry loop.

---

### 5. Hourly publish workflow that usually does nothing

**Decision.** `publish.yml` runs every hour; `run.py due` decides whether a slot is
actually due, reading the audience timezone from `settings.yaml`.

**Why.** GitHub Actions cron is UTC-only. A fixed UTC schedule drifts by an hour
twice a year when the audience timezone changes for daylight saving. Checking
locally keeps 9am at 9am. The 90-minute grace window absorbs Actions queue delays,
and the slot claim makes the overlap safe.

---

### 6. `content_history.db` is committed to the repository

**Decision.** The SQLite file is version-controlled.

**Why.** Actions runners are ephemeral. Without persisted history, duplicate
prevention, pillar balancing and cooldowns reset on every run — the system would
happily post the same thing twice a week. Caches are evicted; artifacts expire.
At this scale (hundreds of rows a year) a committed SQLite file is the simplest
thing that actually works.

**When to change.** If the account ever runs multiple concurrent writers, move to a
hosted Postgres. The repository layer is already isolated in `app/content/database.py`.

---

### 7. Images served from `raw.githubusercontent.com`

**Decision.** Default media host is the public repository itself.

**Why.** Instagram fetches media by public URL. This needs zero extra
infrastructure, no third-party account, and no additional secret — the same Actions
run that renders the images pushes them. An `S3Host` adapter is included for
Cloudflare R2 or S3 if the repository must stay private.

**Trade-off.** The repository must be public. No secrets are ever committed, so
this is safe, but the content strategy is visible. Use the private-code /
public-assets split or S3 if that matters.

---

### 8. The compliance gate blocks rather than degrades

**Decision.** A failed check stops the post entirely. No auto-rewriting.

**Why.** An unattended system that silently edits a legal claim into something it
thinks is acceptable is more dangerous than one that skips a slot. A missed post
costs nothing; a published guarantee could cost a great deal.

**Consequence.** The guard is deliberately blunt — it flags "cheapest" even in
"the cheapest time to check a name". The content bank was rewritten to avoid the
trigger words rather than the guard being taught about negation, because negation
detection is exactly the kind of cleverness that fails quietly.

---

### 9. Templates declare what content they require

**Decision.** `TEMPLATE_NEEDS` maps each visual system to the points and fields it
consumes. The planner only selects a template the item can feed, and a structural
template is used at most once per carousel.

**Why.** The first implementation picked templates from a plan list and hoped the
content fitted. It produced empty Myth/Fact panels and two identical slides in the
same carousel. Declaring requirements makes those states unrepresentable.

---

### 10. Layout shrinks type; it never truncates words

**Decision.** `typography.fit()` reduces the font size until the text fits both the
measure and the height budget. Headlines are passed in whole.

**Why.** The earlier version trimmed headlines to a character count, which produced
headlines that were cut-off prefixes of the body text beneath them. A test now
asserts this cannot recur.

---

### 11. Analytics adjusts slowly, and not at all on small samples

**Decision.** No plan change below 12 posts with metrics. Maximum ±25% relative
move per review, floored at 3% and capped at 30% share.

**Why.** Engagement on a new account is dominated by noise. An unbounded optimiser
would chase a single lucky post into a monoculture. Saves and shares are weighted
3× above likes because the account's purpose is to be kept and forwarded.
