# Hindi review, 2026-11-22

Desk review of every Hindi string in the app by a reviewer reading Hindi at native level. Not a field test: no ASHA,
family or hi-IN phone voice was involved. Terms chosen are in ../HINDI_GLOSSARY.md. The "(Hindi draft, not
reviewed)" markers on the slip, card and pulse stay until a field check (issue #10); removing them is the team's call.

## Scope and counts

User-facing strings reviewed: about 233 (speech_templates.json 26, community.js 38, pulse.js 40, community/pulse.py
7, community/field.py 24, journey.js 35, slip.js 34, app.js 16, input.js 5, services.py 7, voice.js 1).
speech.js and understand.py have no user-facing Hindi.

Matching-only strings reviewed: services.json (11 category names, 67 service names), hindi_phrases.json (183
service phrases, 39 danger phrases), the Hindi entries in understand.py DANGER and _TERMS, and the
generated lexicon.json.

Changed: 71 user-facing strings, by main reason:

| Kind | Count |
|---|---|
| Spelling or matra | 3 |
| Gender, number or case | 11 |
| Unnatural or too formal | 15 |
| Wrong medical or factual meaning | 9 |
| Inconsistent term | 27 |
| Read-aloud (TTS) problem | 4 |
| Could read as a promise or confirmation | 2 |

Matching: 6 phrases removed (wrong service), 4 added. No danger phrase removed.

Slots and slot order are unchanged in every template. route_first and route_next keep "पहले {name} पर" and "फिर
{name} पर", which test_speech.py checks. The one test change is the pinned band words in test_speech.py.

## app/static/speech_templates.json (read aloud)

| Key | Before | After | Reason |
|---|---|---|---|
| call_102 | गर्भवती महिला या नवजात शिशु के लिए ... | गर्भवती महिला या शिशु के लिए ... | Meaning: 102 serves infants up to one year, not only newborns. |
| abstain_some | हम पक्का नहीं कह सकते कि पास का कोई अस्पताल यह इलाज करता है। नीचे के अस्पतालों की लिस्टिंग में यह लिखा है, जाने से पहले फ़ोन करके पक्का करें। | पास के किसी भी अस्पताल में यह सेवा पक्की नहीं है। नीचे दिए अस्पतालों की लिस्टिंग में यह सेवा लिखी है, पर जाने से पहले फ़ोन करके पूछें। | Meaning: "इलाज" is wrong for MRI; shorter. |
| abstain_none | हम पक्का नहीं कह सकते ...। हमारे डेटा में पास का कोई अस्पताल यह इलाज नहीं बताता। | हमारे डेटा में पास के किसी भी अस्पताल की लिस्टिंग में यह सेवा नहीं लिखी है। | Safety: the old line could be heard as "no hospital nearby does this". Now it says what our data shows. |
| first | सबसे पहले: {name}, ... | पहला विकल्प: {name}, ... | Consistency: pairs with दूसरा विकल्प (backup). |
| route_first | सुझाया रास्ता: पहले {name} पर {purpose}, शुरू से लगभग {low} से {high} मिनट। | सुझाया गया रास्ता: पहले {name} पर, {purpose} के लिए, निकलने के लगभग {low} से {high} मिनट बाद। | Grammar: "{name} पर पूरा इलाज" had no verb or postposition; "शुरू से" was unclear. Same term as the slip. |
| route_next | फिर {name} पर {purpose}, शुरू से लगभग ... मिनट। | फिर {name} पर, {purpose} के लिए, निकलने के लगभग {low} से {high} मिनट बाद। | As above. |
| band.likely | संभावना है | संभावना ज़्यादा | Consistency with pulse; clearer contrast with संभावना कम. |
| band.not_verified | पहले फोन करके पूछें | पक्का नहीं, पहले फ़ोन करके पूछें | Consistency (band word पक्का नहीं, as on the pulse) and nukta; mirrors English "not verified, call first". |
| purpose.stabilise | पहला इलाज, हालत संभालना | पहले इलाज और हालत संभालने | Case: now fits "{purpose} के लिए". |
| purpose.definitive | पूरा इलाज | पूरे इलाज | Case, as above. |
| purpose.access | डायलिसिस के लिए फ़िस्टुला या लाइन | फ़िस्टुला बनवाने या लाइन डलवाने | Meaning: names the procedure, as dialysis patients say it. |
| questions[0] | क्या आज यहाँ {label} का इलाज हो सकता है? | क्या आज {label} के लिए मरीज़ को ला सकते हैं? | Meaning: "MRI स्कैन का इलाज" is wrong; the new form works for every tile label. |
| questions[1] | क्या आप {label} का इलाज खुद यहीं करते हैं, या मरीज़ को कहीं और भेजते हैं? | {label} के लिए क्या आप मरीज़ को यहीं देखते हैं, या कहीं और भेजते हैं? | Meaning, as above. |
| questions[3] | क्या यह इसी शहर की शाखा है, या कोई दूसरी शाखा? | क्या यह इसी जगह वाली ब्रांच है, या कोई दूसरी ब्रांच? | Too formal ("शाखा"); many facilities are not in a शहर. |
| questions[5] | खर्च कितना होगा? क्या PM-JAY, यानी आयुष्मान कार्ड, चलता है? | खर्च कितना होगा? क्या आयुष्मान कार्ड चलता है? | TTS: the voice spells out "PM-JAY". |
| no_hindi_voice | हिंदी | हिन्दी | Spelling consistency with the language buttons. |

