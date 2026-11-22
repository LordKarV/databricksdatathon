# Referral Saathi UI2: design spec

Status: design for the owner's approval. Nothing in `app/` changes in this branch. Prototype in
`design/ui2/prototype/` (serve the folder: `python3 -m http.server --directory design/ui2/prototype`, open
`index.html#/index`), screenshots and the axe report in `design/ui2/screens/`. The prototype renders two real
`/api/plan` payloads (Pusa trauma at 25.6, 85.95; Patna dialysis at 25.6, 85.14), built in `tools/deploy/deploy.sh`
order with every phone number replaced by `0000 000000`.

## 1. Direction

A public-health field tool with Rehearsal's discipline, on a plain sunlit surface. The first screen of every answer
is one readout: whom to call, how many minutes away, how sure in words, and a large green Call button. Everything else
is one tap further. Colour is a signal, never decoration: green is the way to care, red is 108, amber is "call
first". The one expressive element is the route line drawing itself to the hospital.

### What we kept from Rehearsal (owner's direction)

| Rehearsal element | Here | Why |
|---|---|---|
| Barlow for UI, Barlow Condensed for compact labels, IBM Plex Mono for measured numbers | Same roles: Condensed on route stop labels, ledger and fact headings; Plex Mono only for minutes, km, points, phone digits | A DIN-lineage grotesque reads as signage, not as a web template; mono numbers stop the readout jumping |
| Type scale 12/14/16/18/21/24/36, spacing 4/8/12/16/24/32/48 | Same steps, in rem so the text-size setting scales them | Shared rhythm; rem keeps 150 % proportional |
| Radii 2 to 4 px, no pills | Buttons 2 px, panels 4 px | Corners read as a form, not a consumer app |
| Signal colours only for meaning | Green = route line and Call; coral/red = 108, 102, time past the limit; amber = call first, not confirmed | A red thing always means "phone the ambulance" |
| Top bar, readout panel, layer list that doubles as legend | Top bar; the answer panel is the readout (36 px minutes); the route legend is the list of what each mark means | Rehearsal's rail order (readout, layers, checks) becomes answer, route, why |
| Route draws in 700 ms; pulse marker is the only ambient motion | The route line draws once; the first stop's marker pulses (2.4 s); both off under reduced motion | Motion shows where to go first |
| Focus ring, tabular figures, sentence case | Kept | |

### What we dropped

| Blueprint element | Replaced by | Why |
|---|---|---|
| Cyanotype navy ground (#0F2135) | Light neutral ground #F2F3F5, white panels; dark mode is neutral #111315, not blue | Sunlight: dark blue grounds wash out outdoors; the owner asked for light by default |
| 1 m / 5 m grid, drafting lines, sheet border | Nothing; hairlines only between list rows | Drafting texture is decoration on a 360 px phone |
| Title block, drawing-sheet metaphor, reference-bubble mark | Plain footer line ("Data as of", "not a doctor's advice"); the existing two-dot route mark | The metaphor belongs to building plans, not referrals |
| Hazard red #C8261E | #9B1C16 in both themes | White on it is 8.2:1 (AAA); #C8261E was 5.9:1 |
| Exit green #007A43 with white | #00663A (light), #3DDB8E with near-black text (dark) | 7.1:1 and 10.6:1, AAA for the Call label |

### Skill rules applied

- `ecc:frontend-design-direction`: purpose (one call decision), audience (ASHA at 360 px, coordinator on desk), tone
  (calm, utilitarian), one memorable detail (the route drawing itself), no cards inside cards, the first viewport
  is the task, existing conventions kept (hash router, `data-f` markers, system of lazy-loaded scripts).
- `ecc:accessibility` and `ecc:frontend-a11y`: native elements first (`fieldset`/`legend` radios, `details`,
  `ol`/`dl`/`table`), `aria-current` on the nav, live region for results, label on every icon-only button, colour
  never alone (shape plus word for each band), reduced motion, visible focus, 1.4.11 non-text contrast.
- `ecc:make-interfaces-feel-better`: `text-wrap: balance` on headings and `pretty` on body, `tabular-nums`
  everywhere, antialiased root, explicit transition properties (never `all`), press scale 0.98, 48 px hit areas,
  borders for separation and no shadows, concentric radii (2 inside 4).
- Research brief (`design/ui2/RESEARCH.md`), rules taken: one language at a time and own-script language names, no
  flags (section 3); Devanagari line-height 1.8 for body and 1.4 for single-line labels, no fixed heights, no
  letter-spacing or text-transform on Devanagari (section 4); body weight 500 for sunlight (section 4); audio on
  every answer (M-SAKHI, section 2); urgency shown twice, colour plus shape and weight (CHT, section 2); "Data as of"
  on every result (section 2); no gradients, glass, emoji icons, centred hero, badge per row (section 1). Not taken:
  UX4G's Noto Sans base face (the owner chose Barlow) and the "हिन्दी (Hindi)" bracket form (it puts two
  languages back on screen).

