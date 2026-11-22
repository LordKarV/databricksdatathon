# Referral Saathi: interface design

One identity for the phone page in `app/static/`. Tokens live at the top of `app/static/app.css` (CSS custom
properties, light and dark); there is no separate tokens file because a fifth request on the critical path costs
more on a 2G phone than it saves in tidiness. Change a colour there and nowhere else.

## The world we design for

An ASHA in Sitamarhi is standing in a courtyard at dusk with a woman in labour, a cheap Android phone at 30 percent
battery, and one bar of signal. The things in her hands that already work are paper: the referral slip (parchi),
her register, the rubber stamp at the PHC, the MCP card. The things on her phone that already work are WhatsApp and
the dialler. Referral Saathi has to feel like both at once: as familiar to operate as a messaging app, and as
accountable as a stamped register entry.

So the vernacular is:

- **The stamp.** In the PHC, a decision on paper is a stamp in coloured ink: a ruled rectangle with a capital word
  in it. Our uncertainty bands are stamps. The band words are already capitals in the payload (`LIKELY`,
  `NOT VERIFIED: call to confirm`); we set them as stamps instead of fighting them.
- **The register line.** The why page's evidence ledger is a register: ruled rows, points in a right-hand column,
  a double rule under the total like an account book.
- **The route chart.** Bus and train route boards in Bihar draw a line with stops on it. The multi-stop plan is
  drawn the same way, against the clock, with the time window as a hard limit on the line.
- **The dialler.** The most important action on almost every screen is a phone call. Call buttons are the
  largest, most solid things on the page.

The tone is a calm tool in a crisis: no celebration, no gradients, nothing that moves unless it explains.

## What we took from KIN, and why

