// UI-RECEIPT-1 (#140, lead 15:55Z): a tested-trust line at the top of a Likely option's Why page, right after the
// band and score. k and n come from meta.test_record, which app/facts/build.py copies from
// model/gold/v3/test_eval/results.json (agent-labelled, facility-service pairs, all services pooled). n small dots, k
// filled and the rest crossed, drawn as inline SVG (aria-hidden; the sentence is the text). A classic script sharing
// app.js globals (state, N, th); app.js loads it after the Why page has painted, so it is not part of the first-paint
// bytes (75 KB budget).
'use strict';
const DOT = 8;  // px per dot
function testDotsSvg(k, n) {
  const dots = Array.from({length: n}, (_, j) => {
    const x = j * DOT + DOT / 2, y = DOT / 2, r = DOT / 2 - 1.5;
    return j < k ? `<circle cx="${x}" cy="${y}" r="${r}" style="fill:var(--go)"/>`
      : `<g style="stroke:var(--hazard);stroke-width:1.5;fill:none"><circle cx="${x}" cy="${y}" r="${r}"/>` +
        `<path d="M${x - r * .7} ${y - r * .7}l${r * 1.4} ${r * 1.4}m0 -${r * 1.4}l-${r * 1.4} ${r * 1.4}"/></g>`;
  }).join('');
  return `<svg aria-hidden="true" focusable="false" width="${n * DOT}" height="${DOT}" viewBox="0 0 ${n * DOT} ${DOT}"
    style="display:block;max-width:100%;height:auto;margin:0 0 var(--sp1)">${dots}</svg>`;
}
function RSReceipt() {
  const p = state.plan, tr = p && p.meta && p.meta.test_record, m = location.hash.match(/^#\/why\/(\d+)$/);
  if (!m || !tr || p.offline || p.error || !p.options) return;
  const o = p.options.find(x => x.rank === +m[1]);
  if (!o || o.band !== 'likely') return;
  if (!(Number.isInteger(tr.k) && Number.isInteger(tr.n) && tr.n > 0 && tr.k >= 0 && tr.k <= tr.n)) return;
  const b = document.querySelector('#main .why-head .band'), row = b && b.closest('.why-head > *');
  if (!row || row.parentElement.querySelector('.tested')) return;  // not drawn yet, or already drawn
  const el = document.createElement('div');
  el.className = 'note tested';
  el.innerHTML = testDotsSvg(tr.k, tr.n) + `<p style="margin:0">${th('tested.line', {
    k: N('meta.test_record.k', tr.k), n: N('meta.test_record.n', tr.n)})}</p>`;
  row.after(el);  // straight after the band: before the passed-over line when that is drawn first
}