## 2. Tokens

CSS custom properties at the top of `app.css` (prototype: `ui.css`). Ratios computed with the WCAG formula.

| Token | Light | Ratio (on surface) | Dark | Ratio (on surface) | Use |
|---|---|---|---|---|---|
| `--bg` | #F2F3F5 | | #111315 | | Page |
| `--surface` | #FFFFFF | | #1A1D20 | | Panels, rows, bars |
| `--raised` | #E8EAED | | #25292D | | Pressed, neutral fill |
| `--text` | #0F1317 | 18.7 (16.8 on bg) | #EDEFF1 | 14.7 | All body text |
| `--muted` | #3B434C | 10.0 (9.0 on bg) | #B9BFC6 | 9.1 | Secondary text, still AAA |
| `--line` | #D3D7DC | | #30353B | | Row dividers (decorative) |
| `--line-strong` | #69727D | 4.9 | #7D8690 | 4.6 | Control borders (1.4.11 needs 3) |
| `--go` | #00663A, white text 7.1 | 7.1 | #3DDB8E, text #04140B 10.6 | 9.5 | Route line, Call button |
| `--go-text` | #005A33 | 8.4 | #5FE3A3 | 10.5 | Minutes readout, stop numbers |
| `--hazard` | #9B1C16, white text 8.2 | | #9B1C16, white text 8.2 | | 108 / 102 bar, limit rule |
| `--hazard-text` | #A1221B | 7.6 | #FF8B73 | 7.4 | Emergency tile icons, limit label |
| `--warn` | #E8A317 | 2.2 (edge only) | #F5B83D | 9.5 | Call-first edge, diamond fill |
| `--warn-tint` | #FFF3D6, text 16.9 | | #3A2E10, text 11.5 | | "Not confirmed" line |
| `--go-tint` | #E4F2EA, text 16.2 | | #12301F, text 12.4 | | "Likely" line |
| `--focus` | #0F1317 ring, white gap | 18.7 | #F5B83D ring, dark gap | 9.5 | Focus, 3 px plus 2 px gap |

Amber is never text and never alone: the call-first edge sits next to the "Call first" heading, and the diamond has
an ink outline (the outline carries 1.4.11). Space: `--sp1..7` = 4, 8, 12, 16, 24, 32, 48 px. Radii `--r1` 2,
`--r2` 4. Motion: `--fast` 120 ms, `--draw` 700 ms, `--pulse` 2400 ms, ease `cubic-bezier(.2,.7,.2,1)`. Target
`--target` 3 rem (48 px at 100 %). Dark mode follows the phone unless Settings says Light or Dark
(`html[data-theme]`).

## 3. Type

| Role | Latin | Devanagari | Size (px at 100 %) | Line-height Latin / Hindi |
|---|---|---|---|---|
| Readout number | Plex Mono 500 | (digits stay Latin) | 36 | 1.0 |
| h1, facility name on answer | Barlow 600 | Hind 600 | 24 | 1.25 / 1.5 |
| h2, settings legends | Barlow 600 | Hind 600 | 21 | 1.3 / 1.5 |
| h3, buttons, row names | Barlow 600 | Hind 600 | 18 | 1.25-1.35 / 1.5 |
| Body | Barlow 500 | Hind 500 | 18 | 1.45 / 1.8 |
| Secondary, notes | Barlow 500 | Hind 500 | 16 | 1.45 / 1.8 |
| Route stops, ledger and fact headings | Barlow Condensed 600 | Hind 600 | 16 | 1.2 / 1.5 |
| Legend, limit label, bottom nav | Barlow 600 / Condensed | Hind | 14 | 1.2 / 1.4 |

