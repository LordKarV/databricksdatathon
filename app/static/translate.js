// On-demand Hindi machine translation of facility quotes (SAFETY.md 14). Hook: RSTranslate.bind(root).
// Each evidence quote (an element marked data-f="...evidence.N.quote") gets a "हिंदी में पढ़ें" button. The page sends
// only the claim id from the plan; the server looks the quote up, translates it and guards names and numbers. The
// original quote is never changed: the translation is added under it, labelled as a machine translation.
'use strict';
(function (root) {
  const LABEL_HI = 'मशीन अनुवाद। मूल अंग्रेज़ी ऊपर है और वही सबूत है।';
  const LABEL_EN = 'Machine translation. The original English above is the evidence.';
  const NA = '<span lang="hi">अनुवाद अभी उपलब्ध नहीं</span> / Translation not available right now';
  const QUOTE = /^(.+\.evidence\.\d+)\.quote$/;
  const escHtml = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

  function at(obj, path) {
    return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
  }

  function unavailable(btn) {
    btn.innerHTML = NA;
    btn.disabled = true;
  }

  // The server's reply, or null offline or on a network error. A 429 still carries {available: false, message}.
  async function fetchHindi(id) {
    if (!navigator.onLine) return null;
    try {
      const r = await fetch('/api/translate', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({claim_id: id})});
      return r.ok || r.status === 429 ? await r.json() : null;
    } catch { return null; }
  }
  const RETRY = new Set(['timeout', 'rate_limited']);  // not cached on the server: tapping again can work

  // Pieces restored from the quote (names, numbers: "part") or from the fixed term list ("term") are marked with the
  // quote's data-f path, so the faithfulness test can check every number shown against the quote.
  function partsHtml(parts, path) {
    return parts.map(p => p.kind === 'text' ? escHtml(p.text)
      : `<span data-f="${path}" data-k="${p.kind === 'part' ? 'part' : 'term'}">${escHtml(p.text)}</span>`).join('');
  }

  // Read aloud through speech.js, label first; with no Hindi voice, speech.js reads the English original instead.
  async function say(hindi, original, note) {
    try { await loadScript('/speech.js', 'RSSpeech'); await RSSpeech.load(); } catch { /* handled below */ }
    if (!root.RSSpeech) { note.textContent = 'Read aloud is not available now.'; return; }
    const r = RSSpeech.speak(LABEL_HI + '\n' + hindi, 'hi', {fallback: LABEL_EN + '\n' + original});
    note.textContent = r.message || '';
  }

  async function show(id, original, path, wrap) {
    const btn = wrap.querySelector('.tr-btn'), out = wrap.querySelector('.tr-out');
    btn.disabled = true;
    out.textContent = '';
    const j = await fetchHindi(id);
    if (!j || !j.available) {
      if (j && RETRY.has(j.reason)) {
        btn.disabled = false;  // try again
        out.innerHTML = `<p class="small">${escHtml(j.message || 'Translation not available right now.')}</p>`;
      } else {
        unavailable(btn);
        if (j && j.message) out.innerHTML = `<p class="small">${escHtml(j.message)}</p>`;
      }
      return;
    }
    const hindi = j.hindi;
    btn.remove();  // not .hidden: the button rule in app.css sets display
    out.innerHTML = `<p class="small muted"><span lang="hi">${LABEL_HI}</span> ${LABEL_EN}</p>
      <p lang="hi" class="tr-text">${j.parts ? partsHtml(j.parts, path) : escHtml(hindi)}</p>
      <button type="button" class="tr-say"><span lang="hi">सुनें</span> / Read aloud</button>
      <p class="small muted tr-note"></p>`;
    out.querySelector('.tr-say').addEventListener('click', () => say(hindi, original, out.querySelector('.tr-note')));
  }

  function bind(main) {
    const plan = typeof state !== 'undefined' && state.plan;
    if (!plan) return;
    main.querySelectorAll('[data-f$=".quote"]').forEach(q => {
      const m = QUOTE.exec(q.dataset.f);
      const box = m && q.closest('blockquote, li');
      const id = m && at(plan, m[1] + '.claim_id');
      const original = m && at(plan, m[1] + '.quote');
      if (!box || !id || box.querySelector('.tr')) return;
      const wrap = document.createElement('div');
      wrap.className = 'tr';
      wrap.innerHTML = '<button type="button" class="tr-btn"><span lang="hi">हिंदी में पढ़ें</span></button><div class="tr-out" aria-live="polite"></div>';
      box.appendChild(wrap);
      const btn = wrap.querySelector('.tr-btn');
      if (!navigator.onLine) { unavailable(btn); return; }
      btn.addEventListener('click', () => show(id, original, q.dataset.f, wrap));
    });
  }

  root.RSTranslate = {bind, LABEL_HI, LABEL_EN};
})(globalThis);
