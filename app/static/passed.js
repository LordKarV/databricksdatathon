// UI-PASSED-1 (#140, lead 15:55Z): one "Passed over" line at the top of option 1's Why page, after the band and the
// tested-trust line, from the engine's own why_not[0] row (name, travel km, reason). The rows are relative to the
// first choice, so only option 1's Why page shows it. When the plan says option 1 is already the nearest
// (first_is_nearest), the line says nothing nearer offers the care instead. A classic script sharing app.js globals
// (state, F, N, E, th); app.js loads it after the Why page has painted, so it is not part of the first-paint bytes.
'use strict';
function passedLineHtml(p) {
  if (p.first_is_nearest) return th('passed.none');
  const w = (p.why_not || [])[0];
  if (!w) return '';
  const km = w.travel.km < 10 ? w.travel.km.toFixed(1) : Math.round(w.travel.km);
  return `<strong>${th('passed.over')}</strong>: <b lang="en">${F('why_not.0.name', w.name)}</b>, ${N('why_not.0.travel.km', km)} ${
    th('unit.km')}${th('punct.stop')} ${E('why_not.0.reason', w.reason)}${th('punct.stop')}`;
}
// The Why page's header row that holds the band (and the score); new lines go right after it, in a fixed order.
function whyBandRow() {
  const b = document.querySelector('#main .why-head .band');
  return b && b.closest('.why-head > *');
}
function RSPassed() {
  const p = state.plan, m = location.hash.match(/^#\/why\/(\d+)$/);
  if (!m || !p || p.offline || p.error || !p.options || !p.options.length || p.options[0].rank !== +m[1]) return;
  const row = whyBandRow(), head = row && row.parentElement;
  if (!row || head.querySelector('.passed')) return;  // already drawn
  const html = passedLineHtml(p);
  if (!html) return;
  const after = head.querySelector('.tested') || row;  // the receipt, when drawn, comes first
  after.insertAdjacentHTML('afterend', `<p class="note passed">${html}</p>`);
}