KIN (the user's earlier project) was designed for people who live in Meta's apps. Our users live in WhatsApp and
Facebook on the same cheap phones, so several of its rules carry over directly:

- **Familiarity over novelty.** Grouped grey ground with white sections, capsule buttons, 12 px fields, a 4 px grid,
  44 px targets: the shape of every messaging app she already uses. Nothing to learn.
- **System fonts.** The lightest and most offline-safe choice, and Android's own Noto Sans Devanagari renders Hindi
  well. No webfont, no extra request, nothing to cache.
- **Quiet by default, help only when needed.** Evidence, ledger rows and other routes stay one tap away
  (`details`); the first screen of an answer is the band, the place, the time and the call button.
- **Sentence case,** one transition style, colour never the only signal.

What we did not take: Meta blue and Meta greys (our neutrals are cooler and our primary is an ink blue, not a
brand blue), the 20 px card radius (our sections are 14 px; stamps are square-cornered on purpose), and the
spring card animation (our one motion is the route drawing itself).

## Colour

Six named colours, plus two band inks. Every text pair is AA or better (ratios measured on the surface they sit on).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ground` (register grey) | #EEF1F4 | #121417 | Page behind sections |
| `--surface` | #FFFFFF | #1E2126 | Sections, cards, fields |
| `--ink` (register ink) | #141A23 (17.5:1) | #E8EBEF (13.5:1) | Text |
| `--ink-2` | #4E5866 (7.2:1) | #AEB5BF (7.8:1) | Secondary text |
| `--line` / `--line-strong` | #D5DAE1 / #8A93A0 (3.1:1) | #343941 / #6B7380 (3.4:1) | Hairlines / control borders |
| `--neel` (primary, ink blue) | #1F3FA8 (9.0:1) | #93B0FF (7.6:1), fill #93B0FF with #0B1530 text | Filled buttons, links, selection |
| `--neem` (Likely) | #17683A on #E2F2E7 (5.9:1) | #7BD69A on #16301F (8.1:1) | Likely stamp, met checks |
| `--haldi` (Call first, Not verified) | #7A5300 on #FFF0C2 (6.0:1) | #F2C14E on #3A2E0D (7.9:1) | Not verified stamp, call-first tab, offline banner |
| `--siren` (108 / 102) | #C8102E, white text (5.9:1) | #D21F3C, white text (5.3:1) | Danger bar only |
| `--slate` (Unlikely) | #5A6270 on #ECEEF1 (5.3:1) | #A9B0BA on #262A30 (6.6:1) | Unlikely stamp |
| `--violet` (public standard) | #5B3E96 (8.2:1) | #C3A8F5 (7.9:1) | "by public standard, not verified" |

Red is reserved for 108/102 and the late part of the route line. It never marks a facility, so a red thing on the
screen always means "phone the ambulance". The danger bar keeps a solid red fill with white text in dark mode too:
at night it should be the brightest thing on the screen, not a pastel.

## Type

- **Latin:** the system UI face. `Roboto` first (Android, the real target), then `system-ui`, `-apple-system`,
  `Segoe UI`, `Noto Sans`.
- **Devanagari:** `Noto Sans Devanagari` first (Android ships it; it was drawn to sit next to Roboto/Noto Sans),
  then `Kohinoor Devanagari` (iOS, macOS), `Nirmala UI` (Windows), `Mukta` if installed.
- `:lang(hi)` text gets `line-height: 1.7` (matras above the headline and the u/ri marks below need about 25 percent
  more room than Latin) and is set 6 percent larger, because Devanagari at the same pixel size reads smaller than
  Latin under the shirorekha. Headings in Hindi get `line-height: 1.45` so stacked matras never clip.
- Numbers: `font-variant-numeric: tabular-nums` in the ledger, the route strip and every table.

Scale (px), a 1.2 ratio from a 17 px body: 16 (small, the floor: nothing on the page is smaller), 17 (body),
20 (h3, card titles), 23 (h2), 28 (h1). Weights: 400 body, 600 labels and h3, 700 h1/h2 and stamps.
No all-caps labels: the old uppercase `h2` and "CALL FIRST" go to sentence case. The only capitals are the band
words the payload already writes in capitals, set as stamps.

## Space, shape, targets

- 4 px grid: 4, 8, 12, 16, 24, 32, 48. Page gutter 16 px, max width 40 rem (72 rem for Compare and Area on desk).
- Radii carry hierarchy: sections 14, fields 12, tiles 14, buttons capsule, stamps 4, the call-first tab 8 8 0 0.
- Every tap target is at least 48 px tall (44 px is the floor; 48 gives a margin for thumbs in a moving vehicle).
- Shadows: none on sections (a 1 px line is enough and costs nothing in sunlight). One soft shadow on the sticky
  108 bar so it reads as above the page.

## Motion

One orchestrated moment: the route line draws itself from the start over 700 ms (stroke-dashoffset), then the
stop markers settle in. Everything else is static. The recording microphone shows a slow ring because it answers
the person's action. Under `prefers-reduced-motion: reduce` both are static.

## Components

**Danger bar (108/102).** Full width, solid siren red, white bold 18 px, a handset icon, sticky to the top of the
viewport on plan and why screens so it is reachable from anywhere in a long answer. The compact variant on the
home screen ("Chest pain or stroke now? Call 108") is a white section with a 2 px red border and a red call link.

**Band stamps.** A 2 px bordered rectangle, 4 px radius, tinted ground, the band word in 700 weight, and a shape
before it so colour is never the only signal:

```
 [(v) LIKELY]                         filled disc with a tick, neem, solid border
 [<?> NOT VERIFIED: call to confirm]  diamond with ?, haldi, solid border
 [[x] UNLIKELY]                       square with a cross, slate, solid border
 [ by public standard, not verified ] violet text, dashed border, no fill: a claim nobody has checked
```

**Call first.** A tab that sits on top of the first option's section: ink-blue fill, white text, handset icon,
sentence case. It is a recommendation, not a band, so it is shaped differently from the stamps.

**Wide tables (Area).** The plan per PIN and the ten calls scroll inside their own focusable region on a phone, so
the page itself never scrolls sideways.

**Option card (register entry).** A white section with a 6 px spine on the left in the band's colour and pattern
(solid neem, dashed haldi, dotted slate), so the band reads even in greyscale. Order inside: rank and stamp,
facility name (20 px, 600), place and payer line, travel line, the cited quote, the track record, field reports,
then two capsule buttons ("Call ahead" solid, "Why this?" outline).

**Cited quote.** No italic, no decoration: a 3 px rule on the left in `--line-strong`, the sentence in ink, and the
field and claim id as small grey tags after it. Data-quality warnings sit under the quote with a triangle icon;
weak ones in haldi.

**Ledger rows (why page, "How we decided").** A table drawn like a register page: hairline rows, the label left,
points right in tabular numerals with their sign, the total row in 700 weight over a double rule.

**Route strip.** See the wireframe below. A time axis from the start (left) to just past the last arrival.
Each stop group is one lane. A neel line runs from the start along lane 1 to the first stop, carries on along
that lane until the next arrival, drops straight down to lane 2, and so on. Each lane's label (minutes in bold,
the stop's purpose under it) sits above its lane on the far side of the drop, on a surface-coloured patch so the
hatch and the window rule never run through the words. Each arrival is drawn as a capsule from `eta_low` to `eta_high` (the range is the honesty: we do not
know the minute). The time window is a vertical rule at `limit_minutes`, labelled "Window 60 min", and the time
past it is hatched red. Every number on the strip comes from the payload and carries `data-f`. The strip is
`role="img"` with a plain label; the numbered stop list under it stays the accessible version.

**Buttons.** Capsules, 48 px tall. Primary: neel fill, white text. Secondary: white with a 2 px neel border.
Call buttons (`href^="tel:"` with the button class) get the handset and the primary fill. Pressed toggles
(`aria-pressed="true"`) fill neel.

**Offline banner.** A haldi-tinted strip with a 6 px haldi left edge and the words "No internet." in 700. It says
what still works, not that something broke.

**Voice button.** The microphone button is a full-width capsule. While recording (`aria-pressed="true"`) it turns
siren red with "Stop" text from the script and a slow expanding ring (static under reduced motion).

**Tiles (service picker).** Two columns, 14 px radius, Hindi label first at 20 px 600, English under it at 16 px in
`--ink-2`. The chosen tile gets a 2 px neel border.

## Wireframes (360 px)

Home:

```
+------------------------------------+
| (o-o) Referral Saathi    Stories   |
|                Your area  How      |
+------------------------------------+
| Where is the patient?              |  h1 28
| +--------------------------------+ |
| | pin  26.595, 85.481. GPS 40 m  | |  where section
| | (Change location) (Update GPS) | |
| +--------------------------------+ |
| What does the patient need?        |  h2 23, sentence case
| [ Search a service.............. ] |
| +--------------+ +---------------+ |
| | Hindi 20     | | Hindi 20      | |  tiles
| | English 16   | | English 16    | |
| +--------------+ +---------------+ |
| (Describe in your words) (Scan..)  |
| +--------------------------------+ |
| | Chest pain or stroke now?      | |  red border, red link
| |                 (handset) 108  | |
| +--------------------------------+ |
| > Danger signs now?                |
+------------------------------------+
```

Answer (emergency, with a route):

```
+------------------------------------+
|#### (handset) CALL 108 ambulance ##|  sticky, siren red
+------------------------------------+
| Accident / injury near you         |
| 26.595, 85.481. GPS 40 m           |
| (Quick)(Compare)(Area)             |  segmented capsules
| (Hindi)(English) (Read aloud)      |
| Suggested route                    |
| +--------------------------------+ |
| | Route 1                        | |
| | Start        :Window 60 min    | |
| | o-----(1)[==]:                 | |
| |       41-66  :\                | |
| |              ://///(2)[=====]  | |
| |              :///// 97-141 min | |
| | 1 Sharda Hospital ...          | |  the list, as today
| | 2 Heritage Hospitals ...       | |
| | [v] first care within 60: met  | |
| +--------------------------------+ |
| Options to call                    |
| +-[ Call first ]-----------------+ |
| |# 1 [(v) LIKELY]                | |  spine in band colour
| |# Prasad Hospital               | |
| |# Muzaffarpur. Private.         | |
| |# 69 km, about 50-80 min        | |
| |# | "Provides dialysis ..."     | |
| |# (Call ahead)  (Why this?)     | |
| +--------------------------------+ |
+------------------------------------+
```

Why page:

```
| (<- Plan)                          |
| Prasad Hospital [(v) LIKELY]       |
| Say this to the family             |
| "..."                              |
| From its own listing               |
| | "quote"  [field] [claim]         |
| How we decided                     |
| What we weighed          Points    |
| ---------------------------------- |
| Listing names the service    +3    |
| Phone shared by 4 listings   -1    |
| ================================== |
| Total                   +2 -> 0.81 |
| Call ahead                         |
| ((handset) Call 06212 230333)      |  primary capsule
| 1. "Is this ...?"                  |
| (Said yes)(Said no)(No answer)...  |
```

## Review against the brief (before building)

First pass, and what changed:

1. *Palette.* The first draft was a warm off-white "paper" ground with a terracotta call colour. That is the most
   common generated look and it also washes out in sunlight. Replaced with KIN-style cool grouped grey and white
   sections, and an ink blue that reads like a pen on a form rather than a brand.
2. *Cards.* The first draft gave every block the same rounded card with a shadow (the SaaS kit). Now only option
   cards and the route are sections with a band spine; secondary information (why not, field notes) sits flatter,
   and there are no shadows except under the sticky 108 bar.
3. *Band chips.* The draft used rounded pills in four colours. Pills read as tags, and colour carried the meaning.
   Stamps (rectangles, 2 px ink border, a distinct shape per band, a dashed border for the unverified public
   standard) come from the PHC's own vernacular and survive greyscale.
4. *Labels.* The old page used uppercase tracked `h2` labels and "CALL FIRST". Both are gone; the only capitals
   left are the payload's band words, where a stamp justifies them.
5. *Where the boldness goes.* Only the route strip is expressive (the drawn line, the hatched late zone).
   The rest is deliberately plain so the strip and the red bar are the two things the eye finds first.

## Critique after the first screenshots (and what was fixed)

1. *The route strip.* First build used one SVG path in a stretched viewBox with `vector-effect: non-scaling-stroke`;
   Chromium then breaks `pathLength` dashes, so the line drew with gaps, and the labels under each lane collided
   with the step down to the next lane. Now the SVG has no viewBox (x in percent, y in px), the line is a run of
   segments that draw one after another, and labels sit above their lane on the far side of the drop.
2. *Header and toggles.* Links set as inline-flex swallowed the space before the Hindi text ("Your area(...)"), and
   `summary` as a flex row spread "Route 2 : three_sites" across the line. Both are plain block layout now.
3. *The main action.* "Call ahead" and "Why this?" looked equal. "Call ahead" is now the solid capsule.
4. *Sideways scroll.* The slip and the Area page were wider than the phone before this change (373 and 495 px at a
   360 px viewport). Slip cells break long URLs; the two Area tables scroll inside their own region.

Measured: critical path 23,731 B gzip before, 28,022 B after (4 requests; CSS +2.7 KB, the strip +1.4 KB of JS).