Reviewed, unchanged: call_108, reason, backup, this, ask, band.unlikely, purpose.assess, purpose.recurring,
questions[2], questions[4], cannot_speak.

## app/static/journey.js (family journey card, shown and read aloud)

| Key | Before | After | Reason |
|---|---|---|---|
| sos | आपात नंबर | इमरजेंसी नंबर | Consistency, plainer. |
| listed | इस सेवा के लिए सूची में है | लिस्टिंग में यह सेवा लिखी है | Safety: "सूची में है" read like an official list; now it says what is written. |
| items[2] | आयुष्मान / PMJAY या JSSK कार्ड | आयुष्मान कार्ड या जच्चा-बच्चा (MCP) कार्ड | Meaning: there is no JSSK card; the card a pregnant woman carries is the MCP card. Slash and PMJAY were also bad for TTS. |
| items[3] | पुरानी रिपोर्ट | पुरानी जाँच रिपोर्ट | Meaning: "रिपोर्ट" also means a field report in this app; this is test reports. |
| say108 | आपात स्थिति में 1 0 8 ... | इमरजेंसी में 1 0 8 ... | Consistency. |
| say102 | गर्भावस्था या शिशु: 1 0 2 पर फ़ोन करें। | गर्भवती महिला या शिशु के लिए 1 0 2 पर फ़ोन करें। | Meaning and grammar: names the person; matches the read-aloud template. |

Reviewed, unchanged: title (यात्रा कार्ड), call108, call102, go, stops, for, address, geo, osm, check, bring, items
0, 1, 4, callTitle, ask, askDefault, notMedical, old, read, big, print, tools, noSpeech, noHi, sayStop, sayPhone,
sayBring, sayAsk.

## app/static/slip.js (referral slip; also used on the journey card)

| Key | Before | After | Reason |
|---|---|---|---|
| title | रेफरल पर्ची | रेफ़रल पर्ची | Spelling (nukta, as everywhere else). |
| ifNot | अगर नहीं | वहाँ न हो सके तो | Unnatural: "if not" alone is unclear on a slip. |
| call | फ़ोन से पूछा | फ़ोन पर पूछताछ | Unnatural as a row label; it repeated the outcome text. |
| noCall | अभी फ़ोन से पूछा नहीं। ... | अभी फ़ोन पर नहीं पूछा। ... | Word order. |
| numbers | आपात स्थिति: 108 (एम्बुलेंस, मुफ़्त)। | इमरजेंसी: 108 (एम्बुलेंस, मुफ़्त)। | Consistency. |
| n102 | गर्भावस्था या शिशु: 102 (मुफ़्त)। जवाब नहीं? 108 पर फ़ोन करें। | गर्भवती महिला या शिशु: 102 (मुफ़्त)। जवाब न मिले तो 108 पर फ़ोन करें। | Meaning, and the same sentence as the read-aloud. |
| worse | ... सबसे नज़दीकी 24x7 इमरजेंसी में जाएँ। | ... सबसे पास की 24 घंटे खुली इमरजेंसी में जाएँ। | TTS: "24x7". |
| made | बनाई गई | बनाने का समय | Gender: also shown on the journey card, and कार्ड is masculine. |

Reviewed, unchanged: service, go, phone, noPhone, travel, about, min, km, map, why, said (4), at, note, name, asOf,
old, ask, listing, source, route, stay.

## app/static/community.js (report screens and messages)