- Nothing on screen is below 14 px; 12 px is in the scale but unused.
- Devanagari face: Hind (SIL OFL, Indian Type Foundry), a UI grotesque whose Devanagari sits at 94 % of Latin cap
  height. `size-adjust: 108%` on its `@font-face` so the shirorekha lines up with Barlow's x-to-cap band; the system
  fallback (Noto Sans Devanagari on Android) gets 104 %. One scale for both scripts, no per-language font sizes.
- `:lang(hi)` sets `line-height: 1.8`, `letter-spacing: 0`, `text-transform: none`. No element has a fixed height
  with text in it; buttons use `min-height` and padding, so matras never clip (checked at 150 % in
  `answer_trauma-hi-light-360-text150.png`).
- Facility names, quotes and payload English carry `lang="en"` inside Hindi screens, so the screen reader switches
  voice and Barlow renders them.

Fonts, self-hosted under `app/static/fonts/`, subset with fonttools, no hinting, `font-display: swap`:

| File | Bytes | Loaded |
|---|---:|---|
| barlow-500.woff2, barlow-600.woff2 (Basic Latin) | 8,524 + 8,628 | Every page; preloaded |
| barlow-condensed-600.woff2 | 8,164 | When a condensed label renders |
| plex-mono-500-digits.woff2 (digits and `+-.,:%`) | 1,416 | When a number renders |
| hind-500-deva.woff2, hind-600-deva.woff2 | 35,632 + 34,980 | Only when Devanagari is on screen (`unicode-range`) |

Critical path today is 28,022 B gzip (design/ui/DESIGN.md). UI2 for English: about 28 KB + 26.7 KB fonts + 2.5 KB
`en.json` = about 57 KB. Hindi adds 70.6 KB of Hind and 4.7 KB `hi.json` on the first Hindi visit (about 133 KB).
That is over the 60 KB guide; the justification: swap means first paint never waits (Noto Sans Devanagari renders
first), the service worker caches the fonts after one visit, and shipping no Devanagari face is what made the
old Hindi look mismatched. If the owner wants it lighter: drop Hind 600 (-35 KB) and use the system face for bold.

## 4. Components

- **Top bar** (56 px, sticky): mark plus app name (a link home), the language button naming the other language in
  its own script (`lang` attribute set), a Settings button (sliders icon, `aria-label`).
- **108 bar**: full-width hazard fill, white text, phone icon, sticky under the top bar on emergency answers and the
  offline screen; a 102 half appears for C-section and newborn ICU. Home has a compact row: "Emergency now? Call
  108" with a 108 button.
- **Answer panel (readout)**: 4 px left edge (amber for call first, green when Likely), "Call first" h2, facility
  name 24/600, place and ownership, minutes in Plex Mono 36, the range and km, the sure line (band shape plus band
  word plus one instruction, on its tint), green Call button 56 px with the number, then Listen and "Why this place?"
  side by side.
- **Next rows**: a plain list with dividers, rank in mono, name (link to its Why page), minutes and band, a 48 px
  outlined call button with `aria-label` "Call <name>".
- **Band mark**: likely = green disc with tick; not confirmed = amber diamond with "?" and ink outline; unlikely =
  square with a cross. Always the word next to it.
- **Route strip**: one lane, x is minutes, capsules for each arrival range, the limit as a red rule with the time past
  it hatched, the line drawing in 700 ms, the first stop pulsing. `aria-hidden`; the numbered stop list under it is
  the accessible version, then the window line ("First care in about 19 min, inside the 60 min limit") and the
  legend list. Planned care shows the steps list only (no clock).
- **Service tiles**: 2 columns at 360 px, 96 px tall, icon 32 px over the label; emergency icons in hazard text
  colour. Custom inline SVG, 24 px grid, 2 px round stroke: pregnant woman, incubator, bandage, flame, kidney with a
  drop, scanner ring, heart with pulse, question mark.
- **Mic button**: full-width ink-filled "Speak" button, the first control under "What care is needed?".
- **Ledger**: table, Condensed column heads, points right-aligned in mono, a double rule over the total.
- **Facts list** (`dl`): Condensed term, plain value; warnings get a triangle.
- **Track record**: the sentence first, then a three-part bar (green right, hatched red wrong, grey no answer) with
  its key; the bar is `aria-hidden` because the sentence carries the numbers.
- **Settings controls**: big radio rows for language (each label in its own script), segmented radios for text
  size and theme, checkboxes for voice.
