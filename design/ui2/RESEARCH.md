# UI2 design research brief (ASHA hospital referral app, Bihar and UP)

Scope: Hindi-first, low-literacy users, cheap Android phones at 360 px, used outdoors. Time-boxed (8 lookups).
Rules marked [unverified] come from general practice, not from a page I opened in this pass.

## 1. Avoiding the "AI-generated" look

- Drop the purple-to-blue gradient (from-violet-500 to-indigo-600 and similar). It is the most cited tell. Use one flat brand colour taken from the domain, such as the UX4G primary, plus semantic red, amber and green. Source: https://www.925studios.co/blog/ai-slop-design-tells and https://uxdesign.cc/purple-6a6d1786f6c1
- Do not ship the default stack untouched: Inter, stock shadcn components, Lucide icons and default Tailwind spacing. One analysis found that v0, Lovable and Claude Code all produce it. Change the font first, then define your own tokens. Source: https://dev.to/alanwest/how-to-fix-the-ai-generated-look-in-your-frontend-1ahh
- No centered hero, no pill badge above a headline, and no row of three rounded feature cards. The first screen of a work tool is the task itself: a patient condition picker or a hospital list. Source: https://world.hey.com/kostac/spot-the-slop-a-ui-designer-s-guide-to-fixing-ai-defaults-4c448c9c
- Ban glassmorphism, blurred backdrops, soft drop shadows on every card, and emoji used as icons. They lose contrast in sunlight and render differently across Android versions. Use 1 px borders and solid fills. Source: https://github.com/Laith0003/ux-skill/wiki/Anti-AI-slop-ban-list
- Do not nest cards inside cards (rounded-2xl card soup), and show at most one badge per row. Use a plain list with dividers, and let a single status chip such as "ICU available" carry the meaning. Source: https://cdn.jsdelivr.net/npm/pixelslop@0.3.8/dist/skill/resources/ai-slop-patterns.md
- Make every choice explicit and tie it to the user, not to the defaults. The tells are "fluent averages", not errors in themselves. Source: https://uxdesign.cc/ai-design-isnt-ugly-it-s-fluent-and-that-s-the-problem-131b2f4eb78c

## 2. mHealth for ASHAs, CHWs and low-literacy users

- Pair each question and answer with an audio prompt that plays on tap. M-SAKHI (built on CommCare) gives every question and response audio, and its evaluation found better ASHA knowledge and capacity to do the work. Source: https://chwcentral.org/wp-content/uploads/Evaluation-of-Impact-of-the-M-SAKHI-mHealth-App-on-Knowledge-Skills-and-Acceptance-of-use-of-App-by-Maternal-and-Child-Health-Community-Health-Workers-in-Rural-Maharashtra.pdf
- Always put a short Hindi label next to an icon, and test icons with real users. Icons that users found confusing were replaced after field feedback, and audio was added to most of them. Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC7971376/table/tab5
- Use pictures that match the text closely and carry little extra detail, with one idea per screen. Short sentences, no paragraphs. Source: https://cdc.gov/health-literacy/php/develop-materials/guidance-standards.html
- Show urgency twice, through colour and through type weight or an icon, so it still reads for users with weak literacy or colour vision. This follows the CHT task list redesign. Use the CHT icon set (CC BY-SA 4.0, SVG). Source: https://medic.org/stories/colors-cues-and-co-creation-designing-task-lists-ui-for-real-world-chw-priorities/ and https://docs.communityhealthtoolkit.org/design/icons
- Use checklist-style guided steps, not free-form forms, and add a confirm screen before any irreversible action, such as "Refer to X? Call now". ImTeCHO and mSakhi both replaced paper checklists with step-by-step guided flows. Source: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4335194/ and https://www.qualcomm.com/media/documents/files/india-msakhi.pdf
- Work offline first. Cache the last facility list and show "Data as of <date>" on every result, so the user knows how old the data is. Trust cues: the source (for example a government facility registry), a verified date, and a tel: link to the facility. [unverified: general CHT and CommCare practice] Source: https://docs.communityhealthtoolkit.org/design

## 3. Indian government standards (UX4G, GIGW 3.0, bilingual UI)

- Typeface: UX4G uses Noto Sans as its base UI face, with Noto Sans Display for large headings only. Load Noto Sans Devanagari explicitly. Most fonts cover Latin only, and without it Hindi falls back to whatever the device has. Source: https://ux4g.gov.in/foundations/typography
- Set Devanagari line-height to 1.8, as UX4G specifies, to leave room for the parts that sit above and below the line. Source: https://ux4g.gov.in/foundations/typography
- Colour: use UX4G's primary, semantic and neutral ramps (15 ramps, delivered as CSS custom properties). Apply only the primary colour inside components. Secondary and tertiary colours are tokens only. Source: https://ux4g.gov.in/get-started/for-developers and https://ux4g.gov.in/resources/theme-craft
- Components target WCAG 2.1 AA. GIGW 3.0 also aligns with WCAG 2.1 AA: 4.5:1 text contrast, a lang attribute on every page and every switched string, and no meaning carried by colour alone. [GIGW text not fetched in this pass] Source: https://doc.ux4g.gov.in/ and https://guidelines.india.gov.in/
- Language switcher: label each option in its own script, for example "हिन्दी" and "English". UX4G's pattern adds the English name in brackets, as in "हिन्दी (Hindi)". Never use flags, since a flag stands for a country, not a language. Set lang="hi" or lang="en" on each option. Source: https://doc.ux4g.gov.in/web/llms/patterns/feedback-communication-language-switcher.md, https://designsystem.digital.gov/patterns/select-a-language/two-languages/ and https://design-system.service.gov.uk/components/language-navigation/
- Put the switcher in the persistent top bar and remember the choice. Show one language at a time, not stacked Hindi over English, to halve text density at 360 px. The exception is clinical terms that ASHAs know in English (ICU, NICU, C-section), which keep the Latin term in Hindi text. [placement and one-at-a-time rule unverified for GIGW] Source: https://design-system.service.gov.uk/components/language-navigation/

## 4. Devanagari UI typography on Android

- Faces: Noto Sans Devanagari is the default and ships on Android. Hind was designed for UI, and its Devanagari base characters are 94% of Latin cap height. Mukta is a good UI alternative. Do not set Hindi in Inter or Roboto, which fall back per glyph. Source: https://fonts.google.com/specimen/Hind/about
- Size: Devanagari body text at least 16 px, and about 1 to 2 px larger than the Latin text next to it, because the headline sits below cap height and the matras are small. [ratio unverified] Source: https://fonts.google.com/specimen/Hind/about
- Line-height: 1.8 for Devanagari body text (UX4G), and at least 1.4 for single-line labels. Never set a fixed height with overflow:hidden on a text container. Source: https://ux4g.gov.in/foundations/typography
- Avoid clipped matras. Size buttons, chips and inputs with min-height and vertical padding, not a fixed height or a line-height of 1. Clipping comes from Latin-tuned line metrics, and Noto, Nirmala and Mangal all clipped in fixed-height UI. Source: https://community.articulate.com/discussions/discuss/hindi-text-clipping-in-player-ui---looking-for-a-devanagari-safe-font/1242062 and https://community.notepad-plus-plus.org/post/103376
- Do not use letter-spacing or text-transform on Devanagari. Tracking breaks conjuncts and the headline bar. [unverified] Source: https://www.w3.org/TR/deva-gap
- For outdoor use, set body weight to 500 rather than 400, and use dark text on an off-white background, not grey on white. Thin strokes in Devanagari fade in direct sun. [unverified field practice] Source: https://ux4g.gov.in/foundations/typography