| Key | Before | After | Reason |
|---|---|---|---|
| noted | ... मरीज़ की कोई जानकारी नहीं। | ...; मरीज़ की कोई जानकारी नहीं भेजी जाती। | Unnatural: the clause had no verb. |
| none | ... स्लिप बनाने पर ... | इस फ़ोन पर हाल का कोई रेफ़रल नहीं है। रेफ़रल पर्ची बनाने पर ... | Consistency (पर्ची). |
| turned_away | लौटा दिया | मरीज़ को लौटा दिया | Consistency with मरीज़ को ले लिया. |
| queued | रिपोर्ट सहेजी गई। ... | रिपोर्ट सेव हो गई। ... | Consistency (सेव). |
| slipMade | स्लिप बनी | पर्ची बनी | Consistency. |
| weight | ... अकेले रिपोर्ट से कोई अस्पताल "Unlikely" नहीं होता। | ... सिर्फ़ इन रिपोर्टों से कोई अस्पताल "Unlikely" (संभावना कम) नहीं बनता। | Consistency: keeps the on-screen English label and adds the Hindi band word. |
| cardShared | परिवार कार्ड भेजा गया। | यात्रा कार्ड भेजा गया। | Consistency with the card's own title. |
| cardSaved | परिवार कार्ड डाउनलोड में सहेजा गया। ... | यात्रा कार्ड डाउनलोड में सेव हो गया। ... | Consistency. |
| cardFailed | परिवार कार्ड नहीं बन सका। WhatsApp या SMS स्लिप भेजें। | यात्रा कार्ड नहीं बन सका। WhatsApp या SMS से पर्ची भेजें। | Consistency. |
| no_bed | बिस्तर खाली नहीं | बेड खाली नहीं | Unnatural: hospitals say बेड. |
| machine_down | मशीन ख़राब | मशीन खराब | Spelling, same as field.py. |

Reviewed, unchanged: reasonQ, notOffered, notToday, skip, home, skipped, title, which, happened, accepted, whyAway,
wait, lt_30m, 30_120m, gt_2h, unknown, send, pickFirst, reported, privacy, cardCancelled, service_not_here,
equipment_absent, referred_elsewhere_for_this_service, doctor_absent, asked_to_pay, closed_now.

## app/static/app.js and app/services.py (tiles, label_hi, inline Hindi)

| Where | Before | After | Reason |
|---|---|---|---|
| tile and label_hi, trauma_emergency | एक्सीडेंट / चोट | एक्सीडेंट या चोट | TTS: the label goes into spoken questions and the voice reads the slash. |
| tile and label_hi, burn_care | जलना | जलने की चोट | Grammar: "जलना का इलाज", "जलना के रेफ़रल" were wrong. |
| tile and label_hi, cardiac_surgery | दिल का ऑपरेशन | दिल की सर्जरी | Grammar: "दिल का ऑपरेशन के लिए" is wrong; a feminine head keeps the oblique case right. |
| field reports heading | (फ़ील्ड रिपोर्ट) | (स्वास्थ्य कार्यकर्ताओं की रिपोर्ट) | Consistency, plainer. |
| announce after Said no | दर्ज हुआ: मना किया। ... | दर्ज हुआ: फ़ोन पर ना कहा। ... | Consistency with the slip. |
| card file note | परिवार कार्ड एक फ़ाइल है ...: जगह, फ़ोन और ...। | यात्रा कार्ड एक फ़ाइल है ...। इसमें जगह, फ़ोन नंबर और साथ क्या ले जाएँ लिखा है; ... | Consistency; shorter sentences. |
| card failure fallback | परिवार कार्ड नहीं बन सका। | यात्रा कार्ड नहीं बन सका। | Consistency. |

Reviewed, unchanged: tiles ऑपरेशन से डिलीवरी, नवजात ICU, डायलिसिस, MRI स्कैन, कुछ और / पता नहीं (not read aloud and
not used in {label}); रेफ़रल कैसा रहा?, आपका क्षेत्र, हिन्दी, परिवार को भेजें.

## app/static/pulse.js (Your area panel)

