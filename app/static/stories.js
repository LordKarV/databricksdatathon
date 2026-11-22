// 'Data stories' page (issue #53). Loaded lazily on #/stories. Renders /api/stories (built by app/stories/build.py
// from viz/gallery.json): every piece of text carries data-f with its path in stories.json, so the page can be
// checked against the file. Charts are <img> elements; their alt text is the gallery's alt text.
'use strict';
(function (root) {
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function F(path, text) { return `<span data-f="${path}" data-k="text">${esc(text)}</span>`; }

  function story(d, s, i) {
    const p = `stories.${i}`;
    const charts = s.charts.map((c, j) => `<figure class="story-chart">
        <img src="/api/stories/chart/${encodeURIComponent(c.file)}" alt="${esc(c.alt_text)}" loading="lazy"
             data-f="${p}.charts.${j}.alt_text" data-k="alt">
        <figcaption class="small muted">Chart ${j + 1} of ${s.charts.length}.
          <a href="${esc(d.repo_url + c.source)}" rel="noopener noreferrer">${F(`${p}.charts.${j}.source`, c.source)}</a></figcaption>
        <details class="small"><summary>Describe this chart in words</summary><p>${esc(c.alt_text)}</p></details>
      </figure>`).join('');
    const data = s.data_csv.map((c, j) => c.in_repo
      ? `<li><a href="${esc(d.repo_url + c.path)}" rel="noopener noreferrer">${F(`${p}.data_csv.${j}.path`, c.path)}</a></li>`
      : `<li>${F(`${p}.data_csv.${j}.path`, c.path)} <span class="muted">(not in the repository)</span></li>`).join('');
    return `<article class="story" id="story-${esc(s.id)}" aria-labelledby="story-h-${esc(s.id)}">
      <h3 id="story-h-${esc(s.id)}">${F(`${p}.order`, s.order)}. ${F(`${p}.theme`, s.theme)}</h3>
      <p class="story-say">${F(`${p}.presenter_line`, s.presenter_line)}</p>
      ${charts}
      <p><strong>The numbers.</strong> ${F(`${p}.headline`, s.headline)}</p>
      <p><strong>What this does not show.</strong> ${F(`${p}.caveat`, s.caveat)}</p>
      <details class="small"><summary>Data and checks</summary>
        <p>Data behind the chart:</p><ul>${data}</ul>
        <p>How it was checked: ${F(`${p}.verification`, s.verification)}</p>
        ${s.script ? `<p>Made by <a href="${esc(d.repo_url + s.script)}" rel="noopener noreferrer">${F(`${p}.script`, s.script)}</a>.</p>` : ''}
      </details>
    </article>`;
  }

  // Styles for this screen only, injected on first use so they stay off the first-paint CSS (75 KB budget).
  const CSS = `.story { border-top: 1px solid var(--line); padding-top: var(--sp3); margin-top: var(--sp4); }
.story-chart { margin: var(--sp3) 0; }
.story-chart img { display: block; width: 100%; height: auto; background: #fff; border: 1px solid var(--line); border-radius: var(--r2); }
.story-toc { padding-left: 20px; }
.story details a, .story-chart figcaption a { display: inline-block; padding: 6px 0; min-height: 24px; overflow-wrap: anywhere; }`;
  function injectCss() {
    if (typeof document === 'undefined' || document.getElementById('stories-css')) return;
    const st = document.createElement('style');
    st.id = 'stories-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  function render(d) {
    injectCss();
    const toc = d.acts.map((a, k) => `<li><a href="#/stories" data-act="${k}">${F(`acts.${k}`, a)}</a></li>`).join('');
    const body = d.acts.map((a, k) => `<section aria-labelledby="act-${k}"><h2 id="act-${k}" tabindex="-1">${F(`acts.${k}`, a)}</h2>
      ${d.stories.map((s, i) => s.act === a ? story(d, s, i) : '').join('')}</section>`).join('');
    return `<a class="btn" href="#/">&larr; Start</a>
    <h1 tabindex="-1">Data stories</h1>
    <p>What we found in the data, one chart at a time. Every sentence and number on this page is copied from
      <a href="${esc(d.repo_url + d.source)}" rel="noopener noreferrer">${F('source', d.source)}</a>; nothing is retyped.</p>
    <nav aria-label="Stories by part"><ol class="story-toc">${toc}</ol></nav>
    ${body}`;
  }

  function bind(el) {
    el.querySelectorAll('a[data-act]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      const h = el.querySelector('#act-' + a.dataset.act);
      if (h) { h.scrollIntoView(); h.focus(); }
    }));
  }

  root.RSStories = {render, bind};
})(typeof window !== 'undefined' ? window : globalThis);
if (typeof module !== 'undefined') module.exports = globalThis.RSStories;
