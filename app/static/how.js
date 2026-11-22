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
    const d = (k, digits) => F(`facts.${k}.value`, Number(f[k].value).toFixed(digits), 'num');
    const t = k => F(`facts.${k}.value`, f[k].value);
    const of = k => F(`facts.${k}.of`, Number(f[k].of).toLocaleString('en-IN'), 'num');
    const link = (path, label) => `<a href="${esc(h.repo_url + path)}" rel="noopener noreferrer">${label}</a>`;
    const src = k => `<span class="small muted">(${link(f[k].source, F(`facts.${k}.source`, f[k].source))})</span>`;
    const tsrc = k => `<p class="small muted">From ${link(h.tables[k].source, F(`tables.${k}.source`, h.tables[k].source))},
      section "${F(`tables.${k}.heading`, h.tables[k].heading)}".</p>`;
    const tbl = (k, caption) => {
      const tb = h.tables[k];
      // Focusable, labelled region so keyboard users can scroll a wide table (WCAG 2.1.1, axe scrollable-region).
      return `<div class="table-scroll" tabindex="0" role="region" aria-label="${esc(caption)}"><table><caption>${esc(caption)}</caption>
        <thead><tr>${tb.columns.map((c, j) => `<th scope="col">${F(`tables.${k}.columns.${j}`, c)}</th>`).join('')}</tr></thead>
        <tbody>${tb.rows.map((r, i) => `<tr>${r.map((c, j) => j === 0
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
    <p class="small">Scores: ${F('facts.scores_source.value', h.facts.scores_source.value)} ${src('scores_source')}.</p>

    <h2>The data problem we found</h2>
    <p>The records are messy in ways that can send a patient to the wrong place.</p>
    <ul>
      <li><strong>Text about another facility.</strong> ${n('other_facility')} of ${of('other_facility')} records
        have a sentence that names another facility ${src('other_facility')}. In ${n('other_facility_direct')} of
        them, that sentence is written as if it were about the record itself. The app never uses such a sentence as
        evidence.</li>
      <li><strong>Map points in the wrong town.</strong> ${n('coords_far')} of ${of('coords_far')} map points are
        more than ${n('far_km')} km from their own PIN code, and ${n('coords_far2')} are more than ${n('far2_km')} km
        away ${src('coords_far')}. ${n('coords_same_state')} of the ${of('coords_same_state')} still fall in the same
        state ${src('coords_same_state')}.</li>
      <li><strong>${F('tables.findings.rows.2.0', fd.rows[2][0])}.</strong> ${F('tables.findings.rows.2.1', fd.rows[2][1])}</li>
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
        ignored. The sentences are graded with ${n('evidence_rules')} evidence rules, checked by hand on
        ${n('handchecked')} cases ${src('handchecked')}.</li>
      <li><strong>Three questions.</strong> Does the facility exist? Is its map point right? Does it offer the
        service? Each answer is a chance. The service chance comes from the model described below. The range shown
        next to it is how often checked pairs with a similar score were confirmed.</li>
      <li><strong>Labels.</strong> "Likely" means the model's chance is at least ${d('likely_p', 2)}, the location check
        is at least ${d('likely_p_location', 1)}, the existence check is at least ${d('likely_p_exists', 1)}, and the
        listing has a sentence about the service as its own unit ${src('likely_p')}. Of the ${n('app_pairs')} facility-service pairs the app serves ${src('app_pairs')}: ${n('app_likely')} Likely,
        ${n('app_not_verified')} "Not verified: call to confirm", ${n('app_no_service_text')} "No service text: call
        to ask" (the listing has no sentence about the service), and ${n('app_unlikely')} Unlikely
        ${src('app_likely')}.</li>
      <li><strong>Order.</strong> Options are ordered by the model's chance, discounted by travel time. The discount
        is steeper in an emergency (${n('scale_emergency')} minute scale) than for planned care
        (${n('scale_planned')} minutes). A listing with no sentence about the service counts as at most
        ${d('likely_p', 2)}, so a hospital cannot come first on its size or level alone. We search ${n('radius_km')} km and
        show up to ${n('n_options')} options ${src('radius_km')}. The order does not yet count the time lost if the
        first place turns the patient away.</li>
      <li><strong>Saying no.</strong> When nothing is Likely, the app says so, lists places to call, and names the
        nearest hospital the public standard says should offer the service.</li>
      <li><strong>Several stops.</strong> ${n('pathways')} care pathways are written down for time-critical cases
        (${F('facts.pathway_names.value', f.pathway_names.value)}) ${src('pathways')}. For these the app adds a
        suggested route. The route planner still uses placeholder chances built from the listings, not the model,
        and the route says so.</li>
    </ul>

    <h2>How good it is</h2>
    <p>The app uses ${t('v2_model')}: an expert-set scorecard with one calibration step ${src('v2_model')}.
      These results are on DEV pairs, grouped five-fold, out of fold. The labels were made by an agent from public
      web pages, not checked by a person. The sealed test set has not been opened yet.</p>
    <p>What the chance means: ${t('v2_meaning')}</p>
    ${tbl('v2_eval', 'The model against simpler choices, on DEV pairs')}
    <ul>
      <li><strong>Likely.</strong> ${n('likely_dev')} of ${of('likely_dev')} DEV pairs labelled Likely were
        confirmed (${d('likely_dev_lo', 3)} to ${d('likely_dev_hi', 3)}).</li>
      <li><strong>First options.</strong> A confirmed place was among the first ${n('conf_em_k')} options in
        ${n('conf_em')} of ${of('conf_em')} emergency groups and among the first ${n('conf_pl_k')} in ${n('conf_pl')}
        of ${of('conf_pl')} planned-care groups. A random order scores ${d('conf_em_random', 2)} and
        ${d('conf_pl_random', 2)}. ${t('conformal_note')}</li>
      <li><strong>Public facilities.</strong> On ${n('public_pairs')} labelled public pairs
        (${n('public_contradicted')} contradicted) we could not show that the score ranks public facilities better
        than chance; the sample is too small to tell ${src('public_pairs')}.</li>
    </ul>
    ${more('History: the earlier prototype, on its own test set', `<p>${t('v1_note')}</p>
      <p>Its test set: ${F(`tables.labels.rows.${testRow}.2`, labels.rows[testRow][2])}.</p>
      <h3>The labels</h3>${tbl('labels', 'What the labels are')}
      <h3>Does the score separate confirmed from not confirmed?</h3><p>Higher is better; a coin toss scores one
      half.</p>${tbl('auroc', 'Area under the ROC curve on the test pairs')}
      <h3>Is the first option right?</h3>${tbl('top1', 'First option over the benchmark queries')}
      <h3>What did not work</h3><ul>${dnw.items.map((x, i) => `<li>${F(`lists.did_not_work.items.${i}`, x)}</li>`).join('')}</ul>
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