| Key | Before | After | Reason |
|---|---|---|---|
| intro | ... समन्वयकों और योजनाकारों के लिए। | ... कोऑर्डिनेटर और योजना बनाने वालों के लिए। | Too formal; NHM staff say कोऑर्डिनेटर. |
| unavailable | क्षेत्र की रिपोर्ट अभी उपलब्ध नहीं हैं: रिपोर्ट स्टोर से जुड़ नहीं पाए। ... | क्षेत्र की रिपोर्ट अभी नहीं दिख सकतीं: रिपोर्ट वाले सर्वर से जुड़ नहीं पाए। ... | "रिपोर्ट स्टोर" is jargon. |
| accepted | लिया गया | बार मरीज़ को लिया गया | Grammar: shown as "5 लिया गया" after a count. |
| turnedAway | लौटाया गया | बार लौटाया गया | As above. |
| how[3] | स्वीकार होने का दायरा ... | मरीज़ को लेने की दर का दायरा ... | Unnatural; says what rate. |
| how[4] | ..., पक्की पुष्टि नहीं। | ...; इससे पक्का नहीं होता। | Consistency (पक्का). |
| how[5] | ज़िला गोल की गई जगह के सबसे नज़दीकी PIN से लिया जाता है। निर्देशांक कभी सेव नहीं होते। | ज़िला, मोटे तौर पर ली गई जगह के सबसे पास वाले पिन कोड से तय होता है। सही जगह (निर्देशांक) कभी सेव नहीं होती। | "गोल की गई जगह" is a calque of "rounded location". |
| BAND.likely | संभावित | संभावना ज़्यादा | Consistency with read-aloud. |
| BAND.not_verified | पुष्टि नहीं | पक्का नहीं | Consistency, plainer. |

Reviewed, unchanged: title, lang, draft, district, service, all, show, loading, needDistrict, badDistrict, offline,
sim, win, since, services, facilities, reasons, reports, referrals, listing, source, band, noBand, card, howTitle,
how[0], how[1], how[2], REASON (2), language button.

## app/community/pulse.py (server-built pulse sentences)

| String | Before | After | Reason |
|---|---|---|---|
| rate sentence | इतनी कम रिपोर्टों से, असली दर शायद ... | इतनी कम रिपोर्टों से, मरीज़ को लेने की असली दर शायद ... | Says which rate. |
| phone sentence | ...; यह पक्की पुष्टि नहीं है। | ...; इससे पक्का नहीं होता। | Consistency. |

Reviewed, unchanged: HIDDEN_NOTE, SIM, the counts sentence, the accepted sentence, the empty-district sentence.

## app/community/field.py (field-report lines on option cards)

| String | Before | After | Reason |
|---|---|---|---|
| SIM | डेमो के लिए नकली: | डेमो के लिए नकली आँकड़े: | Consistency with pulse; "नकली" alone had no noun. |
| REASON.no_bed | बिस्तर खाली नहीं | बेड खाली नहीं | As in community.js. |
| REBANDED | ... रिपोर्ट सूची से मेल नहीं खातीं: पहले फ़ोन करें। | ... रिपोर्ट लिस्टिंग से मेल नहीं खातीं: पहले फ़ोन करके पूछें। | Consistency (listing, call first). |
| DISAGREE | रिपोर्ट और सूची में मेल नहीं: पहले फ़ोन करें। | रिपोर्ट और लिस्टिंग में मेल नहीं: पहले फ़ोन करके पूछें। | As above. |
| ONE_REPORTER | ...; कम से कम 2 की रिपोर्ट चाहिए। | ...; कम से कम 2 स्वास्थ्य कार्यकर्ताओं की रिपोर्ट चाहिए। | "2 की" left the noun out. |
| NO_TEXT_CAP | सूची में इस सेवा के बारे में कोई वाक्य नहीं है, इसलिए केवल रिपोर्ट से यह Likely नहीं होगा। | लिस्टिंग में इस सेवा के बारे में कुछ नहीं लिखा है, इसलिए सिर्फ़ रिपोर्ट से यह Likely (संभावना ज़्यादा) नहीं होगा। | Consistency; Hindi band word added next to the on-screen label. |
| summary line | ...; सबसे नई {ago} | ...; सबसे नई रिपोर्ट: {ago} | "सबसे नई आज" had no noun. |
| availability note | ...; सबसे नई {ago}। यह उपलब्धता के बारे में है, सेवा होने के बारे में नहीं। | ...; सबसे नई रिपोर्ट: {ago}। यह उस समय की बात है; इससे यह पता नहीं चलता कि अस्पताल में यह सेवा है या नहीं। | The old sentence was a literal translation and hard to follow. |
| NOT_READ | इस जवाब के लिए दर्ज फ़ील्ड रिपोर्ट नहीं पढ़ी गईं; स्कोर सिर्फ़ सूची से हैं। | इस जवाब के लिए स्वास्थ्य कार्यकर्ताओं की रिपोर्ट नहीं पढ़ी जा सकीं; स्कोर सिर्फ़ लिस्टिंग से हैं। | Consistency; "पढ़ी जा सकीं" says the read failed. |

