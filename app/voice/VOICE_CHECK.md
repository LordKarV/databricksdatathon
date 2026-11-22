# Voice support: independent end-to-end check

Run on 2026-11-21 against the voice-support worktree, after building the data in deploy order (export_v1,
facts, packs, howto, stories). The app ran as it does on Databricks: `python app/main.py` with
DATABRICKS_APP_PORT=8765, faster-whisper 1.1.1, the "small" model from the local Hugging Face cache, and
SERVING_ENDPOINT_TEXT / SERVING_ENDPOINT_VISION unset. Machine: Apple M5 Pro, the model limited to 2 CPU threads
as in transcribe.py. The Databricks container (2 vCPU) was not measured; expect it to be slower.

The check scripts are in the session scratchpad (`vcheck/asr_check.py`, `offline_check.py`, `speech_check.py`,
`targets.py`), not in the repo.

| # | Item | Result |
|---|------|--------|
| 1 | /api/transcribe with the feasibility clips, hi and en | pass (16 calls, all 200; nothing written to disk) |
| 2 | Each transcript through /api/parse | pass for matched language: 6 of 6 Hindi and English clips route right, and so does the Hinglish clip G1 |
| 3 | 10 Hindi / Hinglish utterances offline, LLM env vars unset | pass on the server (11 of 11). The browser's offline path failed 6 of 11 before the fix below, and passes 10 of 11 after it |
| 4 | Hindi read aloud on results, itinerary and call ahead | pass (28 screens, 302 slots, 104 numbers, 0 errors) |
| 5 | Privacy: no audio or transcript in logs | pass |
| 6 | Full test suite and a11y check | pass (321 passed, 1 skipped; the skipped real-model test passes with the model installed; a11y 53 states, 0 violations) |

## 1. Speech to text (/api/transcribe)

Each WAV in `app_design/feasibility/voice_language/audio/` was re-encoded with ffmpeg to 48 kHz mono
webm/opus at 32 kbit/s, the format Chrome's MediaRecorder sends. It was then posted as
`data:audio/webm;codecs=opus;base64,...`. The latency below is the HTTP round trip on a warm model. The first
request after start, which loads the model from the local cache, took 2.25 s.

| Clip (spoken) | lang | audio s | latency s | transcript | /api/parse service | expected | |
|---|---|---|---|---|---|---|---|
| E1 (en) | en | 4.6 | 1.62 | My father needs dialysis three times a week, his kidneys have failed. | dialysis | dialysis | pass |
| H1 (hi) | hi | 3.7 | 1.90 | मेरी माखो हवते में 3 भार डालेसिस करवाना परता है | dialysis | dialysis | pass |
| H2 (hi) | hi | 3.7 | 1.87 | गर्भवती है, बचा उलता है, दर शुरो हो गया है | emergency_csection | emergency_csection | pass |
| H6 (hi) | hi | 3.0 | 2.01 | ग्याज सिलिंदर प्टा, चेफ्रा और हाच जल गय. | burn_care | burn_care | pass |
| H7 (hi) | hi | 4.1 | 2.08 | तरक सी तक्कर पैर की हदी तुट गई बहुत खुन्बेह रहा है | trauma_emergency + danger card | trauma_emergency | pass |
| G1 (Hinglish) | hi | 3.9 | 1.92 | मैरी माको हैथ्त मीन 3 भार कुन साफ कार्विना पैक जहें | dialysis | dialysis | pass |
| H1 (hi) | en | 3.7 | 1.58 | My mother has to get dialysis done three times a week. | dialysis | dialysis | pass |
| H2 (hi) | en | 3.7 | 1.94 | Garbhabati hai, bacha ulta hai, dharbh shuro ho gaya hai. | emergency_csection | emergency_csection | pass |
| H6 (hi) | en | 3.0 | 1.65 | gas cylinder fire, the face and hands burned | none | burn_care | miss |
| H7 (hi) | en | 4.1 | 1.62 | The truck has broken the body of the foot. | none | trauma_emergency | miss |
| G1 (Hinglish) | en | 3.9 | 1.72 | Mary Ma co-hacked me in teen barcone soft Carvena pack to head | none | dialysis | miss |
| E1 (en) | hi | 4.6 | 3.44 | वो दोगा नेज़ा दीलिसी तो तो वो वो वो ... (220 characters, "वो" 65 times) | none | dialysis | miss |
| X5 (Bengali) | hi / en | 3.3 | 2.05 / 1.74 | Devanagari / Latin gibberish | none | dialysis | out of scope |
| X6 (Tamil) | hi / en | 4.2 | 2.16 / 1.69 | gibberish / empty | none | nicu | out of scope |

