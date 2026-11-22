// UI-PASSED-1 (#140): one "Passed over" line under the answer card, from the engine's own why_not[0] row (name, travel
// km, reason, as the Why page shows it). When the plan says option 1 is already the nearest (first_is_nearest), the
// line says nothing nearer offers the care instead. A classic script sharing app.js globals (state, F, N, E, th);
// app.js loads it after the answer has painted, so it is not part of the first-paint bytes (75 KB budget).
'use strict';
function passedLineHtml(p) {
  if (p.first_is_nearest) return th('passed.none');
  const w = (p.why_not || [])[0];
  if (!w) return '';
  const km = w.travel.km < 10 ? w.travel.km.toFixed(1) : Math.round(w.travel.km);
  return `<strong>${th('passed.over')}</strong>: <b lang="en">${F('why_not.0.name', w.name)}</b>, ${N('why_not.0.travel.km', km)} ${
    th('unit.km')}${th('punct.stop')} ${E('why_not.0.reason', w.reason)}${th('punct.stop')}`;
}
function RSPassed() {
  const p = state.plan, card = document.querySelector('#main article.answer');
  const box = card && card.closest('#main > *');
  if (location.hash !== '#/plan' || !p || p.offline || !p.options || !p.options.length || !box) return;
  if (box.nextElementSibling && box.nextElementSibling.classList.contains('passed')) return;  // already drawn
  const html = passedLineHtml(p);
  if (!html) return;
  box.insertAdjacentHTML('afterend', `<p class="note passed" style="margin:0 0 var(--sp3)">${html}</p>`);
}
