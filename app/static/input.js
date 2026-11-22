// Free-text input, voice input, referral-note photo and read aloud (#64, voice support). A classic script that
// shares app.js globals (state, esc, $, svc, pickService, announce, renderBar, save, loadScript). Every
// suggestion ends at a confirm card: one tap to accept, one to change. Danger words and the lexicon run in the
// browser first, so they also work offline. Voice: /voice.js (speech to text) and /speech.js (read aloud), loaded
// when a screen needs them.
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

  // Speaking and listening use the app language (state.lang, one setting for the whole app).
  const pref = k => { try { return JSON.parse(localStorage.getItem('rs.' + k)); } catch { return null; } };
  const voiceLang = () => (state.lang === 'hi' ? 'hi' : 'en');
  const sayOn = () => pref('say') !== false;  // read the voice question aloud; on unless switched off in Settings

  function setDanger(phrase) {
    if (!phrase) return;
    state.dangerText = phrase;
    renderBar();
    announce(ts('input.danger'));
  }

  // ---------- confirm card (screen S2) ----------
  // After speech to text, the question is asked in the app language, with big Yes / No buttons.
  const ASK = s => ts('input.did_you_mean', {svc: s.label});
  function askHtml(r) {
    return `<div class="panel"><p><strong>${esc(ASK(svc(r.service)))}</strong></p>
      <p class="note">${th('input.because_said', {phrase: `<span lang="und">${esc(r.phrase)}</span>`})}</p>
      <button type="button" class="btn btn-ink btn-block" data-confirm="${esc(r.service)}">${th('input.yes')}</button>
      <button type="button" class="btn btn-block" data-voice-no>${th('input.no')}</button></div>`;
  }
  function confirmHtml(r, unsure, heard) {
    const parts = [];
    if (r.danger) {
      parts.push(`<p class="panel danger-note" role="alert"><strong>${th('input.call_108')}</strong> ${r.from_note ? th('input.note_danger')
        : th('input.you_wrote', {phrase: `<span lang="und">${esc(r.danger_phrase)}</span>`})}
        ${r.note === 'planned_dropped' ? ' ' + th('input.planned_dropped') : ''}</p>`);
    }
    if (r.service && svc(r.service) && heard) {
      parts.push(askHtml(r));
    } else if (r.service && svc(r.service)) {
      parts.push(`<div class="panel">${unsure ? `<p><strong>${th('input.unsure')}</strong></p>` : ''}
        <p>${th('input.looking', {svc: `<strong>${esc(svc(r.service).label)}</strong>`})}</p>
        ${r.phrase ? `<p class="note">${th(r.from_note ? 'input.because_note' : 'input.because_wrote', {phrase: `<span lang="und">${esc(r.phrase)}</span>`})}</p>` : ''}
        <button type="button" class="btn btn-ink btn-block" data-confirm="${esc(r.service)}">${th('input.right')}</button>
        <a class="btn btn-block" href="#/">${th('input.change')}</a></div>`);
    } else if (r.candidates && r.candidates.length) {
      parts.push(`<div class="panel"><p>${th('input.which')}</p>${r.candidates.map(c => `<button type="button"
        class="btn btn-block" data-confirm="${esc(c.service)}">${esc(svc(c.service).label)}
        <span class="note">("<span lang="und">${esc(c.phrase)}</span>")</span></button>`).join('')}
        <a class="btn btn-block" href="#/">${th('input.none_of')}</a></div>`);
    } else if (r.note === 'symptoms_only') {
      parts.push(`<p class="panel">${th('input.symptoms')}</p><a class="btn btn-block" href="#/">${th('input.pick')}</a>`);
    } else if (!r.danger) {
      const why = r.source === 'model_unavailable' || r.offline ? ' ' + th('input.no_model') : '';
      parts.push(`<p class="panel">${th('input.no_service')}${why} ${th('input.pick_tile')}</p>
        <a class="btn btn-block" href="#/">${th('input.pick')}</a>`);
    } else {
      parts.push(`<a class="btn btn-block" href="#/">${th('input.pick')}</a>`);
    }
    return parts.join('');
  }
  function bindConfirm(root) {
    root.querySelectorAll('[data-confirm]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.confirm)));
    root.querySelectorAll('[data-voice-no]').forEach(b => b.addEventListener('click', () => {
      root.innerHTML = `<p class="panel">${th('input.again')}</p><a class="btn btn-block" href="#/">${th('input.pick')}</a>`;
      $('#desc').focus();
    }));
  }

  // ---------- "Describe it in your words" ----------
  function describeScreen() {
    return `<a class="back" href="#/">${rsIcon('back')} ${th('nav.back')}</a>
      <h1 tabindex="-1">${th('input.describe_h')}</h1>
      <p class="note">${th('input.describe_help')}</p>
      <div id="voice" class="section"></div>
      <label for="desc" class="section">${th('home.need_h')}</label>
      <textarea id="desc" rows="3" maxlength="500" lang="${voiceLang()}">${esc(state.descText || '')}</textarea>
      <label class="check"><input type="checkbox" id="say-q" ${sayOn() ? 'checked' : ''}> ${th('input.say_q')}</label>
      <button type="button" id="desc-go" class="btn btn-ink btn-block">${th('input.find')}</button>
      <div id="desc-out" aria-live="polite"></div>
      <p class="note section">${th('input.model_note')}</p>`;
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
          out.innerHTML = `<p>${th('input.reading')}</p>`;
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
      announce(ask ? ASK(ask) : r.service ? ts('input.suggested', {svc: svc(r.service).label}) : ts('input.none_found'));
      if (ask && sayOn() && canSpeak()) {
        loadScript('/speech.js', 'RSSpeech').then(() => RSSpeech.load()).then(() => {
          const said = RSSpeech.speak(ASK(ask), voiceLang(), {fallback: `Did you mean ${ask.en}?`});
          if (said.message) announce(said.message);
        }).catch(() => {});
      }
    };
    onHeard = (text, lang) => { $('#desc').value = text; go(lang); };
    $('#desc-go').addEventListener('click', () => go());
    $('#desc').addEventListener('input', e => setDanger(dangerHit(e.target.value)));
    $('#say-q').addEventListener('change', e => save('say', e.target.checked));
    loadScript('/voice.js', 'initVoice').then(() => initVoice($('#voice'), (text, lang) => onHeard(text, lang)),
      () => { $('#voice').innerHTML = `<p class="note">${th('input.keyboard_mic')}</p>`; });
  }
  // The microphone's transcript goes through the same path as typed text, then the spoken Yes / No question.
  let onHeard = () => {};

  // ---------- "Scan referral note" ----------
  function noteScreen() {
    if (!navigator.onLine) {
      return `<a class="back" href="#/">${rsIcon('back')} ${th('nav.back')}</a><h1 tabindex="-1">${th('home.scan')}</h1>
        <p class="panel">${th('input.note_offline')}</p>`;
    }
    return `<a class="back" href="#/">${rsIcon('back')} ${th('nav.back')}</a>
      <h1 tabindex="-1">${th('home.scan')}</h1>
      <div class="panel"><p><strong>${th('input.note_ask')}</strong></p>
        <p class="note">${th('input.note_keep')}</p></div>
      <label class="btn btn-ink btn-block section" for="note-file">${th('input.note_photo')}</label>
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
      out.innerHTML = `<p>${th('input.note_reading')}</p>`;
      let r;
      try {
        const image = await shrink(file);
        input.value = '';
        const res = await fetch('/api/read-note', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({image}), signal: AbortSignal.timeout(20000)});
        r = res.ok ? await res.json() : {ok: false};
      } catch { r = {ok: false}; }
      if (!r.ok) {
        out.innerHTML = `<p class="panel">${th('input.note_failed')}</p><a class="btn btn-block" href="#/">${th('input.pick')}</a>`;
        announce(ts('input.note_failed'));
        return;
      }
      if (r.danger) {  // from a photo: a possible sign to check, never a quote of what the note "says"
        state.dangerText = 'possible danger sign in the note';
        renderBar();
        announce(ts('input.note_danger_say'));
      }
      const shown = {...r, from_note: true, candidates: [], note: null};
      out.innerHTML = confirmHtml(shown, !r.sure) + (r.detected_text ? `<details><summary>${th('input.note_read')}</summary>
        <p class="note" lang="und" style="white-space: pre-wrap">${esc(r.detected_text)}</p></details>` : '');
      bindConfirm(out);
      announce(r.service ? ts('input.suggested', {svc: svc(r.service).label}) : ts('input.none_found'));
    });
  }

  // ---------- read aloud ----------
  // Spoken text is speech.js's fixed templates filled from state.plan only (no model writes it). state.spoken keeps
  // both languages so the faithfulness test can check every spoken value against the payload.
  const canSpeak = () => 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  function speakHtml() {
    if (!canSpeak()) return '';
    return `<button type="button" id="speak" class="btn" aria-pressed="false">${rsIcon('speaker')} <span>${th('ans.listen')}</span></button>`;
  }
  // opts: buildSpeech options from the screen ({danger}, plus {only: i} on the why / call-ahead page).
  // state.spoken keeps both languages so the faithfulness test checks every spoken value; the button speaks the
  // app language.
  async function bindSpeak(opts) {
    const b = $('#speak'), plan = state.plan;
    state.spoken = null;
    if (!b || !plan) return;
    const label = b.querySelector('span');
    const idle = () => { b.setAttribute('aria-pressed', 'false'); label.textContent = ts('ans.listen'); };
    const note = m => { const n = $('#speak-note'); if (n) n.textContent = m; };
    try { await loadScript('/speech.js', 'RSSpeech'); } catch { /* offline and not cached: handled below */ }
    if (!window.RSSpeech || !(await RSSpeech.load())) { b.disabled = true; note(ts('ans.listen_na')); return; }
    if (!b.isConnected) return;  // the screen changed while loading
    state.spoken = {hi: RSSpeech.buildSpeech(plan, 'hi', opts), en: RSSpeech.buildSpeech(plan, 'en', opts)};
    b.addEventListener('click', () => {
      if (b.getAttribute('aria-pressed') === 'true') { RSSpeech.stop(); idle(); return; }
      const lang = voiceLang();
      const r = RSSpeech.speak(state.spoken[lang].text, lang, {fallback: state.spoken.en.text, onend: idle,
        onstart: () => { b.setAttribute('aria-pressed', 'true'); label.textContent = ts('ans.stop'); }});
      note(r.message || '');
    });
  }
  window.addEventListener('hashchange', () => { if (canSpeak()) speechSynthesis.cancel(); });

  return {load, searchHits, dangerHit, describeScreen, bindDescribe, noteScreen, bindNote, speakHtml, bindSpeak,
    setDanger, heard: (text, lang) => onHeard(text, lang)};
})();