- When the chosen language matches the speech, latency is 1.6 to 2.1 s for 3 to 4.6 s of audio. That is about
  0.35 to 0.67 times real time, including HTTP and the opus decode.
- G1 passed here, though it failed in the feasibility run (CER 0.84). The opus re-encode changed the transcript
  to "कुन साफ", which matches the lexicon's folded "खून साफ". Count this as luck, not a fix.
- When the language does not match the speech, Whisper translates (H1, H2) or garbles the text. All the misses
  above are this case. In production the text model would be tried, but here it was off. E1 forced to Hindi went
  into a repetition loop and took 1.8 s longer.
- Memory: the server process RSS after the 17 calls was 1,327 MB. This is the current RSS, not the peak.
- Rejections: non-audio data URL 415, bad webm 415, 3 MB body 413, lang "fr" 422. All return in under 10 ms.
- Disk: after the calls, `find -newer` over the worktree, /tmp, $TMPDIR and ~/.cache found one new file. It came
  from this session's own tooling (`ecc-metrics-*.json`), not from the server. A Python audit hook in the server,
  loaded through sitecustomize, logged 0 file opens for writing. This hook does not see native writes from
  ctranslate2 or PyAV; the find covers those. test_voice.py's real-model test also passes with the model present
  (16 passed): it checks that one transcribe call writes nothing.

## 2. Transcripts to /api/parse

See the table above. The 6 clips where the chosen language matches the speech all route to the expected service
through the lexicon (source "lexicon"), and so does G1 in Hindi. H7 also raises the danger card ("खुन्बेह" fuzzy
matches "खून बह"). No model call was needed for any of them.

## 3. Offline path, LLM env vars unset

The test used 5 Devanagari sentences and 5 Hinglish ones from `app/tests/test_hindi_lexicon.py`, plus one
danger sentence ("बच्चा सांस नही ले रहा").