The Hindi lines carry the same digits as the English ones. test_faithfulness.py checks this in a browser; it was
skipped here (no playwright), so that check was not run.
Reviewed, unchanged: the other REASON entries, _ago, the accepted, phone_yes and reason parts, who_hi.

## Files reviewed with no change

- app/static/input.js: "क्या आपका मतलब {s.hi} है?", हाँ, नहीं, "फिर से बोलें या लिखें।", हिन्दी. The new tile labels
  read correctly in the question.
- app/static/voice.js: हिन्दी.
- app/inputs/understand.py: matching words only, all spelled as people type them.
- kb/taxonomy/services.json: the Hindi names are used for matching (lexicon) and not shown on tiles; no wrong
  meaning found. Category names are not shown in the app.

## Matching: kb/taxonomy/hindi_phrases.json and app/inputs/lexicon.json

Rebuilt with app/inputs/build_lexicon.py.

| Change | Phrases | Reason |
|---|---|---|
| Removed from nicu | बच्चा कमजोर, कमजोर बच्चा, बच्चा कमज़ोर, bachcha kamzor, bacha kamjor, kamzor bachcha | Wrong service: "weak child" sends a malnourished toddler to newborn intensive care. The taxonomy routes "bachcha bahut kamzor hai" to nutrition rehabilitation. Newborn phrases (नया बच्चा कमजोर, नवजात, समय से पहले, कम वजन) still match. |
| Added to nicu | कमजोर पैदा हुआ, kamzor paida | Replacement that names birth. |
| Added to burn_care | जलने की चोट | The new tile label. |
| Added to cardiac_surgery | दिल की सर्जरी | The new tile label. |

Offline accuracy after the change (test_hindi_lexicon.py): Devanagari 40/40, Hinglish 40/40, English 28/40, all
108/120, as before. No danger phrase was removed.

## Flagged, not changed

Needs a native speaker in the field:
- Band words read aloud. Check that संभावना ज़्यादा / पक्का नहीं / संभावना कम are understood when heard without
  the screen, especially by older ASHAs in Bhojpuri and Maithili areas.
- जच्चा-बच्चा कार्ड is the UP and Bihar name for the MCP card; some states say ममता कार्ड or MCP कार्ड. The English
  journey card still says "Ayushman / PMJAY or JSSK card": the English should change too.
- यात्रा कार्ड for the family card. Families may not know the word; "अस्पताल जाने का कार्ड" is a longer option.
- पर्ची for the referral slip, and रेफ़रल itself, in Jharkhand and MP tribal blocks.
- बेड vs बिस्तर, ब्रांच vs शाखा: chosen as hospital speech; confirm with ASHAs.
- 102 coverage wording "शिशु": confirm what local 102 services take (some states run 102 for all patients).

Matching phrases that may hit the wrong service or a false danger card (kept; for the team or a clinician):
- खून बदलवाना (dialysis): also means exchange transfusion for a newborn with jaundice, which is NICU.
- बच्चे को पीलिया, baby ko piliya, बच्चा दूध नहीं पी रहा (nicu): right for a newborn, wrong for an older child.
- मशीन में रखना (nicu): could be an adult on a ventilator.
- डिलीवरी के बाद खून (emergency_csection): routes postpartum bleeding to the C-section tile, as the taxonomy
  decides (it stands for CEmONC). The tile name ऑपरेशन से डिलीवरी may confuse a family in that case.
- Danger: जवाब नहीं दे रहा fires on "अस्पताल फ़ोन पर जवाब नहीं दे रहा"; बहुत खून fires on "बहुत खून की कमी" (severe
  anaemia); लकवा and मिर्गी fire on old, stable conditions. All err towards the danger card, the safe side.
- Danger signs not in the list (clinical review should decide): खून की उल्टी, पेट में बच्चा हिल नहीं रहा.

Code issues that leave English in Hindi output (out of scope for a strings review):
- {need} in "क्या आपके यहाँ {need} है?" is the engine's English text ("dialysis unit or machine").
- The journey card's call-ahead questions and route purposes are English payload text, read by the Hindi voice.
- The slip's travel label (g.label), stay durations ("45 min", "2 h") and the "20-30" range are English or symbols.
- A Hindi SMS slip of 300 characters is about five SMS parts.
- pulse.js how[2] says सोमवार where the English uses r.week_starts.
