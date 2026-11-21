// Referral Saathi skeleton (issue #5). Plain JS, no framework, hash routes:
//   #/ home (S1)  #/gps (S1a)  #/change (S1b)  #/plan (S3 / S3x)  #/why/<rank> (S4 + S5 + S6)
'use strict';

const SERVICES = [
  // Fixed order, emergencies first (spec 3.1). Hindi labels are drafts until review (#10).
  {key: 'emergency_csection', hi: '\u0911\u092a\u0930\u0947\u0936\u0928 \u0938\u0947 \u0921\u093f\u0932\u0940\u0935\u0930\u0940', en: 'Emergency C-section', profile: 'emergency'},
  {key: 'nicu', hi: '\u0928\u0935\u091c\u093e\u0924 ICU', en: 'Newborn ICU (NICU)', profile: 'urgent'},
  {key: 'trauma_emergency', hi: '\u090f\u0915\u094d\u0938\u0940\u0921\u0947\u0902\u091f / \u091a\u094b\u091f', en: 'Accident / injury', profile: 'emergency'},
  {key: 'burn_care', hi: '\u091c\u0932\u0928\u093e', en: 'Burns', profile: 'emergency'},
  {key: 'dialysis', hi: '\u0921\u093e\u092f\u0932\u093f\u0938\u093f\u0938', en: 'Dialysis', profile: 'scheduled'},
  {key: 'mri', hi: 'MRI \u0938\u094d\u0915\u0948\u0928', en: 'MRI scan (planned)', profile: 'planned'},
  {key: 'cardiac_surgery', hi: '\u0926\u093f\u0932 \u0915\u093e \u0911\u092a\u0930\u0947\u0936\u0928', en: 'Heart surgery (planned)', profile: 'planned'},
  {key: 'other', hi: '\u0915\u0941\u091b \u0914\u0930 / \u092a\u0924\u093e \u0928\u0939\u0940\u0902', en: 'Other / not sure', profile: null},
];
// Tiny offline lexicon stub; the real one comes from the taxonomy synonyms (spec 3.1 step 2).
const LEXICON = {
  emergency_csection: ['c-section', 'caesarean', 'cesarean', 'lscs', 'operation se delivery', 'delivery'],
  nicu: ['nicu', 'newborn', 'navjaat', 'sncu', 'baby icu'],
  trauma_emergency: ['accident', 'injury', 'chot', 'trauma', 'fracture'],
  burn_care: ['burn', 'jalna', 'jal gaya'],
  dialysis: ['dialysis', 'kidney', 'khoon saaf', 'kidney machine'],
  mri: ['mri', 'scan'],
  cardiac_surgery: ['heart', 'dil', 'bypass', 'cardiac', 'valve'],
};
const DANGER_SIGNS = ['Heavy bleeding', 'Breathing trouble', 'Unconscious or fitting',
  'Labour with bleeding or baby stuck', 'Chest pain', 'Burn on face or large area'];
const BAND_ICON = {likely: '\u2714', not_verified: '?', unlikely: '\u2716'};

const state = {loc: load('loc'), service: null, danger: new Set(), plan: null, msg: ''};

function load(k) { try { return JSON.parse(localStorage.getItem('rs.' + k)); } catch { return null; } }
function save(k, v) { try { localStorage.setItem('rs.' + k, JSON.stringify(v)); } catch { /* private mode */ } }
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
const $ = sel => document.querySelector(sel);
const svc = key => SERVICES.find(s => s.key === key);
function announce(text) { $('#status').textContent = ''; setTimeout(() => { $('#status').textContent = text; }, 50); }
function timeStr(t) { return new Date(t).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }

// ---------- 108 bar ----------
function isEmergency() {
  const s = svc(state.service);
  return state.danger.size > 0 || (s && (s.profile === 'emergency' || s.profile === 'urgent'));
}
function renderBar() {
  const s = svc(state.service);
  const show102 = s && (s.key === 'emergency_csection' || s.key === 'nicu');
  const onPlan = location.hash.startsWith('#/plan') || location.hash.startsWith('#/why') || location.hash === '#/gps';
  if (!(isEmergency() && (onPlan || state.danger.size))) { $('#bar108').innerHTML = ''; return; }
  $('#bar108').innerHTML = `<div class="bar-108" role="region" aria-label="Emergency numbers">
    <a href="tel:108"><span aria-hidden="true">&#9742;</span>&nbsp;CALL 108 ambulance (free)</a>
    ${show102 ? '<a href="tel:102"><span aria-hidden="true">&#9742;</span>&nbsp;Call 102: pregnant women, babies (free). No answer? Call 108</a>' : ''}
  </div>`;
}

