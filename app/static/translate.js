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

  async function fetchHindi(id) {
    if (!navigator.onLine) return null;
    try {
      const r = await fetch('/api/translate', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({claim_id: id})});
      const j = r.ok ? await r.json() : null;
      return j && j.available ? j.hindi : null;
    } catch { return null; }
  }

  // Read aloud through speech.js, label first; with no Hindi voice, speech.js reads the English original instead.
  async function say(hindi, original, note) {
    try { await loadScript('/speech.js', 'RSSpeech'); await RSSpeech.load(); } catch { /* handled below */ }
    if (!root.RSSpeech) { note.textContent = 'Read aloud is not available now.'; return; }
    const r = RSSpeech.speak(LABEL_HI + '\n' + hindi, 'hi', {fallback: LABEL_EN + '\n' + original});
    note.textContent = r.message || '';
  }

  async function show(id, original, wrap) {
    const btn = wrap.querySelector('.tr-btn'), out = wrap.querySelector('.tr-out');
    btn.disabled = true;
    const hindi = await fetchHindi(id);
    if (!hindi) { unavailable(btn); return; }
    btn.remove();  // not .hidden: the button rule in app.css sets display
    out.innerHTML = `<p class="small muted"><span lang="hi">${LABEL_HI}</span> ${LABEL_EN}</p>
      <p lang="hi" class="tr-text">${escHtml(hindi)}</p>
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
      btn.addEventListener('click', () => show(id, original, wrap));
    });
  }

  root.RSTranslate = {bind, LABEL_HI, LABEL_EN};
})(globalThis);
