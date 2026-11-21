// 'How this works' page (issue #45). Loaded lazily on #/how. Renders /api/how (built by app/howto/build.py):
// every number and table cell carries data-f with its path in how.json, and every source links to its repo file.
'use strict';
(function (root) {
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function F(path, text, kind = 'text') { return `<span data-f="${path}" data-k="${kind}">${esc(text)}</span>`; }

  function render(h) {
    const f = h.facts;
    const n = k => F(`facts.${k}.value`, Number(f[k].value).toLocaleString('en-IN'), 'num');
    const of = k => F(`facts.${k}.of`, Number(f[k].of).toLocaleString('en-IN'), 'num');
    const link = (path, label) => `<a href="${esc(h.repo_url + path)}" rel="noopener noreferrer">${label}</a>`;
    const src = k => `<span class="small muted">(${link(f[k].source, F(`facts.${k}.source`, f[k].source))})</span>`;
    const tsrc = k => `<p class="small muted">From ${link(h.tables[k].source, F(`tables.${k}.source`, h.tables[k].source))},
      section "${F(`tables.${k}.heading`, h.tables[k].heading)}".</p>`;
    const tbl = (k, caption) => {
      const t = h.tables[k];
      // Focusable, labelled region so keyboard users can scroll a wide table (WCAG 2.1.1, axe scrollable-region).
      return `<div class="table-scroll" tabindex="0" role="region" aria-label="${esc(caption)}"><table><caption>${esc(caption)}</caption>
        <thead><tr>${t.columns.map((c, j) => `<th scope="col">${F(`tables.${k}.columns.${j}`, c)}</th>`).join('')}</tr></thead>
        <tbody>${t.rows.map((r, i) => `<tr>${r.map((c, j) => j === 0
          ? `<th scope="row">${F(`tables.${k}.rows.${i}.${j}`, c)}</th>`
          : `<td>${F(`tables.${k}.rows.${i}.${j}`, c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${tsrc(k)}`;
    };
    const more = (summary, body) => `<details><summary>${esc(summary)}</summary>${body}</details>`;
    const labels = h.tables.labels;
    const testRow = labels.rows.findIndex(r => /test/.test(r[0]));
    const fd = h.tables.findings;
    const dnw = h.lists.did_not_work;

    return `<a class="btn" href="#/">&larr; Start</a>
    <h1 tabindex="-1">How this works</h1>
    <p>Referral Saathi reads ${n('records')} facility records ${src('records')}, checks each claim against the
      sentence it came from, and tells you whom to call first and why. Every number on this page links to the file
      it comes from.</p>

    <h2>The data problem we found</h2>
    <p>The records are messy in ways that can send a patient to the wrong place.</p>
    <ul>
      <li>${n('coords_far')} of ${of('coords_far')} map points are more than ${n('far_km')} km from their own PIN code
        ${src('coords_far')}.</li>
      ${fd.rows.slice(0, 3).map((r, i) => `<li><strong>${F(`tables.findings.rows.${i}.0`, r[0])}.</strong>
        ${F(`tables.findings.rows.${i}.1`, r[1])}</li>`).join('')}
    </ul>
    ${tsrc('findings')}
    ${more('All five findings and what goes wrong for a patient', tbl('findings', 'Findings that matter most for a patient'))}

    <h2>What we fixed, flagged and could not fix</h2>
    <p>${n('n_fixed')} problems were fixed, ${n('n_flagged')} are flagged on screen, and ${n('n_cannot')} cannot be
      fixed by cleaning at all. For those, the answer is a phone call before travelling.</p>
    ${more('What we fixed', tbl('fixed', 'Fixed by cleaning'))}
    ${more('What we flag on screen', tbl('flagged', 'Flagged, not repaired'))}
    ${more('What cleaning cannot fix', tbl('cannot', 'Cannot be handled by cleaning'))}

    <h2>How a recommendation is made</h2>
    <ul>
      <li><strong>Evidence.</strong> Each option shows the listing's own sentences word for word, with an id you can
        trace. Sentences that name another facility, or say the service is not offered, are left out and listed as
        ignored.</li>
      <li><strong>Three questions.</strong> Does the facility exist? Is its map point right? Does it offer the
        service? Each answer is a probability with a range, from ${n('evidence_rules')} evidence rules checked by
        hand on ${n('handchecked')} cases ${src('handchecked')}.</li>
      <li><strong>Labels.</strong> "Likely" only when a second source confirmed the service: ${n('app_likely')} of
        ${n('app_pairs')} facility-service pairs the app serves today ${src('app_likely')}. Across all
        ${n('pairs_graded')} graded pairs ${src('pairs_graded')}, ${n('pairs_verified_true')} were confirmed that way
        ${src('pairs_verified_true')}. Everything else is "Not verified: call first".</li>
      <li><strong>Order.</strong> Options are ordered by how sure we are, discounted by travel time. The discount is
        steeper in an emergency (${n('scale_emergency')} minute scale) than for planned care
        (${n('scale_planned')} minutes). We search ${n('radius_km')} km and show up to ${n('n_options')} options
        ${src('radius_km')}. Ranking by expected time to care, including the chance of being turned away, arrives
        with the fitted model.</li>
      <li><strong>Saying no.</strong> When nothing is confirmed, the app says so, lists places to call, and names the
        nearest hospital the public standard says should offer the service.</li>
      <li><strong>Several stops.</strong> ${n('pathways')} care pathways are written down for time-critical cases
        (${F('facts.pathway_names.value', f.pathway_names.value)}) ${src('pathways')}. The multi-stop planner that
        uses them is being built.</li>
    </ul>

    <h2>How good it is</h2>
    <p>Tested on held-back facility-service pairs labelled from public web pages. The test set:
      ${F(`tables.labels.rows.${testRow}.2`, labels.rows[testRow][2])}.</p>
    ${more('The labels', tbl('labels', 'What the labels are'))}
    ${more('Does the score separate confirmed from not confirmed?', `<p>Higher is better; a coin toss scores
      one half.</p>${tbl('auroc', 'Area under the ROC curve on the test pairs')}`)}
    ${more('Is the first option right?', tbl('top1', 'First option over the benchmark queries'))}
    ${more('What did not work', `<ul>${dnw.items.map((x, i) => `<li>${F(`lists.did_not_work.items.${i}`, x)}</li>`).join('')}</ul>
      <p class="small muted">From ${link(dnw.source, F('lists.did_not_work.source', dnw.source))}, section
      "${F('lists.did_not_work.heading', dnw.heading)}".</p>`)}

    <h2>Sources</h2>
    <p>Every record comes from web pages. Some kinds of page are more often right than others.</p>
    ${more('How reliable each kind of source is', tbl('sources', 'Reliability by source class'))}
    ${more('Other public lists we evaluated, and their licences', tbl('datasets', 'External lists and licences'))}

    <h2>Limits</h2>
    <ul>
      <li>Thin rural coverage: ${n('bihar_records')} of ${of('bihar_records')} records are in Bihar
        ${src('bihar_records')}.</li>
      <li>Labels come from public web pages, not from phone calls or visits.</li>
      <li>Opening hours: ${n('hours_records')} of ${of('hours_records')} records say anything about hours, mostly a
        generic round-the-clock claim ${src('hours_records')}. No data says whether a bed or slot is free today.</li>
      <li>Bed counts, staff on duty and today's slots are not in the data: phone first.</li>
    </ul>
    <p class="small muted">Page data built ${F('built_at', h.built_at)}.</p>`;
  }

  root.RSHow = {render};
})(typeof window !== 'undefined' ? window : globalThis);
