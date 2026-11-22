// Free-text input, voice input, referral-note photo and read aloud (#64, voice support). A classic script that
// shares app.js globals (state, esc, $, svc, pickService, announce, renderBar, save, loadScript). Every
// suggestion ends at a confirm card: one tap to accept, one to change. Danger words and the lexicon run in the
// browser first, so they also work offline. Voice: /voice.js (speech to text) and /speech.js (read aloud), loaded
// when a screen needs them.

// Read-aloud language label (#121 bug 8): the toggle changes the spoken language only, so the label says so. One map
// per language, so it moves into the strings files of the coming app-wide language setting; the screen shows 'en'
// until then. The Hindi is a draft for native review (#10).
const SAY_STRINGS = {
  en: {label: 'Read aloud in (speech only, the screen stays in English):'},
  hi: {label: 'किस भाषा में पढ़कर सुनाएँ (सिर्फ़ आवाज़, स्क्रीन अंग्रेज़ी में ही रहेगी):'},
};
const RSInput = (() => {
  let lex = null;

  async function load() {
    if (lex) return lex;
    try { lex = await (await fetch('/lexicon.json')).json(); } catch { lex = null; }
    return lex;
  }
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // fold() from inputs/understand.py (exact folds only, no fuzzy): ASR and typing swaps such as खुन / खून and
  // नही / नहीं match offline too. Keep the two in step.
  const DEVA = {'\u093c': '', '\u0901': '', '\u0902': '', '\u094d': '', 'ी': 'ि', 'ू': 'ु', 'ै': 'े', 'ौ': 'ो',
    'ॉ': 'ो', 'ॅ': 'े', 'ई': 'इ', 'ऊ': 'उ', 'ऐ': 'ए', 'औ': 'ओ', 'ऑ': 'ओ', 'ख': 'क', 'घ': 'ग', 'छ': 'च', 'झ': 'ज',
    'थ': 'त', 'ध': 'द', 'फ': 'प', 'भ': 'ब', 'ट': 'त', 'ठ': 'त', 'ड': 'द', 'ढ': 'द', 'ण': 'न', 'श': 'स', 'ष': 'स'};
  const LATIN = [['chch', 'ch'], ['cch', 'ch'], ['ee', 'i'], ['oo', 'u'], ['ph', 'f'], ['w', 'v'], ['z', 'j'], ['q', 'k']];
  function fold(s) {
    let t = [...String(s || '').toLowerCase().normalize('NFD')].map(c => DEVA[c] ?? c).join('');
    for (const [a, b] of LATIN) t = t.split(a).join(b);
    t = t.replace(/[\u0964\u0965]|[^\p{L}\p{N}\p{M}_\s'\u0900-\u097f]/gu, ' ').replace(/([^\s\d])\1+/gu, '$1');
    return t.replace(/\s+/g, ' ').trim();
  }
  function edgeRe(p) {  // Latin-script phrases on word edges ("chot" not inside "chota"); Devanagari as a substring
    const a = /^[\x00-\x7f]/.test(p) ? '(?<![a-z0-9])' : '';
    const b = /[\x00-\x7f]$/.test(p) ? '(?![a-z0-9])' : '';
    return new RegExp(a + reEsc(p) + b);
  }
  function dangerHit(text) {
    if (!lex) return null;
    const t = fold(text);
    return lex.danger.find(w => edgeRe(fold(w)).test(t)) || null;
  }
  // Whole-phrase hits per service, longest phrase first: the same rule as the server (inputs/understand.py).
  function phraseHits(text) {
    if (!lex) return {};
    const t = fold(text), out = {};
    for (const [k, ps] of Object.entries(lex.services)) {
      const hit = [...ps].sort((a, b) => b.length - a.length).find(p => fold(p) && edgeRe(fold(p)).test(t));
      if (hit) out[k] = hit;
    }
    return out;
  }
  // Search box: also matches while typing ("dial" finds dialysis).
  function searchHits(v) {
    if (!lex || v.length < 2) return [];
    return Object.keys(lex.services).filter(k => lex.services[k].some(w => w.includes(v) || v.includes(w)));
  }
  function localParse(text) {
    const danger = dangerHit(text);
    const all = phraseHits(text);
    const planned = new Set(lex ? lex.planned : []);
    const hits = Object.entries(all).filter(([k]) => !(danger && planned.has(k)));
    const r = {text, danger: !!danger, danger_phrase: danger, service: null, phrase: null, candidates: [],
      source: null, note: danger && Object.keys(all).some(k => planned.has(k)) ? 'planned_dropped' : null};
    if (hits.length === 1) return {...r, service: hits[0][0], phrase: hits[0][1], source: 'lexicon'};
    if (hits.length > 1) return {...r, candidates: hits.map(([service, phrase]) => ({service, phrase})), source: 'lexicon'};
    return danger ? {...r, source: 'danger'} : r;
  }

  // Hindi or English for speaking and listening: one choice, the same localStorage entry as voice.js ('rs.voice').
  const pref = k => { try { return JSON.parse(localStorage.getItem('rs.' + k)); } catch { return null; } };
  function voiceLang() {
    const l = (pref('voice') || {}).lang;
    return l === 'hi' || l === 'en' ? l : (navigator.language || '').toLowerCase().startsWith('hi') ? 'hi' : 'en';
  }
  const setVoiceLang = lang => save('voice', {...(pref('voice') || {}), lang});  // save() from app.js: try/catch
  const sayOn = () => pref('say') !== false;  // read the voice question aloud; on unless switched off

  function setDanger(phrase) {
    if (!phrase) return;
    state.dangerText = phrase;
    renderBar();
    announce('Danger sign in what you wrote. Call 108 now.');
  }

  // ---------- confirm card (screen S2) ----------
  // After speech to text, the question is asked in the language the user spoke, with big Yes / No buttons.
  const ASK = {hi: s => `\u0915\u094d\u092f\u093e \u0906\u092a\u0915\u093e \u092e\u0924\u0932\u092c ${s.hi} \u0939\u0948?`, en: s => `Did you mean ${s.en}?`};
  function askHtml(r, lang) {
    const s = svc(r.service), hi = lang === 'hi';
    return `<div class="card"><p lang="${lang}"><strong>${esc(ASK[lang](s))}</strong></p>
      <p class="small">Because you said: "${esc(r.phrase)}"</p>
      <button type="button" class="btn btn-primary btn-block" data-confirm="${esc(r.service)}"
        lang="${lang}">${hi ? '\u0939\u093e\u0901' : 'Yes'}</button>
      <button type="button" class="btn btn-block" data-voice-no lang="${lang}">${hi ? '\u0928\u0939\u0940\u0902' : 'No'}</button></div>`;
  }
  function confirmHtml(r, unsure, heard) {
    const parts = [];
    if (r.danger) {
      parts.push(`<p class="card" role="alert"><strong>Call 108 now.</strong> ${r.from_note ? 'Possible danger sign in the note: please check.' : `You wrote "${esc(r.danger_phrase)}".`}
        ${r.note === 'planned_dropped' ? ' For chest pain now, call 108. Heart operation and MRI are planned services.' : ''}</p>`);
    }
    if (r.service && svc(r.service) && heard) {
      parts.push(askHtml(r, heard));
    } else if (r.service && svc(r.service)) {
      parts.push(`<div class="card">${unsure ? '<p><strong>We are not sure.</strong> Check this, or pick a tile.</p>' : ''}
        <p>Looking for: a hospital that can do <strong>${esc(svc(r.service).en)}</strong></p>
        ${r.phrase ? `<p class="small">Because ${r.from_note ? 'the note says' : 'you wrote'}: "${esc(r.phrase)}"</p>` : ''}
        <button type="button" class="btn btn-primary btn-block" data-confirm="${esc(r.service)}">Yes, that is right</button>
        <a class="btn btn-block" href="#/">Change service</a></div>`);
    } else if (r.candidates && r.candidates.length) {
      parts.push(`<div class="card"><p>Which one is it?</p>${r.candidates.map(c => `<button type="button"
        class="btn btn-block" data-confirm="${esc(c.service)}">${esc(svc(c.service).en)}
        <span class="small">("${esc(c.phrase)}")</span></button>`).join('')}
        <a class="btn btn-block" href="#/">None of these</a></div>`);
    } else if (r.note === 'symptoms_only') {
      parts.push(`<p class="card">This sounds like symptoms. Ask the PHC doctor which service is needed, or call 108.</p>
        <a class="btn btn-block" href="#/">Pick a service</a>`);
    } else if (!r.danger) {
      const why = r.source === 'model_unavailable' || r.offline ? ' Reading free text needs the internet and the model, which are not available now.' : '';
      parts.push(`<p class="card">We could not tell the service from these words.${why} Pick a tile.</p>
        <a class="btn btn-block" href="#/">Pick a service</a>`);
    } else {
      parts.push('<a class="btn btn-block" href="#/">Pick a service</a>');
    }
    return parts.join('');
  }
  function bindConfirm(root) {
    root.querySelectorAll('[data-confirm]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.confirm)));
    root.querySelectorAll('[data-voice-no]').forEach(b => b.addEventListener('click', () => {
      root.innerHTML = `<p class="card"><span lang="hi">\u092b\u093f\u0930 \u0938\u0947 \u092c\u094b\u0932\u0947\u0902 \u092f\u093e \u0932\u093f\u0916\u0947\u0902\u0964</span> Say it again, or type it.</p>
        <a class="btn btn-block" href="#/">Pick a service</a>`;
      $('#desc').focus();
    }));
  }

  // ---------- "Describe it in your words" ----------
  function describeScreen() {
    return `<a class="btn" href="#/">&larr; Back</a>
      <h1 tabindex="-1">Describe it in your words</h1>
      <p class="small">English, Hindi or Hinglish. Tap Speak, or use your keyboard's microphone.</p>
      <label for="desc">What does the patient need?</label>
      <textarea id="desc" rows="3" maxlength="500" lang="${navigator.language && navigator.language.startsWith('hi') ? 'hi' : 'en'}"
        >${esc(state.descText || '')}</textarea>
      <div id="voice"></div>
      <label class="check small"><input type="checkbox" id="say-q" ${sayOn() ? 'checked' : ''}>
        Read the question aloud after I speak</label>
      <button type="button" id="desc-go" class="btn btn-primary btn-block">Find the service</button>
      <div id="desc-out" aria-live="polite"></div>
      <p class="small muted">When the words do not name a service, the text is sent once to a Databricks model to read it.
        It is not stored.</p>`;
  }
  async function bindDescribe() {
    await load();
    const go = async heard => {  // heard: 'hi' | 'en' when the text came from the microphone
      const text = $('#desc').value.trim();
      state.descText = text;
      if (!text) { $('#desc').focus(); return; }
      const out = $('#desc-out');
      let r = localParse(text);
      if (!r.service && !r.candidates.length && !r.danger) {
        if (!navigator.onLine) r = {...r, offline: true};
        else {
          out.innerHTML = '<p>Reading...</p>';
          try {
            const res = await fetch('/api/parse', {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({text}), signal: AbortSignal.timeout(10000)});
            r = res.ok ? await res.json() : {...r, source: 'model_unavailable'};
          } catch { r = {...r, source: 'model_unavailable'}; }
        }
      }
      setDanger(r.danger_phrase);
      const ask = heard && r.service && svc(r.service);
      out.innerHTML = confirmHtml(r, false, ask ? heard : null);
      bindConfirm(out);
      announce(ask ? ASK[heard](ask) : r.service ? `Suggested: ${svc(r.service).en}. Confirm or change.`
        : 'No service found. Pick a tile.');
      if (ask && sayOn() && canSpeak()) {
        loadScript('/speech.js', 'RSSpeech').then(() => RSSpeech.load()).then(() => {
          const said = RSSpeech.speak(ASK[heard](ask), heard, {fallback: ASK.en(ask)});
          if (said.message) announce(said.message);
        }).catch(() => {});
      }
    };
    onHeard = (text, lang) => { $('#desc').value = text; go(lang); };
    $('#desc-go').addEventListener('click', () => go());
    $('#desc').addEventListener('input', e => setDanger(dangerHit(e.target.value)));
    $('#say-q').addEventListener('change', e => save('say', e.target.checked));
    loadScript('/voice.js', 'initVoice').then(() => initVoice($('#voice'), (text, lang) => onHeard(text, lang)),
      () => { $('#voice').innerHTML = `<p class="small">Use your keyboard's mic to speak.</p>`; });
  }
  // The microphone's transcript goes through the same path as typed text, then the spoken Yes / No question.
  let onHeard = () => {};

  // ---------- "Scan referral note" ----------
  function noteScreen() {
    if (!navigator.onLine) {
      return `<a class="btn" href="#/">&larr; Back</a><h1 tabindex="-1">Scan referral note</h1>
        <p class="card">Reading a note needs the internet. Use the search box or a tile.</p>`;
    }
    return `<a class="btn" href="#/">&larr; Back</a>
      <h1 tabindex="-1">Scan referral note</h1>
      <div class="card"><p><strong>Ask the patient first. Cover the name before taking the photo.</strong></p>
        <p class="small">We do not keep the photo. It is sent once to a Databricks model to read it.</p></div>
      <label class="btn btn-primary btn-block" for="note-file">Take a photo of the note</label>
      <input id="note-file" class="visually-hidden" type="file" accept="image/*" capture="environment">
      <div id="note-out" aria-live="polite"></div>`;
  }
  // Re-encode through a canvas (about 1024 px on the long side, JPEG): smaller upload, and EXIF is dropped.
  async function shrink(file) {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, 1024 / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas');
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    return c.toDataURL('image/jpeg', 0.85);
  }
  function bindNote() {
    const input = $('#note-file');
    if (!input) return;
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      const out = $('#note-out');
      if (!file) return;
      out.innerHTML = '<p>Reading the note...</p>';
      let r;
      try {
        const image = await shrink(file);
        input.value = '';
        const res = await fetch('/api/read-note', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({image}), signal: AbortSignal.timeout(20000)});
        r = res.ok ? await res.json() : {ok: false};
      } catch { r = {ok: false}; }
      if (!r.ok) {
        out.innerHTML = '<p class="card">Could not read the note now. Pick a service.</p><a class="btn btn-block" href="#/">Pick a service</a>';
        announce('Could not read the note.');
        return;
      }
      if (r.danger) {  // from a photo: a possible sign to check, never a quote of what the note "says"
        state.dangerText = 'possible danger sign in the note';
        renderBar();
        announce('Possible danger sign in the note. Please check. Call 108 now.');
      }
      const shown = {...r, from_note: true, candidates: [], note: null};
      out.innerHTML = confirmHtml(shown, !r.sure) + (r.detected_text ? `<details><summary>What we read from the photo</summary>
        <p class="small" style="white-space: pre-wrap">${esc(r.detected_text)}</p></details>` : '');
      bindConfirm(out);
      announce(r.service ? `Suggested: ${svc(r.service).en}. Confirm or change.` : 'No service found. Pick a tile.');
    });
  }

  // ---------- read aloud ----------
  // Spoken text is speech.js's fixed templates filled from state.plan only (no model writes it). state.spoken keeps
  // both languages so the faithfulness test can check every spoken value against the payload.
  const canSpeak = () => 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  function speakHtml() {
    if (!canSpeak()) return '';
    const l = voiceLang(), t = (v, label) => `<button type="button" data-say-lang="${v}" aria-pressed="${l === v}"
      class="${l === v ? 'btn-primary' : ''}">${label}</button>`;
    return `<p id="say-lang-h" class="small say-lang-label">${esc(SAY_STRINGS.en.label)}</p>
      <div class="row" role="group" aria-labelledby="say-lang-h">${t('hi', '<span lang="hi">\u0939\u093f\u0928\u094d\u0926\u0940</span>&nbsp;Hindi')}
      ${t('en', 'English')}</div>
      <button type="button" id="speak" class="btn-block" aria-pressed="false"><span aria-hidden="true">&#128266;</span
      > Read aloud</button><p id="speak-note" class="small muted" aria-live="polite"></p>`;
  }
  // opts: buildSpeech options from the screen ({danger}, plus {only: i} on the why / call-ahead page).
  async function bindSpeak(opts) {
    const b = $('#speak'), plan = state.plan;
    state.spoken = null;
    if (!b || !plan) return;
    const idle = () => { b.setAttribute('aria-pressed', 'false'); b.lastChild.textContent = ' Read aloud'; };
    document.querySelectorAll('[data-say-lang]').forEach(t => t.addEventListener('click', () => {
      setVoiceLang(t.dataset.sayLang);
      document.querySelectorAll('[data-say-lang]').forEach(x => {  // filled = chosen, not only aria-pressed
        x.setAttribute('aria-pressed', String(x === t));
        x.classList.toggle('btn-primary', x === t);
      });
      if (window.RSSpeech) RSSpeech.stop();
      idle();
    }));
    try { await loadScript('/speech.js', 'RSSpeech'); } catch { /* offline and not cached: handled below */ }
    if (!window.RSSpeech || !(await RSSpeech.load())) { b.disabled = true; $('#speak-note').textContent = 'Read aloud is not available now.'; return; }
    if (!b.isConnected) return;  // the screen changed while loading
    state.spoken = {hi: RSSpeech.buildSpeech(plan, 'hi', opts), en: RSSpeech.buildSpeech(plan, 'en', opts)};
    b.addEventListener('click', () => {
      if (b.getAttribute('aria-pressed') === 'true') { RSSpeech.stop(); idle(); return; }
      const lang = voiceLang();
      const r = RSSpeech.speak(state.spoken[lang].text, lang, {fallback: state.spoken.en.text, onend: idle,
        onstart: () => { b.setAttribute('aria-pressed', 'true'); b.lastChild.textContent = ' Stop reading'; }});
      $('#speak-note').textContent = r.message || '';
    });
  }
  window.addEventListener('hashchange', () => { if (canSpeak()) speechSynthesis.cancel(); });

  return {load, searchHits, dangerHit, describeScreen, bindDescribe, noteScreen, bindNote, speakHtml, bindSpeak,
    setDanger, heard: (text, lang) => onHeard(text, lang)};
})();