- **Offline notice**: amber-tinted row with the no-signal icon, what is shown, then what to do next, then "Try again".
- **Bottom nav** (64 px, fixed): Home, Recent, Area, How it works; icon over word; `aria-current="page"` gets an
  ink top bar.

## 5. Language system

### Rules

1. One setting, `rs.lang` in localStorage (`hi` or `en`). It drives every string, `<html lang>`, read-aloud voice,
   speech-to-text language, the slip, the family card, field-report lines, pulse, Area and How.
2. First launch (no `rs.lang`): full-screen chooser, the only screen with both scripts. Two 80 px radio rows,
   "हिन्दी" and "English", the one matching `navigator.language` pre-selected and listed first; "Continue" follows
   the selection's language.
3. After that: the top-bar button shows the other language's own name and switches everything in one tap. The
   screen re-renders in place; focus returns to the same button and the scroll position is kept. Settings has the
   same choice as radios (focus stays on the chosen radio).
4. Removed: the read-aloud Hindi/English pair (`input.js speakHtml`), the voice radio pair (`voice.js`), the slip
   language pair (`app.js slipScreen`), the pulse language select (`pulse.js`), and every inline
   `<span lang="hi">(...)</span>`. `rs.voice.lang` is migrated into `rs.lang` once and then ignored.
