// 'How this works' page (issue #45). Loaded lazily on #/how. Renders /api/how (built by app/howto/build.py):
// every number and table cell carries data-f with its path in how.json, and every source links to its repo file.
'use strict';
(function (root) {
  // New strings (#117 A), en and hi, ready for the app-wide language setting. {n} and {of} are marked numbers.
  const TEXT = {
    sites_unreliable: {
      en: 'Listed websites: {n} of {of} facilities with a crawled website have one our crawl marks unreliable (no ' +
        'usable page, no page naming the facility, or another organisation). The app does not cite these pages. ' +
        'The frozen model still reads the crawl through its website terms (W family), so a score can include ' +
        'website points for a site the card marks unreliable.',
      hi: '\u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0926\u0940 \u0917\u0908 ' +
        '\u0935\u0947\u092c\u0938\u093e\u0907\u091f: \u0935\u0947\u092c\u0938\u093e\u0907\u091f ' +
        '\u0935\u093e\u0932\u0947 {of} \u0905\u0938\u094d\u092a\u0924\u093e\u0932\u094b\u0902 ' +
        '\u092e\u0947\u0902 \u0938\u0947 {n} \u0915\u0940 \u0935\u0947\u092c\u0938\u093e\u0907\u091f ' +
        '\u0939\u092e\u093e\u0930\u0940 \u091c\u093e\u0901\u091a \u092e\u0947\u0902 ' +
        '\u092d\u0930\u094b\u0938\u0947 \u0932\u093e\u092f\u0915 \u0928\u0939\u0940\u0902 ' +
        '\u0928\u093f\u0915\u0932\u0940 (\u0915\u094b\u0908 \u0915\u093e\u092e \u0915\u093e ' +
        '\u092a\u0947\u091c \u0928\u0939\u0940\u0902, \u0915\u093f\u0938\u0940 \u092a\u0947\u091c ' +
        '\u092a\u0930 \u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u0915\u093e \u0928\u093e\u092e ' +
        '\u0928\u0939\u0940\u0902, \u092f\u093e \u0915\u093f\u0938\u0940 \u0926\u0942\u0938\u0930\u0940 ' +
        '\u0938\u0902\u0938\u094d\u0925\u093e \u0915\u0940)\u0964 \u0910\u092a \u0907\u0928 ' +
        '\u092a\u0947\u091c\u094b\u0902 \u0915\u094b \u0938\u092c\u0942\u0924 \u0915\u0947 \u0924\u094c\u0930 ' +
        '\u092a\u0930 \u0928\u0939\u0940\u0902 \u0926\u093f\u0916\u093e\u0924\u093e\u0964 ' +
        '\u092e\u0949\u0921\u0932 \u0928\u0939\u0940\u0902 \u092c\u0926\u0932\u093e \u0917\u092f\u093e ' +
        '\u0939\u0948, \u0907\u0938\u0932\u093f\u090f \u0909\u0938\u0915\u0947 ' +
        '\u0935\u0947\u092c\u0938\u093e\u0907\u091f \u0935\u093e\u0932\u0947 \u0905\u0902\u0915 (W) ' +
        '\u0905\u092c \u092d\u0940 \u0909\u0938\u0940 \u091c\u093e\u0901\u091a \u0938\u0947 ' +
        '\u0906\u0924\u0947 \u0939\u0948\u0902\u0964',
    },
  };
  // New wording (#121), en and hi, ready for the app-wide language setting; this page shows 'en' today.
  const HOW_TEXT = {
    similar_apart: {en: 'Shown separately from it, not as a range around it: how often checked pairs with a similar score were confirmed.',
      hi: 'सेवा की संभावना से अलग, उसके आसपास का दायरा नहीं: मिलते-जुलते स्कोर वाली जाँची गई जोड़ियों में कितनी पक्की निकलीं।'},
    rule_lead: {en: "The model's rule, word for word:", hi: 'मॉडल का नियम, शब्दशः:'},
    rule_terms: {en: 'Here p is the service chance, t_L its Likely threshold, P_L the location check, P_E the existence check and T the level of the listing\'s own text about the service; the location and existence checks shown on each option are these same P_L and P_E.',
      hi: 'यहाँ p सेवा की संभावना है, t_L संभावना ज़्यादा की सीमा, P_L जगह की जाँच, P_E अस्पताल होने की जाँच और T लिस्टिंग में सेवा के बारे में उसका अपना लिखा; हर विकल्प पर दिखी जगह और अस्पताल होने की जाँच यही P_L और P_E हैं।'},
  };
  const HT = k => esc(HOW_TEXT[k].en);
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
        service? Each answer is a chance. The service chance comes from the model described below.
        ${HT('similar_apart')}</li>
      <li><strong>Labels.</strong> "Likely" means the model's chance is at least ${d('likely_p', 2)}, the location check
        is at least ${d('likely_p_location', 1)}, the existence check is at least ${d('likely_p_exists', 1)}, and the
        listing has a sentence about the service as its own unit ${src('likely_p')}. ${HT('rule_lead')}
        "${t('band_rule')}" ${src('band_rule')}. ${HT('rule_terms')} Of the ${n('app_pairs')} facility-service pairs the app serves ${src('app_pairs')}: ${n('app_likely')} Likely,
        ${n('app_not_verified')} "Not verified: call to confirm", ${n('app_no_service_text')} "No service text: call
        to ask" (the listing has no sentence about the service), and ${n('app_unlikely')} Unlikely
        ${src('app_likely')}.</li>
      <li><strong>Order.</strong> In an emergency the nearest place that plausibly offers the care comes first: call
        it, and if they say no, call the next. A place we judge Unlikely, or with no sentence of its own about the
        service, is never listed. The model's chance only breaks ties within ${n('tie_min')} minutes
        ${src('tie_min')}. A simulated referral world showed that ordering by the chance discounted by travel time
        sent patients farther and lost time when the first place said no; this rule fixed that (simulated, not a
        field result). For planned care, options are ordered by the model's chance, discounted by travel time
        (${n('scale_planned')} minute scale), because a longer trip to a likelier place pays when there is time. A
        listing with no sentence about the service counts as at most ${d('likely_p', 2)}, so a hospital cannot come
        first on its size or level alone. We search ${n('radius_km')} km and show up to ${n('n_options')} options
        ${src('radius_km')}.</li>
      <li><strong>Saying no.</strong> When nothing is Likely, the app says so, lists places to call, and names the
        nearest hospital the public standard says should offer the service.</li>
      <li><strong>Several stops.</strong> ${n('pathways')} care pathways are written down for time-critical cases
        (${F('facts.pathway_names.value', f.pathway_names.value)}) ${src('pathways')}. For these the app adds a
        suggested route. The route planner uses the model's chance for each service the model scores; for support
        equipment it does not score (operating theatre, ECG, laboratory), it uses the facility's own sentences
        that name it, with fixed assumed chances.</li>
    </ul>

    <h2>How good it is</h2>
    <p>The app uses ${t('v2_model')}: an expert-set scorecard with one calibration step ${src('v2_model')}.
      These results are on DEV pairs, grouped five-fold, out of fold. The labels were made by an agent from public
      web pages, not checked by a person. The sealed test set was opened once, after the model was frozen${f.test_likely
    ? '; its result for Likely is below' : ''}.</p>
    <p>What the chance means: ${t('v2_meaning')}</p>
    ${tbl('v2_eval', 'The model against simpler choices, on DEV pairs')}
    <ul>
      <li><strong>Likely.</strong> ${n('likely_dev')} of ${of('likely_dev')} DEV pairs labelled Likely were
        confirmed (${d('likely_dev_lo', 3)} to ${d('likely_dev_hi', 3)}).</li>
      ${f.test_likely ? `<li class="test-record"><strong>Sealed test.</strong> Likely: ${n('test_likely')} of
        ${of('test_likely')} confirmed (${n('test_likely_pct')}%, interval ${n('test_likely_lo')} to
        ${n('test_likely_hi')}%) on a test set sealed before the model was frozen; agent-labelled, not human-checked
        ${src('test_likely')}. Not shown to rank public facilities (${n('test_public_n')} public test pairs with a
        verdict). Opened once, ${t('test_opened')} UTC, as recorded in the opening log ${src('test_opened')}.
        Commitments: model version <code>${t('test_model_version')}</code>, test predictions hash
        <code>${t('test_predictions_sha')}</code>, test labels hash <code>${t('test_labels_sha')}</code>.</li>` : ''}
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
      ${f.sites_unreliable ? `<li>${TEXT.sites_unreliable.en.replace('{n}', n('sites_unreliable'))
    .replace('{of}', of('sites_unreliable'))} ${src('sites_unreliable')}</li>` : ''}
    </ul>
    <p class="small muted">Page data built ${F('built_at', h.built_at)}.</p>`;
  }

  root.RSHow = {render};
})(typeof window !== 'undefined' ? window : globalThis);