- Server, /api/parse with no SERVING_ENDPOINT_*: 11 of 11 right, all with source "lexicon" or "danger".
- Browser, with the network really off (shell from the service worker, Playwright offline, typed into
  #/describe):
  - Before the fix: 6 of 11. The 4 Devanagari sentences with ASR-style spellings matched nothing. The danger
    sentence did not show "Call 108", because input.js matched the lexicon exactly while the server folds the
    spelling first (नही against नहीं).
  - After the fix: 10 of 11, and the danger card shows. The one miss is "गया सिलिंदर पटा ... हात जल गय", which
    needs the server's fuzzy match.
- On all 120 utterances in test_hindi_lexicon.py, the browser's offline matcher, before and after the fix:

| Set | before (exact) | after (folded) |
|---|---|---|
| Devanagari | 26/40, 2 of 6 danger missed | 37/40, 0 missed |
| Hinglish | 36/40 | 40/40 |
| English | 28/40 | 28/40 |
| EVERYDAY (must match nothing) | n/a | 0 of 20 hit |

The fix ports the server's `fold()` (exact spelling folds, no fuzzy match) into `app/static/input.js` for the
danger and lexicon matching. The JS output equals Python's `understand.fold` on all 586 lexicon phrases, danger
words and test utterances. The quoted phrase stays the lexicon's own spelling. The service worker fetches
network-first, so no cache bump is needed.

## 4. Hindi read aloud (Playwright, headless Chromium, speechSynthesis spy)

For each of the 7 service tiles, the check opens the results screen (with the multi-stop itinerary when the plan
has one) and each option's why / call-ahead page (#/why/N#call). It picks हिन्दी, presses Read aloud, and records
every utterance. Results: 28 screens, 3 to 8 lines each. Every utterance was hi-IN and equal to
`state.spoken.hi`, the buildSpeech output.

Checks per screen:
- no "{", "}", "undefined", "null" or "NaN", and no empty line;
- no sentence dropped: an option line, one route line per stop, and an "ask" line when the option has call-ahead
  questions;
- every field buildSpeech reports equals the payload at its path, and its value is in the spoken text;
- every digit left after removing names, quotes and question words is a travel or ETA number from the payload,
  or 108 / 102.

302 slots and 104 spoken numbers were checked, with 0 errors. A mutation run of the checker caught a changed
number, a left-over slot and a field that differs from the payload.

## 5. Privacy

The server ran with the access log off, as main.py sets it. Its full log after 21 transcribe calls (4 of them rejected)
and 37 parse calls was 5 lines: uvicorn startup plus a ctranslate2 "MPS backend" tip. None of the 27 distinct transcripts and test
sentences appears in it, and nothing base64 or webm does either. The only log call in transcribe.py logs the
exception type when the model does not load.

## 6. Tests and accessibility

- `pytest app planner geo common -q -k "not latency"` (Python 3.11, after the input.js fix): 321 passed, 1
  skipped. The skip is the real-model test. With faster-whisper and the cached model, `test_voice.py` gives 16
  passed.
- `app/checks/a11y_check.py`: 53 states, 0 axe violations, no horizontal scroll. Critical path: 4 requests,
  19,729 B gzip (budget 50,000 B, 5 requests).
- Target size (360 px viewport): Speak 328x50, Hindi / English radios 160x48, the phone-speech and read-question
  checkboxes (label) 328x48, हाँ / नहीं 302x50, read-aloud language buttons 160x50, Read aloud 328x50. All are
  44 px or larger.

## Fixed in this check

- `app/static/input.js`: the offline matcher now folds spellings like the server does (see item 3). The unused
  `norm` helper was removed.

## Open issues (not fixed)

1. Choosing the wrong language garbles the result. English speech forced to Hindi loops ("वो" 65 times), and
   Hindi speech forced to English is translated or garbled. The toggle's default comes from the phone's
   language, so a Hindi speaker with an English phone gets English unless they switch. Options: show the
   transcript with a "wrong language? switch" hint, or set `repetition_penalty` / `no_repeat_ngram_size` (not
   tested).
2. The English lexicon misses common ASR English: "burned", "burnt", "broken leg". Without the text model these
   do not route. The lexicon is built by build_lexicon.py from kb/taxonomy.
3. The browser's offline matcher has no fuzzy step, so heavily misspelled Devanagari (H6's ASR text) still needs
   the server.
4. Hindi templates are drafts (#10). Call-ahead questions speak English payload words inside Hindi sentences
   ("क्या आपके यहाँ dialysis unit or machine है?"). Facility names carry their address ("Road No-02, ...
   Muzaffarpur - 842001"), which makes long spoken lines.
5. The dialysis route reads "फिर Rajeshwar Hospital ... 102 से 178 मिनट" and then "फिर Phular ... 50 से 80
   मिनट". The ETAs are each from the start, so the numbers go down. This is faithful to the payload, but it
   sounds wrong when heard in order.
6. Not tested: a real phone, real Hindi TTS voices, Safari or Firefox recording, the Web Speech opt-in mode,
   real speakers (all clips are synthetic macOS voices), and latency and memory on the 2 vCPU Databricks
   container, including the first model download of about 480 MB.