5. One language on screen. Exceptions, each labelled: facility names and listing quotes stay in their original
   script with `lang="en"`; a quote carries "From its own listing, in English" and, in Hindi mode only, the
   "हिन्दी में पढ़ें" button from `translate.js` (PR #109).

### Files and keys

- `app/static/i18n/en.json` and `app/static/i18n/hi.json`, flat keys, same key set (a test checks parity).
  Fetched once with the shell, cached by the service worker, about 2.5 and 4.7 KB gzip.
- Key naming: `<screen>.<thing>` in lower snake case. Namespaces: `app`, `lang`, `nav`, `home`, `svc.<service
  key>`, `danger.<n>`, `sos`, `ans` (answer), `band.<band>`, `op.<operator>`, `why`, `call` (call-ahead script),
  `out` (call outcomes), `slip`, `card` (family card), `field` (field reports), `pulse`, `area`, `how`, `stories`,
  `describe`, `note` (scan), `place` (change location), `gps`, `set` (settings), `off` (offline), `err`, `speak`,
  `punct.stop` ("." or "।").
- Slots are `{name}`; a helper `t(key, vars)` returns escaped text. Payload values are passed already wrapped in
  `F()` so their `data-f` markers survive inside translated sentences.
- `engine` (hi.json only): exact English engine template to Hindi, with `{slot}` capture for values that stay as
  they are (`{label}` maps to `query.service_label.hi`). Covers `band_reason`, `why_not.reason`, `call_ahead`
  question and `asked_because`, `is_real`, `where_check`, `flags`, `purpose_word`, `type_word`, `pathway_name`,
  `contributions.label`, `say_to_family.en`, `vs_direct.text`. Unknown text is shown in English with `lang="en"`.
  Long term, the engine should send codes (it already does for `why_not.reason_code` and `band`) and fill
  `say_to_family.hi`; the table is the interim.

### Folding in the existing Hindi

| Source today | Moves to | Note |
|---|---|---|
| `app/services.py` `label_hi` (there is no services.json) | stays server-side (`query.service_label.hi`); tile labels come from `svc.*` | Tile and payload labels must match: one test compares them |
| `app/static/speech_templates.json` `hi` and `questions` | `speak.*` keys plus the `engine` table; file removed | speech.js reads `t()`; `questions` pairs become engine rows |
| `community.js` `T` pairs `[en, hi]` | `out.*`, `field.*` keys | `say()` becomes `t()` |
| `pulse.js` `T.en` / `T.hi` | `pulse.*` | the language select is deleted |
| `journey.js` `T.en` / `T.hi` | `card.*` | the card is built in the app language |
| `slip.js` `STRINGS.en` / `.hi` | `slip.*` | `toHtml(m, lang)` keeps its `lang` argument, fed from `rs.lang` |
| `translate.js` labels | `why.translate`, `why.tr_label`, `why.tr_na` | "हिंदी में पढ़ें" becomes "हिन्दी में पढ़ें" (glossary spelling) |
| `app.js`, `input.js`, `voice.js`, `offline.js`, `how.js`, `stories.js` English literals | their namespace | a few hundred literals (not counted exactly); a grep test fails on new English literals in templates |

Glossary terms fixed in hi.json (kb/taxonomy/HINDI_GLOSSARY.md): संभावना ज़्यादा / पक्का नहीं / संभावना कम for the
bands; "पहले फ़ोन करके पूछें" for the band instruction and "जाने से पहले फ़ोन करें" for call-before-going; इमरजेंसी;
अस्पताल; एम्बुलेंस, मुफ़्त; गर्भवती महिला या शिशु (102); स्वास्थ्य कार्यकर्ताओं की रिपोर्ट; रेफ़रल पर्ची; यात्रा कार्ड;
आयुष्मान कार्ड (for PM-JAY); सेवा, इलाज (treatment only), जाँच; सेव हो गया; पहला विकल्प, दूसरा विकल्प; "ना कहा" for
said no; "यह डॉक्टर की सलाह नहीं है"; nukta on फ़ and ज़, chandrabindu where standard, digits, no slashes. Open
question for the owner: the brief writes "हिंदी", the reviewed glossary writes "हिन्दी"; the prototype follows the
glossary.

### Strings that need a Hindi version

The prototype's `en.json` and `hi.json` already hold 143 keys (same set in both, plus 33 engine rows) for the chooser, top bar, nav, home, both answers,
Why, Settings and offline (read them as the list for those screens). Still to extract from today's code, by key
namespace and source:

- `place.*` and `gps.*` (`app.js changeScreen`, `gpsScreen`, `getGps` errors): 14 strings.
- `describe.*`, `note.*` (`input.js` describe, confirm card, scan): 30 strings; `voice.*` (`voice.js`): 10.
- `area.*` (`app.js areaHtml`, `gapHtml`, `publicHtml`, `emergencyNumbers`): 35 strings.
- `cmp.*` (Compare depth, `COMPARE_ROWS`): 16 strings.
- `why.*` remainder (`testRecordHtml`, `tieHtml`, verify results, call-ahead script lines 1, 2, 4, 5): 25 strings.
- `slip.*` (about 40, already paired in `slip.js`), `card.*` (about 25, paired in `journey.js`), `pulse.*` (about
  30, paired in `pulse.js`), `out.*` and `field.*` (about 15, paired in `community.js`).
- `how.*` and `stories.*`: the page chrome only (about 20); the How and story bodies come from `/api/how` and
  `/api/stories` and need a `hi` field server-side, or stay English with a "This page is in English" line in Hindi
  mode.

## 6. Accessibility checklist (WCAG 2.2 AA, AAA contrast for text)

- [x] Text contrast 7:1 or more in both themes (table above); axe `color-contrast-enhanced` passes.
- [x] Non-text contrast 3:1 for control borders, focus ring and band shapes.
- [x] Every target 48 by 48 px or larger (script check in `screens/axe_report.json`: none smaller).
- [x] Text size 100 / 125 / 150 % via the root font size; everything is in rem; at 150 % on 360 px there is no
      horizontal scroll on any screen (checked by the script).
- [x] Devanagari line-height 1.8 body, 1.5 headings, 1.4 nav; no fixed heights; matras unclipped at 150 %.
- [x] Landmarks: `header`, `nav` (108, main nav), `main`; one `h1` per screen; `h2` per section; skip link.
- [x] Live region `#status` announces "3 places found. Call <name> first." and call-outcome taps.
- [x] Focus: route change focuses the `h1`; language switch keeps focus on the control used; visible 3 px ring
      plus a 2 px gap; no positive tabindex.
- [x] Never colour alone: bands are shape plus word; the limit is a rule plus hatching plus a label; route checks
      have a tick or triangle plus words.
- [x] `prefers-reduced-motion`: no draw, no pulse, no press scale.
- [x] Dark mode: follows the phone or the Settings choice.
- [x] Read-aloud on every answer (Listen in the readout) and in the Why page through the call-ahead questions;
      voice language is the app language.
- [x] Icons always with words, except the top-bar Settings and row call buttons, which have `aria-label`.
- [x] Plain language: short sentences on the answer screen, no internal ids or model names in view. The ledger's
      "model score (derived/v2)" row is shown through the engine table; removing the path is #121 item 4.
- [x] Errors and offline say what to do next ("Emergency? Call 108 now. ... tap Try again.").
- [ ] Not yet checked: TalkBack on a real Android phone, a Hindi native-speaker read of hi.json, sunlight test.

## 7. Information architecture and screens

Routes (hash, as today): `#/lang` (new), `#/`, `#/plan`, `#/why/<rank>` (Why page; `#call` anchor kept),
`#/slip/<rank>`, `#/settings` (new), `#/recent` (new: the RECENT list plus "How did a referral go?"),
`#/pulse` becomes `#/area` (Your area plus the Area depth), `#/how` (How it works plus a link to Data stories),
`#/describe`, `#/note`, `#/change`, `#/gps`, `#/report`. Compare and Area depth move off the answer screen: Compare
is a link at the end of the Why page ("Compare all options side by side"), Area is the bottom-nav tab.

Screen by screen at 360 px (`*` = above the fold at 100 %):

```
Chooser                      Home                          Emergency answer (Pusa trauma)
+------------------------+   +--------------------------+  +----------------------------+
|                        |   | o-* Referral Saathi [हि][=]|  | o-* Referral Saathi  [हि][=]|
|  o-*                   |   | Emergency now? Call 108   |* | (tel) Call 108 ambulance   |* sticky
|  अपनी भाषा चुनें          |   |                  [108]    |  | Accident or injury         |*
|  Choose your language  |   | Patient is here           |* | Near 25.60, 85.95. Data... |*
| (o) हिन्दी               |   | [pin 25.60, 85.95  Change]|* | |Call first                |*
| ( ) English            |   | What care is needed?      |* | |Sub Divisional Hospital   |*
| [ आगे बढ़ें ]            |   | [ mic  Speak ]            |* | |Rau Pusa. Government      |*
| इसे बाद में सेटिंग में ... |   | [C-section ][Newborn ICU] |* | |19 min                    |*
+------------------------+   | [Accident  ][Burns      ] |* | |14 to 27 min, 17 km       |*
                             | [Dialysis  ][MRI scan   ] |  | |<?> Not confirmed. ...    |*
                             | [Heart     ][Something  ] |  | |[ (tel) Call 0000 000000 ]|*
                             | [Type in words][Scan note]|  | |[Listen] [Why this place?]|*
                             | > Danger signs now?       |  | If they say no             |
                             | Saved for use without ... |  | 2 Miracare  27-46, Likely (tel)
                             |[Home][Recent][Area][How]  |  | 3 Mata Chandrakala ...  (tel)
                             +--------------------------+  | Route for this emergency   |
                                                           | o--(1)==|////(2)====////   |
                                                           | 1 SDH Pusa, first care     |
                                                           | 2 Ganpati, definitive care |
                                                           | (v) First care in about 19 |
                                                           | legend: route, range, late |
                                                           +----------------------------+
```

The planned answer (Patna dialysis) is the same without the 108 bar, with a green edge (Likely), and "Steps for
this care" (assessment, fistula, regular sessions) in place of the strip. The Why page order: back link, name and
band, listing quotes (labelled, translate button in Hindi), say this to the family, ask on the phone (Call, the
questions with their reasons, the four outcome buttons), track record, why not the nearest (plus what would change
it), how we decided (ledger), checks on this listing (real, map point, warnings, field reports), next steps (slip,
family card, map, website check). Settings: language, text size with a sample line, voice (read aloud, speak to
search), screen colour, saved data. Offline: 108 bar, the notice and what to do, Try again, the nearest saved
option by straight-line km with its Call button, the next two, and the data age.

Measured at 360 by 800 (full-page height, English / Hindi):

| Screen | Before (app/checks) | After |
|---|---:|---:|
| Emergency answer (trauma) | 9,866 | 1,615 / 1,829 |
| Planned answer (dialysis) | 5,813 | 1,372 / 1,516 |
| Why page (trauma #1) | (on the answer page before) | 3,166 / 3,423 |

### Faithfulness markers kept per screen (`app/tests/test_faithfulness.py`)

- Answer: `options.0.name`, `.town`, `.travel.minutes|low|high|km`, `.band` or `.model_band` (kind `band`),
  `.phone.display`; `options.1-2.rank|name|travel.low|travel.high|band`; `itinerary.plans.0.stops.<k>.name|
  purpose_word|eta_low|eta_high`, `window_checks.0.eta_minutes|limit_minutes|met`, `itinerary.pathway_name`;
  `field_reports.note.<lang>`. Dropped from this screen (now on Why): quotes, track record, call-ahead.
- Why: every `options.<i>` field today's why page marks (name, town, evidence quote, call_ahead question and
  asked_because, track_record n/k/c/u, contributions label/points/sum, is_real, where_check, flags, say_to_family),
  plus `why_not.<k>.name|travel.km|reason` and `what_would_change.name|first_name`.
- Device text (`data-device`): the location line and GPS accuracy, as today.
- New kind `template`: a Hindi rendering of an engine template. The test must accept it when the English payload
  value matches the engine row and the shown text equals that row's Hindi with the same slot values.
- `test_every_route_field_is_shown` waits for "Suggested route" and wants every route leaf. The compact answer shows
  stop names, purposes, ETAs and window checks; the remaining leaves (p, weakest_capability, dwell, fallback,
  evidence, totals, vs_direct) move to a "Route details" section on the Why page of option 1. The test's wait text
  and route set must be updated in the same PR.

## 8. Migration plan

Order keeps `pytest app/tests` green after each step; each step is one PR.

1. **Strings first, no visual change.** Add `app/static/i18n/en.json` and `hi.json` (start from the prototype
   files), `t()` and `rs.lang` in `app.js`, the sw.js shell list, and `test_i18n.py` (key parity, no empty values,
   glossary spellings, no `<span lang="hi">` left in `app/static/*.js`). Replace English literals in `app.js`
   screen by screen with `t()`; keep markup and `data-f` paths identical so test_faithfulness passes unchanged.
2. **One language.** Delete the inline Hindi spans, the read-aloud and voice language pairs (`input.js
   speakHtml`, `voice.js` radios), the slip language buttons and the pulse language select; feed `rs.lang` into
   `RSSpeech.buildSpeech`, `initVoice`, `RSSlip.toHtml`, `RSSlip.shareJourney`, `RSPulse.initPulse`,
   `RSCommunity.say`. Fold the five `T` tables into the JSON files. Add the chooser (`#/lang`) and the top-bar
   switch. Update `test_speech.py`, `test_slip.py`, `test_pulse.py` to pass the language instead of clicking the
   old toggles; extend test_faithfulness's band words and add kind `template`.
3. **Tokens and fonts.** Replace the token block and type in `app.css`; add `app/static/fonts/` (the six woff2 and
   OFL licences from the prototype) to the shell allowlist in `app.py` and the sw.js cache; preload Barlow 500 and
   600 in `index.html`. Re-run `app/checks/a11y_check.py`.
4. **Answer screen.** Rewrite `planScreen` as readout, next rows, compact route; move quotes, track record,
   call-ahead and route details to `whyScreen`; drop the depth toggle from the answer (Compare link on Why, Area in
   the nav). Update `test_every_route_field_is_shown` (wait text and the Why page for the details) in this PR.
5. **Why, Settings, offline, nav.** Bottom nav and `#/settings`, `#/recent`, `#/area`; the Why page sections;
   `offline.js` `render()` restyled to the same readout. Text-size setting on `html` font-size.
6. **Engine codes (server).** Send `say_to_family.hi` and reason codes so the `engine` table can shrink; until
   then it stays in `hi.json`.
7. **Checks.** Extend `app/checks/a11y_check.py` to both languages and 150 % text, regenerate
   `app/checks/screens/`, and update design/ui/DESIGN.md to point here.

Files touched: `app/static/index.html`, `app.css`, `app.js`, `input.js`, `voice.js`, `speech.js` (templates from
`t()`), `speech_templates.json` (deleted in step 2), `slip.js`, `journey.js`, `community.js`, `pulse.js`,
`offline.js`, `translate.js`, `how.js`, `stories.js`, `sw.js`, `app/app.py` (shell allowlist),
`app/tests/test_faithfulness.py`, `test_speech.py`, `test_slip.py`, `test_pulse.py`, new `test_i18n.py`.

## 9. Verification of this design

- `screens/`: 7 screens x English and Hindi x light and dark at 360 px, the answer and Why pages at 150 % text in
  both languages, and 1280 px for home, answer (both languages) and Why. 36 screenshots.
- axe-core 4.10.2 (WCAG 2.0/2.1/2.2 A and AA, best practice, plus `color-contrast-enhanced`) on every run:
  0 violations. No horizontal scroll on any run. No target under 48 px. Report: `screens/axe_report.json`.
- Not done: a test on a real Android phone in sunlight, TalkBack, and a native Hindi review of `hi.json`.