// ---------- location ----------
function locLine(loc) {
  if (!loc) return 'No location yet.';
  const src = {gps: `GPS ${loc.accuracy_m ?? '?'} m`, last_fix: 'last GPS fix', manual: 'typed coordinates',
    pin: 'PIN centre', district: 'district centre'}[loc.source] || loc.source;
  return `${esc(loc.label || `${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)}`)}. ${esc(src)}, ${timeStr(loc.t)}`;
}
function getGps(onDone) {
  if (!('geolocation' in navigator)) { onDone('This phone has no GPS in the browser. Choose a place instead.'); return; }
  navigator.geolocation.getCurrentPosition(p => {
    state.loc = {lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy),
      source: 'gps', t: Date.now(), label: null};
    save('loc', state.loc);
    onDone(null);
  }, e => onDone(e.code === 1 ? 'Location blocked for this site. Type a PIN or place instead.'
    : 'Could not get GPS. Stand outside, or choose a place instead.'),
  {enableHighAccuracy: true, timeout: 120000, maximumAge: 60000});
}

// ---------- screens ----------
function home() {
  const tiles = SERVICES.map(s => `<button type="button" class="tile" data-svc="${s.key}"
      aria-pressed="${state.service === s.key}"><span class="hi" lang="hi">${esc(s.hi)}</span>
      <span class="en">${esc(s.en)}</span></button>`).join('');
  const where = state.loc
    ? `<div class="where"><p><span aria-hidden="true">&#128205;</span> ${locLine(state.loc)}</p>
        <div class="row"><a class="btn" href="#/change">Change location</a>
        <button type="button" id="regps">Update GPS</button></div></div>`
    : `<button type="button" class="btn btn-primary btn-block" id="gps">
        <span aria-hidden="true">&#128205;</span> Use my location (GPS)</button>
       <a class="btn btn-block" href="#/change">Choose a place instead</a>`;
  const boxes = DANGER_SIGNS.map((d, i) => `<label class="check"><input type="checkbox" data-danger="${i}"
      ${state.danger.has(i) ? 'checked' : ''}> ${esc(d)}</label>`).join('');
  return `<h1 tabindex="-1">Where is the patient?</h1>
    ${state.msg ? `<p class="card" role="alert">${esc(state.msg)}</p>` : ''}
    ${where}
    <h2>What does the patient need?</h2>
    <label for="q">Search a service</label>
    <input id="q" type="search" autocomplete="off" placeholder="kidney, delivery, MRI...">
    <div id="matches"></div>
    <div class="tiles" role="group" aria-label="Services">${tiles}</div>
    <div class="bar-108 compact"><span>Chest pain or stroke now?</span>
      <a href="tel:108"><span aria-hidden="true">&#9742;</span>&nbsp;Call 108</a></div>
    <details><summary>Danger signs now?</summary>${boxes}
      <p class="small muted">Checklist written by the team, not clinically reviewed.</p></details>
    <p class="small muted">Saved for offline: not yet (packs arrive with issue #9).</p>`;
}
function bindHome() {
  $('#gps')?.addEventListener('click', () => { location.hash = '#/gps'; });
  $('#regps')?.addEventListener('click', () => { location.hash = '#/gps'; });
  document.querySelectorAll('[data-svc]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.svc)));
  document.querySelectorAll('[data-danger]').forEach(c => c.addEventListener('change', () => {
    c.checked ? state.danger.add(+c.dataset.danger) : state.danger.delete(+c.dataset.danger);
    renderBar();
    if (c.checked) announce('Danger sign ticked. Call 108 now.');
  }));
  $('#q').addEventListener('input', e => {
    const v = e.target.value.trim().toLowerCase();
    const hits = v.length < 2 ? [] : Object.keys(LEXICON).filter(k => LEXICON[k].some(w => w.includes(v) || v.includes(w)));
    $('#matches').innerHTML = hits.map(k => `<button type="button" class="btn btn-block" data-svc="${k}">
      ${esc(svc(k).en)}</button>`).join('') || (v.length >= 2 ? '<p class="small">No match. Try the tiles.</p>' : '');
    $('#matches').querySelectorAll('[data-svc]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.svc)));
  });
}
function pickService(key) {
  if (key === 'other') {
    state.msg = 'Describing a need in your own words needs the model (not built yet). Try the search box or a tile.';
    render(); $('#q').focus(); return;
  }
  state.service = key; state.msg = '';
  if (!state.loc) { state.msg = 'First tell us where the patient is.'; render(); return; }
  location.hash = '#/plan';
}

function gpsScreen() {
  return `<h1 tabindex="-1">Getting GPS from satellites...</h1>
    <p>Stand outside. This can take up to 2 minutes.</p>
    ${state.loc ? `<p>Using now: ${locLine(state.loc)}</p>` : ''}
    <a class="btn btn-block" href="#/change">Choose place instead</a>
    <a class="btn btn-block" href="#/">Back</a>`;
}
function bindGps() {
  getGps(err => { state.msg = err || ''; if (!err) announce('Location found.'); location.hash = '#/'; });
}

function changeScreen() {
  return `<h1 tabindex="-1">Change location</h1>
    <button type="button" class="btn btn-block" id="back-gps"><span aria-hidden="true">&#128205;</span> Back to my GPS location</button>
    <form id="place-form" novalidate>
      <label for="place">PIN, village, town, district, or 'lat, lon'</label>
      <input id="place" type="text" inputmode="text" autocomplete="off" aria-describedby="place-help place-err">
      <p id="place-help" class="small muted">Example: 26.59, 85.48. PIN and place search arrive with /api/resolve.</p>
      <p id="place-err" role="alert"></p>
      <button type="submit" class="btn btn-primary btn-block">Use this place</button>
    </form>
    <a class="btn btn-block" href="#/">Cancel</a>`;
}
function bindChange() {
  $('#back-gps').addEventListener('click', () => { location.hash = '#/gps'; });
  $('#place-form').addEventListener('submit', e => {
    e.preventDefault();
    const v = $('#place').value.trim();
    const m = v.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
    if (m && +m[1] >= 6 && +m[1] <= 37.5 && +m[2] >= 68 && +m[2] <= 97.5) {
      state.loc = {lat: +m[1], lon: +m[2], accuracy_m: null, source: 'manual', t: Date.now(), label: null};
      save('loc', state.loc); state.msg = ''; location.hash = '#/'; return;
    }
    $('#place-err').textContent = /^\d{6}$/.test(v)
      ? 'PIN lookup is not built yet. Type coordinates as "lat, lon".'
      : 'Type coordinates in India as "lat, lon", for example 26.59, 85.48.';
    $('#place').setAttribute('aria-invalid', 'true');
    $('#place').focus();
  });
}

function trackWords(tr) {
  if (!tr || tr.n < 10) return `Listings like this: too few checks yet (${tr ? tr.n : 0} checked)`;
  return `About ${Math.round(10 * tr.k_confirmed / tr.n)} in 10 listings like this checked out (${tr.n} checked)`;
}
function travelWords(t) {
  const how = t.method === 'osrm' ? 'road route' : 'rough';
  return `${Math.round(t.km)} km, about ${t.low}-${t.high} min (${how})`;
}
function bandHtml(o) {
  const word = o.band === 'not_verified' ? 'NOT VERIFIED: call to confirm' : o.band_word.toUpperCase();
  return `<span class="band band-${o.band}"><span aria-hidden="true">${BAND_ICON[o.band]}</span> ${esc(word)}</span>`;
}
function card(o, label) {
  const q = o.evidence[0];
  return `<article class="card" aria-labelledby="opt-${o.rank}">
    ${o.call_first ? '<p class="call-first">Call first</p>' : ''}
    <p>${o.rank}. ${bandHtml(o)}</p>
    <h3 id="opt-${o.rank}">${esc(o.name)}</h3>
    <p class="small">${esc(o.town)}. ${o.operator === 'private' ? 'Private: may charge.' : o.operator === 'public' ? 'Government.' : ''}</p>
    <p>${esc(travelWords(o.travel))}</p>
    ${q ? `<blockquote>"${esc(q.quote)}" <span class="tag">${esc(q.field)}</span></blockquote>` : ''}
    <p class="small">${esc(trackWords(o.track_record))}. About the listing, not about today. Call to check a slot.</p>
    <div class="row"><a class="btn" href="#/why/${o.rank}#call">Call ahead</a>
      <a class="btn" href="#/why/${o.rank}">Why this? <span class="visually-hidden">${esc(o.name)}</span></a></div>
  </article>`;
}
function planScreen() {
  const s = svc(state.service);
  if (!s || !state.loc) return home();
  const p = state.plan;
  const head = `<h1 tabindex="-1">${esc(s.en)} near you</h1><p class="small">${locLine(state.loc)}</p>`;
  if (!p) return head + '<p>Finding options...</p>';
  if (p.error) return head + `<p class="card" role="alert">${esc(p.error)}</p><a class="btn btn-block" href="#/">Back</a>`;
  const label = p.query.service_label.en;
  let body;
  if (p.abstain) {
    const oo = p.abstain.outside_option;
    body = `<p class="card"><strong>${esc(p.abstain.text)}</strong></p>
      <h2>Call to confirm</h2>${p.options.map(o => card(o, label)).join('')}
      ${oo ? `<article class="card"><h3>${esc(oo.name)}</h3><p>${esc(oo.text)}</p><p>${esc(travelWords(oo.travel))}</p></article>` : ''}`;
  } else {
    body = '<h2>Options to call</h2>' + p.options.map(o => card(o, label)).join('') + (p.why_not.length ? `<details><summary>Why not the nearer ones?</summary>
      ${p.why_not.map(w => `<p><strong>${esc(w.name)}</strong>, ${Math.round(w.travel.km)} km: ${esc(w.reason)}</p>`).join('')}
      <p class="small muted">This describes our data, not the facility.</p></details>` : '');
  }
  return head + body + `<p class="small muted">Data as of ${esc(p.as_of)}. ${p.meta.stub ? 'Sample data from a stub, not a real recommendation.' : ''}</p>
    <a class="btn btn-block" href="#/">New search</a>`;
}
async function bindPlan() {
  if (!state.service || !state.loc || state.plan) return;
  const l = state.loc;
  const qs = new URLSearchParams({service: state.service, lat: l.lat.toFixed(2), lon: l.lon.toFixed(2), source: l.source});
  if (l.accuracy_m != null) qs.set('accuracy_m', l.accuracy_m);
  try {
    const r = await fetch('/api/recommend?' + qs, {redirect: 'manual'});
    if (r.type === 'opaqueredirect') throw new Error('Signed out. Reload the page to sign in again.');
    if (!r.ok) throw new Error('The server could not make a plan (' + r.status + ').');
    state.plan = await r.json();
    announce(state.plan.abstain ? 'No confident option. Showing places to call.' : `${state.plan.options.length} options found.`);
  } catch (e) {
    state.plan = {error: navigator.onLine ? e.message : 'No internet. Plans need internet until offline packs land.'};
    announce(state.plan.error);
  }
  render();
}

function whyScreen(rank) {
  const p = state.plan;
  const o = p && !p.error && p.options.find(x => x.rank === rank);
  if (!o) return `<h1 tabindex="-1">Option not found</h1><a class="btn btn-block" href="#/">Start again</a>`;
  const label = p.query.service_label.en;
  const total = o.contributions.reduce((a, c) => a + c.points, 0);
  const width = o.p_hi - o.p_lo;
  const phone = o.phone && o.phone.e164
    ? `<a class="btn btn-primary btn-block" href="tel:${esc(o.phone.e164)}"><span aria-hidden="true">&#9742;</span> Call ${esc(o.phone.display)}</a>`
    : '<p class="card">No dialable number in our data for this listing.</p>';
  const maps = `https://www.google.com/maps/dir/?api=1&destination=${o.lat},${o.lon}&travelmode=driving`;
  return `<a class="btn" href="#/plan">&larr; Plan</a>
    <h1 tabindex="-1">${esc(o.name)} ${bandHtml(o)}</h1>
    <h2>Say this to the family</h2><p>"${esc(o.say_to_family.en)}"</p>
    <h2>From its own listing</h2>
    ${o.evidence.length ? o.evidence.map(e => `<blockquote>"${esc(e.quote)}" <span class="tag">${esc(e.field)}</span>
      <br><a class="small" href="${esc(e.source_url)}" rel="noopener noreferrer">Source page</a></blockquote>`).join('')
      : `<p>Our data has no own sentence about ${esc(label)} for this listing.</p>`}
    <h2>Is it real</h2><p>${esc(o.is_real.join('; '))}</p>
    <h2>Where</h2><p>${esc(o.where_check)}</p>
    ${o.flags.length ? `<h2>Warnings and what we ignored</h2><ul>${o.flags.map(f => `<li>${esc(f)}</li>`).join('')}</ul>` : ''}
    <h2>How sure</h2><p>${esc(o.band_word)} (${o.p.toFixed(2)}, range ${o.p_lo.toFixed(2)} to ${o.p_hi.toFixed(2)}).
      ${width > 0.4 ? 'We are very unsure about this one. ' : ''}${esc(trackWords(o.track_record))} (dev, not final test).</p>
    ${o.why_first_text ? `<h2>Why it ranks here</h2><p>${esc(o.why_first_text)}</p>` : ''}
    <h2>Distance</h2><p>${o.travel.km} km by road, ${o.travel.low}-${o.travel.high} min (${esc(o.travel.label)}).</p>
    <a class="btn btn-block" href="${esc(maps)}" rel="noopener noreferrer">Directions in Google Maps</a>

    <h2 id="how">How we decided</h2>
    <table><caption>Points for "offers ${esc(label)}"</caption>
      <thead><tr><th scope="col">What we weighed</th><th scope="col" class="num">Points</th></tr></thead>
      <tbody>${o.contributions.map(c => `<tr><td>${esc(c.label)}</td><td class="num">${c.points > 0 ? '+' : ''}${c.points}</td></tr>`).join('')}</tbody>
      <tfoot><tr><th scope="row">Total</th><td class="num">${total > 0 ? '+' : ''}${total} &rarr; ${o.p.toFixed(2)}</td></tr></tfoot>
    </table>
    <p class="small muted">Model ${esc(p.meta.model_hash)}. Facility id ${esc(o.facility_id)}.</p>

    <h2 id="call" tabindex="-1">Call ahead</h2>
    ${isEmergency() ? '<p><strong>Call 108 first. Do not wait for this call to send the patient.</strong></p>' : ''}
    ${phone}
    <ol class="script">
      <li>"Is this ${esc(o.name)}, ${esc(o.town)}?"</li>
      <li>"I have a patient who needs ${esc(label)}."</li>
      ${o.call_ahead.map(c => `<li>"${esc(c.question)}" <span class="small muted">(asked because: ${esc(c.asked_because)})</span></li>`).join('')}
      <li>"If you cannot, which hospital nearby can?"</li>
      <li>"Whom should we ask for when we arrive?"</li>
    </ol>
    <div class="row" role="group" aria-label="What did they say?">
      ${['Said yes', 'Said no', 'No answer', 'Wrong number'].map(x => `<button type="button" data-outcome="${x}">${x}</button>`).join('')}
    </div>`;
}
function bindWhy() {
  document.querySelectorAll('[data-outcome]').forEach(b => b.addEventListener('click', () =>
    announce(`Noted: ${b.dataset.outcome}. Outcomes are not saved yet in this skeleton.`)));
  if (location.hash.endsWith('#call')) $('#call')?.focus();
}

// ---------- router ----------
function render() {
  const h = location.hash || '#/';
  let html, bind;
  if (h === '#/gps') [html, bind] = [gpsScreen(), bindGps];
  else if (h === '#/change') [html, bind] = [changeScreen(), bindChange];
  else if (h === '#/plan') [html, bind] = [planScreen(), bindPlan];
  else if (h.startsWith('#/why/')) [html, bind] = [whyScreen(parseInt(h.split('/')[2], 10)), bindWhy];
  else [html, bind] = [home(), bindHome];
  $('#main').innerHTML = html;
  renderBar();
  const h1 = $('#main h1');
  if (h1 && !h.endsWith('#call')) h1.focus({preventScroll: false});
  document.title = (h1 ? h1.textContent.trim() + ' - ' : '') + 'Referral Saathi';
  bind();
}
window.addEventListener('hashchange', () => {
  if (location.hash === '#/' || location.hash === '#/change') state.plan = null;
  render();
});
function setOnline() { $('#offline').hidden = navigator.onLine; }
window.addEventListener('online', setOnline);
window.addEventListener('offline', setOnline);

document.addEventListener('DOMContentLoaded', async () => {
  // The skip link must not change the hash: the router owns it.
  document.querySelector('a[href="#main"]').addEventListener('click', e => { e.preventDefault(); $('#main').focus(); });
  setOnline();
  render();
  // GPS is the default: refresh silently when permission is already granted (no prompt on load).
  try {
    const perm = await navigator.permissions?.query({name: 'geolocation'});
    if (perm && perm.state === 'granted' && (location.hash || '#/') === '#/') getGps(err => { if (!err) render(); });
  } catch { /* Permissions API missing: the GPS button stays */ }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
});
