// Multi-stop route (#47) for the answer screen and Route details: the strip, the compact stop list, the window check and
// every route field. A classic script sharing app.js globals (F, N, E, th, ts, icon, esc, claimHtml); app.js loads it
// together with the /api/plan request, so it is not part of the first-paint bytes (75 KB budget).
'use strict';
// ---------- Multi-stop route (#47): a compact strip and stop list on the answer, every field under "Route details" ----------
// Durations use kind 'dur' (minutes, hours or days back to stored minutes); met / not met uses kind 'met'.
function durText(m) {
  if (m < 120) return ts('dur.min', {n: m});
  if (m >= 1440) return ts(Math.round(m / 1440) === 1 ? 'dur.day' : 'dur.days', {n: Math.round(m / 1440)});
  return ts('dur.h', {n: Math.round(m / 60)});
}
function stopGroups(stops) {
  const g = [];
  stops.forEach((s, k) => {
    if (g.length && g[g.length - 1].id === s.facility_id) g[g.length - 1].ks.push(k);
    else g.push({id: s.facility_id, ks: [k]});
  });
  return g;
}
function evidenceHtml(s, S) {
  if (!s.evidence.length) return `<p class="note">${th(s.n_evidence ? 'route.ev_not_here' : 'route.ev_none')}</p>`;
  return `<ul class="quotes">${s.evidence.map((e, j) => `<li lang="en">"${F(`${S}.evidence.${j}.quote`, e.quote)}"
    ${claimHtml(`${S}.evidence.${j}.claim_id`, e.claim_id)}</li>`).join('')}</ul>
    ${s.n_evidence > s.evidence.length ? `<p class="note">${th('route.ev_more')}</p>` : ''}`;
}
function stopHtml(r, g, P) {
  const s0 = r.stops[g.ks[0]];
  const S0 = `${P}.stops.${g.ks[0]}`;
  const ph = s0.phone && s0.phone.e164;
  const stages = g.ks.map(k => {
    const s = r.stops[k], S = `${P}.stops.${k}`;
    return `<li><strong>${E(S + '.purpose_word', s.purpose_word)}</strong>.
      ${th('route.p', {p: N(S + '.p', s.p.toFixed(2))})}
      ${s.dwell_minutes != null ? th('route.stay', {d: F(S + '.dwell_minutes', durText(s.dwell_minutes), 'dur')}) : ''}
      ${th('route.weakest', {cap: E(S + '.weakest_capability', s.weakest_capability), p: N(S + '.weakest_capability_p', s.weakest_capability_p.toFixed(2))})}
      ${s.question ? `<br>${th('route.ask', {q: E(S + '.question', s.question)})}` : ''}
      <details class="stop-ev"><summary>${th(s.n_evidence === 1 ? 'route.ev_one' : 'route.ev_n', {n: N(S + '.n_evidence', s.n_evidence)})}</summary>
        ${evidenceHtml(s, S)}</details>
      ${s.fallback ? `<p class="note">${th('route.fallback', {name: `<span lang="en">${F(S + '.fallback.name', s.fallback.name)}</span>`,
        eta: N(S + '.fallback.eta_minutes', s.fallback.eta_minutes), p: N(S + '.fallback.p', s.fallback.p.toFixed(2))})}</p>` : ''}
      ${s.note ? `<p class="note">${E(S + '.note', s.note)}</p>` : ''}
      ${s.flags.map((f, j) => `<p class="note">${E(`${S}.flags.${j}`, f)}</p>`).join('')}</li>`;
  }).join('');
  const phone = ph ? `<a href="tel:${esc(ph)}">${th('route.call', {phone: F(S0 + '.phone.' + (s0.phone.display ? 'display' : 'e164'), s0.phone.display || ph)})}</a>`
    : s0.phone && s0.phone.display ? th('route.phone', {phone: F(S0 + '.phone.display', s0.phone.display)}) : th('route.no_phone');
  return `<li><p class="stop-name"><strong lang="en">${F(S0 + '.name', s0.name)}</strong></p>
    <p class="note">${s0.place ? `<span lang="en">${F(S0 + '.place', s0.place)}</span>. ` : ''}${th('route.arrive', {low: N(S0 + '.eta_low', s0.eta_low), high: N(S0 + '.eta_high', s0.eta_high)})}
      ${phone}</p>
    <ul>${stages}</ul></li>`;
}
function routePlanHtml(r, P) {
  const t = r.totals, v = r.vs_direct;
  return `<p>${E(P + '.type_word', r.type_word)}.</p>
    <ol class="stops-full">${stopGroups(r.stops).map(g => stopHtml(r, g, P)).join('')}</ol>
    ${t.minutes_to_definitive != null ? `<p>${th('route.totals', {min: N(P + '.totals.minutes_to_definitive', t.minutes_to_definitive),
      low: N(P + '.totals.low', t.low), high: N(P + '.totals.high', t.high), first: N(P + '.totals.p_first_care', t.p_first_care.toFixed(2)),
      treated: N(P + '.totals.p_treated', t.p_treated.toFixed(2))})}</p><p class="note">${th('route.totals_assume')}</p>` : ''}
    ${r.window_checks.map((c, j) => checkHtml(c, `${P}.window_checks.${j}`, true)).join('')}
    ${v ? `<p class="note vs-direct">${E(P + '.vs_direct.text', v.text)}
      ${v.what_would_change ? E(P + '.vs_direct.what_would_change', v.what_would_change) : ''}</p>` : ''}
    ${v && v.direct_minutes != null ? `<p class="note">${th('route.direct', {n: N(P + '.vs_direct.direct_minutes', v.direct_minutes)})}</p>` : ''}`;
}
function checkHtml(c, C, full) {
  return `<p class="window${c.met ? '' : ' miss'}">${icon(c.met ? 'ok' : 'warn')}<span>${th(full ? 'route.check' : 'route.check_short', {
    check: E(C + '.check', c.check), limit: N(C + '.limit_minutes', c.limit_minutes),
    met: `<strong>${F(C + '.met', ts(c.met ? 'route.met' : 'route.not_met'), 'met')}</strong>`, eta: N(C + '.eta_minutes', c.eta_minutes)})}</span></p>`;
}
// Route strip (design/ui2/SPEC.md): one lane against the clock; each arrival a capsule from eta_low to eta_high; the
// window a rule with the time past it hatched; the line draws once and the first stop pulses. aria-hidden: the stop
// list under it is the accessible version and carries the marked numbers.
// A missed check comes first (safety): the strip and the line under it never show a green "inside the limit" while
// another check (for example definitive care) is not met.
const keyCheck = r => r.window_checks.find(w => !w.met) || r.window_checks[0];
function stripHtml(r) {
  const c = keyCheck(r);
  if (!c) return '';
  const lanes = stopGroups(r.stops).map(g => r.stops[g.ks[0]]);
  const span = 1.1 * Math.max(c.limit_minutes, ...lanes.map(s => s.eta_high));
  const x = m => +(100 * m / span).toFixed(2);
  const wx = x(c.limit_minutes);
  const short = n => n.replace(/^(Sub Divisional|District|Sadar) Hospital,? /, 'SDH ').replace(/ (Hospital|Medical College).*$/, '');
  const labs = lanes.map((s, k) => {
    const S = `itinerary.plans.0.stops.${r.stops.indexOf(s)}`;
    return `<span class="strip-lab" style="${x(s.eta_low) < 50 ? `left:max(0px, calc(${x(s.eta_low)}% - 7px))` : 'right:0;text-align:right'}"><span lang="en">${k + 1}. ${esc(short(s.name))}</span>
    <span class="num">${N(S + '.eta_low', s.eta_low)}-${N(S + '.eta_high', s.eta_high)}</span></span>`;
  }).join('');
  return `<div class="strip" aria-hidden="true">
    <svg><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="6" fill="var(--hazard)" opacity=".5"/></pattern></defs>
      <rect class="late" x="${wx}%" y="12" width="${(100 - wx).toFixed(2)}%" height="24"/><line class="limit" x1="${wx}%" x2="${wx}%" y1="2" y2="44"/>
      ${lanes.map(s => `<line class="eta" x1="${x(s.eta_low)}%" x2="${x(s.eta_high)}%" y1="24" y2="24"/>`).join('')}
      <line class="path" x1="0" x2="${x(lanes[lanes.length - 1].eta_low)}%" y1="24" y2="24" pathLength="1"/>
      <circle cx="0" cy="24" r="4" class="origin"/>${lanes.map((s, k) => `<circle class="stop${k === 0 ? ' now' : ''}" cx="${x(s.eta_low)}%" cy="24" r="7"/>`).join('')}</svg>
    <span class="strip-limit" style="left:calc(${wx}% + 4px)">${c.limit_minutes} ${th('unit.min')}</span>${labs}</div>`;
}
function routeHtml(p) {
  const it = p.itinerary;
  if (!it) return p.itinerary_note ? `<p class="panel note">${E('itinerary_note', p.itinerary_note)}</p>` : '';
  const head = `<h2 id="h-route">${th('route.h')}</h2>
    <p class="note">${th('route.intro', {name: E('itinerary.pathway_name', it.pathway_name)})}</p>
    ${it.stop_1_note ? `<p class="note">${E('itinerary.stop_1_note', it.stop_1_note)}</p>` : ''}
    ${it.itinerary_note ? `<p class="note">${E('itinerary.itinerary_note', it.itinerary_note)}</p>` : ''}`;
  if (it.abstain) return `<section class="section" aria-labelledby="h-route">${head}<p class="panel"><strong>${E('itinerary.abstain', it.abstain)}</strong></p></section>`;
  if (!it.plans.length) return '';
  const r = it.plans[0], P = 'itinerary.plans.0', c = keyCheck(r), ci = r.window_checks.indexOf(c);
  const compact = stopGroups(r.stops).map(g => {
    const s = r.stops[g.ks[0]], S = `${P}.stops.${g.ks[0]}`;
    return `<li><b lang="en">${F(S + '.name', s.name)}</b><span>${g.ks.map(k => E(`${P}.stops.${k}.purpose_word`, r.stops[k].purpose_word)).join(', ')}${c
      ? `, ${th('route.eta', {low: N(S + '.eta_low', s.eta_low), high: N(S + '.eta_high', s.eta_high)})}` : ''}</span></li>`;
  }).join('');
  const legend = c ? `<ul class="legend" aria-hidden="true"><li><span class="sw sw-route"></span>${th('route.legend_route')}</li>
    <li><span class="sw sw-range"></span>${th('route.legend_range')}</li><li><span class="sw sw-late"></span>${th('route.legend_late')}</li></ul>` : '';
  const details = it.plans.map((x, k) => `<h3>${th('route.n', {n: N(`itinerary.plans.${k}.rank`, x.rank)})}</h3>${routePlanHtml(x, `itinerary.plans.${k}`)}`).join('');
  return `<section class="section" aria-labelledby="h-route">${head}
    <div class="panel route">${stripHtml(r)}<ol class="stops">${compact}</ol>
      ${c ? checkHtml(c, `${P}.window_checks.${ci}`, false) : ''}
      ${r.vs_direct && r.vs_direct.text ? `<p class="vs-direct-main">${E(P + '.vs_direct.text', r.vs_direct.text)}</p>` : ''}${legend}
      <details class="route-details"><summary>${th('route.details')}</summary>${details}</details></div></section>`;
}

