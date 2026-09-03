# Sharp Trademarks — Brand Style Bible

The human-readable companion to `config/brand_style_bible.json`. The JSON file is
what the code reads; this file is what a person reads before changing it. **If you
change one, change the other.**

---

## 1. Position

Sharp Trademarks is the clear, guided way for founders and growing businesses to
protect their brand name, logo and slogan with the USPTO — without the confusion,
the guesswork, or the avoidable filing mistakes.

The promise the account keeps: *you will understand what you are filing, why it
matters, and what happens next.*

**Legal positioning: `hybrid`.** Sharp Trademarks is a filing service whose work is
supported and reviewed by attorneys.

| May say | May never say |
|---|---|
| "attorney-supported" | "we are your attorney" |
| "reviewed by an attorney before filing" | "attorney-client relationship" |
| "our attorneys" | "we represent you" / "legal representation" |
| "USPTO filing support" | "law firm associated with the Federal Office" |
| "pre-filing risk review" | "USPTO-endorsed" / "government approved" |

Change this with one line in `config/settings.yaml` (`brand.legal_positioning`):
`strict` removes every attorney reference; `law_firm` permits attorney-led framing
and **should not be enabled without bar-compliance review**.

> The site currently carries the line *"Sharp Trademarks is a law firm associated
> with the Federal Office."* That reads as a government-affiliation claim and the
> validator blocks it outright. It contradicts the footer disclaimer on the same
> page. Worth resolving on the website too.

---

## 2. Audience

Primary: US founders and small-business owners, 1–20 employees, 0–5 years in.

They arrive at one of six moments:

- just picked a business name
- about to launch or rebrand
- found someone using a similar name
- a marketplace asked for brand registry proof
- an investor or partner asked whether the name is protected
- received an Office Action and does not understand it

Five beliefs the account exists to overturn:

1. Registering an LLC protects the name.
2. Buying the domain protects the name.
3. Copyright covers the brand name.
4. You can file later once you are bigger.
5. The USPTO will tell you if the name is taken.

Their fears: wasting the filing fee, being refused, losing a name they already
invested in, hidden costs, being upsold. **The account never trades on those
fears.** It removes them by explaining the mechanism.

---

## 3. Voice

Eighth-grade reading level. Short sentences. Concrete nouns. Second person.

> **Lead with the claim. Then the evidence. Then the consequence.**

Sharp Trademarks is: precise, calm, plain-spoken, credible, generous with
knowledge, unhurried.
It is not: a hype merchant, a fear-monger, a legalese machine, a discount-shouter,
a meme account.

**Never appears anywhere:** guaranteed · guarantee · 100% · approved instantly ·
cheapest · loophole · hack · secret · bulletproof · we promise · risk-free ·
no-brainer · game-changer · unlock · supercharge · revolutionary · elevate your brand

**Emoji:** none in graphics. At most one in a caption, never in the hook line.

**CTA:** one per caption, low-friction, no pressure, never a price.
Approved forms live in the JSON under `voice.cta_style.approved`.

---

## 4. The pricing rule

**No pricing anywhere.** Not in graphics, captions, alt text, hashtags or CTAs.
Not $35, not $149, not $249, not "starting from", not "affordable rates".

One exception: the phrase *"USPTO filing fees"* may appear when explaining that
government fees exist and are separate — **with no amount attached.**

This is enforced in code (`app/validation/compliance.py`), not by discipline. A
post containing a price cannot be published.

---

## 5. Colour

| Role | Hex | Use |
|---|---|---|
| Sharp Teal | `#0d9488` | accents, rules, highlights, icon strokes |
| Deep Navy | `#101f3d` | primary background and primary text |
| White | `#ffffff` | light background, reversed text |

Support tones: `#182a4e` `#22375f` `#5eead4` `#0f766e` `#f2f6f9` `#d9e2ea` `#5b6b7f`

Rules:

- Every asset uses **one** background family — navy **or** paper. Never a gradient between them.
- Teal is an accent. Never a background wash, never more than ~15% of the canvas.
- Body text is navy on light, white on navy. **Never teal body text.**
- No colour outside this palette appears as a flat UI element.
- Minimum contrast 4.5:1 under 32px, 3:1 above.

> The supplied logo JPEG used slightly different values (`#028d92` teal, `#012a5e`
> navy). `scripts/build_brand_assets.py` normalises the logo to the exact brand
> hexes above, so the mark on every post matches the palette precisely.

---

## 6. Typography

| Role | Family | Weight | Notes |
|---|---|---|---|
| Headline | Manrope | ExtraBold / Bold | tracking −1.5%, leading 1.06, sentence case |
| Body | Inter | Regular / Medium / SemiBold | leading 1.42 |
| Eyebrow | Inter | SemiBold | UPPERCASE, tracking +14%, 26px |

