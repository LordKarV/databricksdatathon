// Spoken summaries in Hindi and English (voice support). Pure template filling on window.RSSpeech.
// Every slot is filled from the plan payload only, and buildSpeech returns the payload path of every value it
// used, so the faithfulness test can check each spoken number and name against its field. No model writes
// spoken text. Templates live in /speech_templates.json (Hindi drafts until native review, #10).
// Hook: await RSSpeech.load(); const s = RSSpeech.buildSpeech(plan, lang, {danger}); RSSpeech.speak(s.text, lang,
// {fallback: RSSpeech.buildSpeech(plan, 'en', {danger}).text, onstart, onend}) -> {lang, message}; RSSpeech.stop().
'use strict';
(function (root) {
  let T = null;
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function use(templates) { T = templates; return T; }
  async function load() {
    if (T) return T;
    try { return use(await (await fetch('/speech_templates.json')).json()); } catch { return null; }
  }

  // One template with {slot}s. A sentence with an empty slot is dropped: better unsaid than wrong.
  function fill(tpl, vals) {
    let empty = false;
    const out = tpl.replace(/\{(\w+)\}/g, (_, k) => {
      const v = vals[k];
      if (v === null || v === undefined || String(v).trim() === '') empty = true;
      return String(v ?? '');
    });
    return empty ? null : out;
  }

  // Hindi call-ahead question: match the engine's fixed English template, speak the Hindi one. {label} is the
  // service label from the payload, {need} the payload's own words. Unknown question: spoken verbatim.
  function questionHi(q, L, plan, path, fields) {
    for (const [en, hi] of L.questions) {
      const re = new RegExp('^' + reEsc(en).replace('\\{label\\}', reEsc(plan.query.service_label.en))
        .replace('\\{need\\}', '(.+)') + '$');
      const m = q.match(re);
      if (!m) continue;
      // A {need} from the engine's fixed list is spoken with its glossary term (#121 bug 8): the question is then a
      // fixed template too. An unknown {need} keeps the payload's own words.
      const need = m[1], needHi = need !== undefined ? (L.needs || {})[need] : undefined;
      if (hi.includes('{label}')) fields.push({path: 'query.service_label.hi', value: plan.query.service_label.hi, kind: 'text'});
      if (need !== undefined && needHi === undefined) fields.push({path, value: need, kind: 'part'});
      else fields.push({path, value: q, kind: 'template'});
      return fill(hi, {label: plan.query.service_label.hi, need: needHi ?? need});
    }
    fields.push({path, value: q, kind: 'text'});
    return q;
  }

  // plan: the /api/plan payload. lang: 'hi' | 'en'. opts.danger: the user ticked a danger sign (UI state).
  // opts.only: an option index (why / call-ahead page): that option, its reason and its questions; no backup or route.
  // Returns {text, fields}: text is one sentence per line; fields lists {path, value, kind} for every slot.
  function buildSpeech(plan, lang, opts = {}) {
    const L = (T || {})[lang] || (T || {}).en;
    if (!L) return {text: '', fields: []};
    const fields = [], lines = [];
    const add = (key, vals, used) => {
      const s = fill(L[key], vals);
      if (s) { lines.push(s); fields.push(...used); }
    };
    const list = plan.options || [];

    if (opts.danger || plan.profile === 'emergency' || plan.profile === 'urgent') {
      (plan.emergency_numbers || []).forEach((n, i) => {
        const key = n.number === '108' ? 'call_108' : n.number === '102' ? 'call_102' : null;
        if (key) add(key, {number: n.number}, [{path: `emergency_numbers.${i}.number`, value: n.number, kind: 'num'}]);
      });
    }
    if (plan.abstain) {
      const key = list.length ? 'abstain_some' : 'abstain_none';
      add(key, {text: plan.abstain.text}, L[key].includes('{text}') ? [{path: 'abstain.text', value: plan.abstain.text, kind: 'text'}] : []);
    }
    const optionLine = (key, o, P) => add(key, {name: o.name, low: o.travel.low, high: o.travel.high, band: L.band[o.band]}, [
      {path: P + '.name', value: o.name, kind: 'text'}, {path: P + '.travel.low', value: o.travel.low, kind: 'num'},
      {path: P + '.travel.high', value: o.travel.high, kind: 'num'}, {path: P + '.band', value: o.band, kind: 'enum'}]);
    const one = Number.isInteger(opts.only);
    const i = one ? opts.only : 0, A = `options.${i}`;
    const a = list[i], b = one ? null : list[1];
    if (a) {
      optionLine(one ? 'this' : 'first', a, A);
      // ponytail: the top reason is the first evidence quote verbatim (the card shows it); never paraphrased.
      if (a.evidence && a.evidence.length) {
        add('reason', {quote: a.evidence[0].quote}, [{path: A + '.evidence.0.quote', value: a.evidence[0].quote, kind: 'text'}]);
      }
    }
    const askLine = () => {
      if (!a || !a.call_ahead || !a.call_ahead.length) return;
      const qf = [];
      const qs = a.call_ahead.map((c, j) => {
        const path = `${A}.call_ahead.${j}.question`;
        if (lang === 'hi' && L.questions.length) return questionHi(c.question, L, plan, path, qf);
        qf.push({path, value: c.question, kind: 'text'});
        return c.question;
      });
      add('ask', {questions: qs.join(' ')}, qf);
    };
    if (!one) askLine();  // answer screen: "Ask" is read with option 1, by its Call button (#140 3d)
    if (b) optionLine('backup', b, 'options.1');

    const route = !one && plan.itinerary && plan.itinerary.plans && plan.itinerary.plans[0];
    if (route && route.stops.length > 1) {
      route.stops.forEach((s, k) => {
        const S = `itinerary.plans.0.stops.${k}`;
        const purposeHi = L.purpose[s.purpose];
        add(k ? 'route_next' : 'route_first', {name: s.name, purpose: purposeHi || s.purpose_word, low: s.eta_low, high: s.eta_high}, [
          {path: S + '.name', value: s.name, kind: 'text'},
          purposeHi ? {path: S + '.purpose', value: s.purpose, kind: 'enum'} : {path: S + '.purpose_word', value: s.purpose_word, kind: 'text'},
          {path: S + '.eta_low', value: s.eta_low, kind: 'num'}, {path: S + '.eta_high', value: s.eta_high, kind: 'num'}]);
      });
    }

    if (one) askLine();
    return {text: lines.join('\n'), fields};
  }

  // ---------- speaking (browser only) ----------
  const canSpeak = () => 'speechSynthesis' in root && 'SpeechSynthesisUtterance' in root;
  function voiceFor(prefix) {
    return root.speechSynthesis.getVoices().find(v => (v.lang || '').toLowerCase().replace('_', '-').startsWith(prefix)) || null;
  }
  function stop() { if (canSpeak()) root.speechSynthesis.cancel(); }

  // Speaks text (one utterance per line: Chrome cuts long utterances off). lang 'hi' with no Hindi voice on the
  // phone speaks opts.fallback (the English summary) instead and says so. Returns {lang, message}; the caller
  // shows message in an aria-live region. opts.onstart / opts.onend drive the Read aloud / Stop button.
  function speak(text, lang, opts = {}) {
    const L = (T && T[lang]) || (T && T.en) || {};
    if (!canSpeak()) return {lang: null, message: L.cannot_speak || 'This phone cannot read aloud.'};
    stop();
    const voices = root.speechSynthesis.getVoices();
    let voice = lang === 'hi' ? voiceFor('hi') : (voiceFor('en-in') || voiceFor('en'));
    let message = '';
    // An empty voice list means "not loaded yet", not "no Hindi": then the engine picks by u.lang.
    if (lang === 'hi' && !voice && voices.length) {
      message = L.no_hindi_voice || 'No Hindi voice on this phone. Reading in English.';
      lang = 'en';
      text = opts.fallback || text;
      voice = voiceFor('en-in') || voiceFor('en');
    }
    const lines = String(text || '').split('\n').filter(s => s.trim());
    lines.forEach((line, i) => {
      const u = new root.SpeechSynthesisUtterance(line);
      u.lang = lang && lang !== 'en' ? lang + '-IN' : 'en-IN';  // hi-IN, ta-IN, ... (all ten are -IN)
      if (voice) u.voice = voice;
      u.rate = 0.95;
      if (i === 0 && opts.onstart) u.onstart = opts.onstart;
      if (i === lines.length - 1 && opts.onend) u.onend = opts.onend;
      if (opts.onend) u.onerror = opts.onend;
      root.speechSynthesis.speak(u);
    });
    return {lang, message};
  }

  root.RSSpeech = {load, use, buildSpeech, speak, stop, canSpeak};
})(globalThis);
