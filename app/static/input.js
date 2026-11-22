// Free-text input, referral-note photo and read aloud (#64). A classic script that shares app.js globals
// (state, esc, $, svc, pickService, announce, renderBar). Every suggestion ends at a confirm card: one tap to accept,
// one to change. Danger words and the lexicon run in the browser first, so they also work offline.
const RSInput = (() => {
  let lex = null;

  async function load() {
    if (lex) return lex;
    try { lex = await (await fetch('/lexicon.json')).json(); } catch { lex = null; }
    return lex;
  }
  const norm = s => String(s || '').toLowerCase().replace(/\s+/g, ' ').trim();
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  function edgeRe(p) {  // Latin-script phrases on word edges ("chot" not inside "chota"); Devanagari as a substring
    const a = /^[\x00-\x7f]/.test(p) ? '(?<![a-z0-9])' : '';
    const b = /[\x00-\x7f]$/.test(p) ? '(?![a-z0-9])' : '';
    return new RegExp(a + reEsc(p) + b);
  }
  function dangerHit(text) {
    if (!lex) return null;
    const t = norm(text);
    return lex.danger.find(w => edgeRe(w).test(t)) || null;
  }
  // Whole-phrase hits per service, longest phrase first: the same rule as the server (inputs/understand.py).
  function phraseHits(text) {
    if (!lex) return {};
    const t = norm(text), out = {};
    for (const [k, ps] of Object.entries(lex.services)) {
      const hit = [...ps].sort((a, b) => b.length - a.length).find(p => edgeRe(p).test(t));
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

  function setDanger(phrase) {
    if (!phrase) return;
    state.dangerText = phrase;
    renderBar();
    announce('Danger sign in what you wrote. Call 108 now.');
  }

  // ---------- confirm card (screen S2) ----------
  function confirmHtml(r, unsure) {
    const parts = [];
    if (r.danger) {
      parts.push(`<p class="card" role="alert"><strong>Call 108 now.</strong> You wrote "${esc(r.danger_phrase)}".
        ${r.note === 'planned_dropped' ? ' For chest pain now, call 108. Heart operation and MRI are planned services.' : ''}</p>`);
    }
    if (r.service && svc(r.service)) {
      parts.push(`<div class="card">${unsure ? '<p><strong>We are not sure.</strong> Check this, or pick a tile.</p>' : ''}
        <p>Looking for: a hospital that can do <strong>${esc(svc(r.service).en)}</strong></p>
        <p class="small">Because ${r.from_note ? 'the note says' : 'you wrote'}: "${esc(r.phrase)}"</p>
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
  }

  // ---------- "Describe it in your words" ----------
  function describeScreen() {
    return `<a class="btn" href="#/">&larr; Back</a>
      <h1 tabindex="-1">Describe it in your words</h1>
      <p class="small">English, Hindi or Hinglish. You can use your keyboard's microphone.</p>
      <label for="desc">What does the patient need?</label>
      <textarea id="desc" rows="3" maxlength="500" lang="${navigator.language && navigator.language.startsWith('hi') ? 'hi' : 'en'}"
        >${esc(state.descText || '')}</textarea>
      <button type="button" id="desc-go" class="btn btn-primary btn-block">Find the service</button>
      <div id="desc-out" aria-live="polite"></div>
      <p class="small muted">When the words do not name a service, the text is sent once to a Databricks model to read it.
        It is not stored.</p>`;
  }
  async function bindDescribe() {
    await load();
    const go = async () => {
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
      out.innerHTML = confirmHtml(r);
      bindConfirm(out);
      announce(r.service ? `Suggested: ${svc(r.service).en}. Confirm or change.` : 'No service found. Pick a tile.');
    };
    $('#desc-go').addEventListener('click', go);
    $('#desc').addEventListener('input', e => setDanger(dangerHit(e.target.value)));
  }

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
      setDanger(r.danger_phrase);
      const shown = {...r, from_note: true, candidates: [], note: null};
      out.innerHTML = confirmHtml(shown, !r.sure) + (r.detected_text ? `<details><summary>What the model read</summary>
        <p class="small" style="white-space: pre-wrap">${esc(r.detected_text)}</p></details>` : '');
      bindConfirm(out);
      announce(r.service ? `Suggested: ${svc(r.service).en}. Confirm or change.` : 'No service found. Pick a tile.');
    });
  }

  // ---------- read aloud ----------
  const canSpeak = () => 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  function voiceFor(lang) {
    return speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(lang)) || null;
  }
  function speakHtml() {
    return canSpeak() ? `<div class="row"><button type="button" id="speak" aria-pressed="false">
      <span aria-hidden="true">&#128266;</span> Read aloud</button><span id="speak-note" class="small muted"></span></div>` : '';
  }
  // texts: {en, hi}. Hindi only when the phone has a Hindi voice and the text exists in Hindi; else English.
  function bindSpeak(texts) {
    const b = $('#speak');
    if (!b) return;
    b.addEventListener('click', () => {
      if (speechSynthesis.speaking) { speechSynthesis.cancel(); return; }
      const wantHi = (navigator.language || '').startsWith('hi');
      const hiVoice = voiceFor('hi');
      const useHi = wantHi && hiVoice && texts.hi;
      const u = new SpeechSynthesisUtterance(useHi ? texts.hi : texts.en);
      u.lang = useHi ? 'hi-IN' : 'en-IN';
      u.voice = useHi ? hiVoice : (voiceFor('en-in') || voiceFor('en'));
      u.onstart = () => { b.setAttribute('aria-pressed', 'true'); b.lastChild.textContent = ' Stop reading'; };
      u.onend = u.onerror = () => { b.setAttribute('aria-pressed', 'false'); b.lastChild.textContent = ' Read aloud'; };
      $('#speak-note').textContent = wantHi && !useHi ? (hiVoice ? 'Hindi text not ready yet; reading in English.'
        : 'No Hindi voice on this phone; reading in English.') : '';
      speechSynthesis.speak(u);
    });
  }
  window.addEventListener('hashchange', () => { if (canSpeak()) speechSynthesis.cancel(); });

  return {load, searchHits, dangerHit, describeScreen, bindDescribe, noteScreen, bindNote, speakHtml, bindSpeak,
    setDanger};
})();
