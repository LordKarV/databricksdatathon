// 'How this works' card "One record, two answers" (DEMO-TRAP-1, #140). Loaded lazily on #/how, only when /api/how
// has a "trap" key (built by app/howto/trap.py from the raw ai_query re-run and the engine's own plan). Every
// value comes from that key and carries data-f with its path in how.json; only the labels below are written here.
// Engine sentences are shown in Hindi through the reviewed templates (window.rsEngHi), marked data-k="template";
// a sentence with no template stays English, marked lang="en".
'use strict';
(function (root) {
  // New strings, en and hi; the hi text awaits native review (#10).
  const TEXT = {
    title: {en: 'One record, two answers', hi: 'एक रिकॉर्ड, दो जवाब'},
    intro: {en: 'The same facility record, read two ways: {name} (unique_id {id}).',
      hi: 'एक ही अस्पताल रिकॉर्ड, दो तरह से पढ़ा गया: {name} (unique_id {id})।'},
    llm_h: {en: 'A general language model', hi: 'एक सामान्य भाषा मॉडल'},
    llm_run: {en: '{model} on Databricks ({fn}), {file}, run {date}.',
      hi: 'Databricks पर {model} ({fn}), {file}, {date} को चलाया गया।'},
    llm_answer: {en: 'Its answer: {key} {value}, confidence {c}.', hi: 'इसका जवाब: {key} {value}, confidence {c}।'},
    llm_quote: {en: 'The sentence it quoted (field {field}):', hi: 'इसने जो वाक्य उद्धृत किया (फ़ील्ड {field}):'},
    own: {en: "The record's {label} sentence in field {field}:", hi: 'फ़ील्ड {field} में {label} के बारे में रिकॉर्ड का वाक्य:'},
    app_h: {en: 'What Bharosa does', hi: 'भरोसा क्या करता है'},
    band: {en: 'For {label}, the app rates this record {band}, quoting these sentences from it:',
      hi: '{label} के लिए ऐप इस रिकॉर्ड को "{band}" बताता है, और उसके ये वाक्य उद्धृत करता है:'},
    where: {en: 'Its location check (record city {city}):', hi: 'इसकी जगह की जाँच (रिकॉर्ड में शहर {city}):'},
    passed: {en: 'For {label} near {place}, this record is about {n} min away, but the app does not offer it as an option.',
      hi: '{place} के पास {label} के लिए यह रिकॉर्ड लगभग {n} मिनट दूर है, फिर भी ऐप इसे विकल्प के रूप में नहीं दिखाता।'},
    reason: {en: 'The reason the app shows:', hi: 'ऐप जो कारण दिखाता है:'},
    src: {en: 'From {file} and the app\'s plan for this place.', hi: '{file} और इस जगह के लिए ऐप की योजना से।'},
  };
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  const get = (t, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), t);

  // t: how.json "trap"; lang: 'en' or 'hi'; hiFn: engine sentence -> Hindi or null; repo: link base for files.
  function html(t, lang, hiFn, repo) {
    if (!t || !t.saathi) return '';
    const L = lang === 'hi' ? 'hi' : 'en';
    const s = t.saathi;
    const T = (k, v = {}) => esc(TEXT[k][L]).replace(/\{(\w+)\}/g, (m, n) => (n in v ? v[n] : m));
    // One value from the card's data, marked with its how.json path (the How page faithfulness test reads these).
    const F = (path, kind = 'text', lng = 'en') =>
      `<span data-f="trap.${path}" data-k="${kind}"${lng ? ` lang="${lng}"` : ''}>${esc(get(t, path))}</span>`;
    const Q = path => `<q>${F(path)}</q>`;
    const eng = path => {
      const hi = L === 'hi' && hiFn ? hiFn(get(t, path)) : null;
      return hi ? `<span data-f="trap.${path}" data-k="template">${esc(hi)}</span>` : F(path);
    };
    const file = path => `<a href="${esc((repo || '') + get(t, path))}" rel="noopener noreferrer"><code>${F(path)}</code></a>`;
    const label = F(`saathi.label.${L}`, 'text', L);
    const band = `<strong data-f="trap.saathi.band" data-k="band">${root.th ? root.th('band.' + s.band) : esc(s.band)}</strong>`;
    return `<section class="panel trap" lang="${L}" aria-labelledby="trap-h" data-trap="${esc(t.unique_id)}">
      <h2 id="trap-h">${T('title')}</h2>
      <p>${T('intro', {name: F('name'), id: F('unique_id')})}</p>
      <h3>${T('llm_h')}</h3>
      <p>${T('llm_run', {model: F('model_name'), fn: '<span lang="en">ai_query</span>', file: file('query_file'),
        date: F(`ran_on_label.${L}`, 'text', L)})}</p>
      <p>${T('llm_answer', {key: F('verdict.key'), value: F('verdict.value'), c: F('verdict.confidence', 'num')})}</p>
      <p>${T('llm_quote', {field: F('verdict.quote_field')})} ${Q('verdict.quote')}</p>
      <p>${T('own', {label, field: F('own.field')})} ${Q('own.text')}</p>
      <h3>${T('app_h')}</h3>
      <p>${T('band', {label, band})}</p>
      <ul>${s.quotes.map((x, i) => `<li>${F(`saathi.quotes.${i}.field`)}: ${Q(`saathi.quotes.${i}.text`)}</li>`).join('')}</ul>
      <p>${T('where', {city: F('saathi.city')})} ${eng('saathi.where')}</p>
      <p>${T('passed', {label, place: F('saathi.place.name'), n: F('saathi.minutes', 'num')})}</p>
      <p>${T('reason')} ${eng('saathi.reason')}</p>
      <p class="small muted">${T('src', {file: file('source')})}</p>
    </section>`;
  }
  // Placed after the page's first section ("The data problem we found"), before its second heading.
  function show(t, lang) {
    const at = document.querySelectorAll('#main h2')[1];
    if (at && !document.querySelector('.trap')) at.insertAdjacentHTML('beforebegin', html(t, lang, root.rsEngHi, t.repo_url));
  }
  root.RSTrap = {html, show, TEXT};
})(globalThis);