Scale at 1080×1350: eyebrow 26 · headline XL 104 · L 86 · M 68 · subhead 44 ·
body 36 · small 28 · footer 26.

Rules:

- At most two type sizes compete for attention on any slide.
- Headlines never exceed 7 words per line or 4 lines total — the layout engine
  shrinks the type rather than truncating the words.
- Never letterspace lowercase body text.
- Never set headlines in ALL CAPS. The eyebrow is the only uppercase element.
- Never centre-align body copy longer than two lines.

Both families are SIL Open Font Licence; the licences ship in `assets/fonts/`.

---

## 7. Logo

Python composites the logo from real asset files on every single post. **Gemini
never draws it.**

- Reversed variants on navy; standard variants on paper.
- Clear space on all sides ≈ 0.4× logo height.
- Minimum wordmark width 180px at 1080px canvas; below that use the mark alone.
- Never recolour, rotate, outline, shadow, or place on a busy area of imagery.
- A feed post carries the logo **once** — bottom-left of the final slide, or the
  single-image footer.

---

## 8. Imagery

Gemini generates **atmosphere, texture and abstract structure**. Never text, never
logos, never the layout.

**Approved:** abstract geometric fields of concentric arcs and rising bars echoing
the emblem · desaturated macro photography of paper, ink, embossing · clean
isometric 3D in matte navy and teal · long-exposure light trails over navy ·
architectural photography with strong verticals and a cool cast · minimal line-art
diagrams with generous negative space.

**Forbidden:** any legible text or numbers · logos or wordmarks · gavels,
courtrooms, scales of justice · stock handshakes and thumbs-up · identifiable
faces · AI artefacts · neon cyberpunk, glossy chrome, lens flare · flags,
government seals, eagles, or anything implying official endorsement · busy centre
composition.

Composition defaults: ≥45% negative space biased upper-left, focal interest
lower-right third, single soft key from upper left, shallow depth of field, very
fine film grain.

Every generated image is graded toward the palette in code before it is used, so a
stray warm background cannot break the feed.

---

## 9. The ten visual systems

Rotated so the feed feels designed rather than templated, and cooled down for five
posts after use.

| ID | Name | Ground | Used for |
|---|---|---|---|
| VS01 | Statement | navy | myths, mistakes, education — the workhorse cover |
| VS02 | Split Frame | paper | education, process, naming |
| VS03 | Numbered Steps | paper | sequences and enumerated points |
| VS04 | Myth / Fact | navy | myth-busting, objections |
| VS05 | Checklist | paper | clearance, naming, mistakes |
| VS06 | Two Column Compare | paper | education, objections |
| VS07 | Pull Statement | navy | trust, monitoring |
| VS08 | Question / Answer | paper | FAQs, education |
| VS09 | Closing Card | navy | the last slide of every carousel |
| VS10 | Timeline | paper | process, enforcement |

A template is only ever selected when the content item can actually feed it —
a Myth/Fact panel is never chosen for an item with no myth and fact.

Layout constants: 1080×1350, 84px safe margin, one consistent left edge per
slide, slide counter top-right, footer lockup on every slide.

---

## 10. Content pillars

| Pillar | Target share | Purpose |
|---|---|---|
| Trademark Education | 22% | make the fundamentals obvious |
| Costly Mistakes | 16% | prevent avoidable loss |
| Myths vs Facts | 12% | overturn expensive beliefs |
| Search & Clearance | 10% | show why pre-filing review matters |
| Naming & Branding | 10% | reach founders at the naming moment |
| USPTO Process | 10% | remove the fear of the unknown |
| Monitoring & Enforcement | 8% | registration is a start, not an end |
| FAQs & Objections | 7% | answer what stops people filing |
| Trust & Service | 5% | convert attention into enquiry |

**95% of the feed is education and trust. 5% is service.** The audience should
feel Sharp Trademarks is helping them understand brand protection, not selling.

The analytics reviewer may shift these shares by at most ±25% relative per review,
floored at 3% and capped at 30%, and only once at least 12 posts have real metrics.

---

## 11. Claims

**Usable (brand-supplied):** 500+ trademark applications filed · 150+ verified
client reviews · simple 3-step online filing process · based in Fredericksburg,
Virginia.

**Never used:** any star rating or review-platform score · any named testimonial ·
any USPTO statistic not cited to uspto.gov · any approval, refusal or success
percentage · any competitor comparison · any pricing.

The placeholder text on the website — *"add your verified review platform & score
here"* — is never treated as a real rating.

---

## 12. Changing this document

1. Edit `config/brand_style_bible.json` (the machine reads this).
2. Mirror the change here.
3. Run `pytest` — the suite asserts the whole content bank still complies.
4. Run `python run.py preview` and look at the contact sheet.
