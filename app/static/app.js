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

// ---------- offline (spec S9; logic in offline.js, loaded lazily) ----------
function savedLine() {
  const m = load('pack');
  if (!m) return 'Saved for offline: not yet. It saves after your first online answer.';
  return `Saved for offline: ${esc(m.state)}, ${new Date(m.saved_at).toLocaleDateString([], {day: 'numeric', month: 'short'})}.`;
}
function needScripts(srcs) {
  return Promise.all(srcs.map(src => document.querySelector(`script[src="${src}"]`)?.dataset.loaded === '1'
    ? Promise.resolve() : new Promise((ok, fail) => {
      const el = document.querySelector(`script[src="${src}"]`) || document.head.appendChild(Object.assign(
        document.createElement('script'), {src}));
      el.addEventListener('load', () => { el.dataset.loaded = '1'; ok(); });
      el.addEventListener('error', fail);
    })));
}
async function loadArea() {
  const l = state.loc;
  state.area = {loading: true};
  try {
    const r = await fetch('/api/area', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({service: state.service, lat: +l.lat.toFixed(2), lon: +l.lon.toFixed(2)}), redirect: 'manual'});
    if (!r.ok) throw new Error('The area plan is not available (' + (r.status || 'signed out') + ').');
    state.area = await r.json();
    announce('Area plan loaded.');
  } catch (e) {
    state.area = {error: navigator.onLine ? e.message : 'The area plan needs internet.'};
  }
  render();
}
function stopWatch() { if (state.stopWatch) { state.stopWatch(); state.stopWatch = null; } }
async function offlinePlan(reason) {
  let pack = null;
  try { await needScripts(['/pack.js', '/offline.js']); pack = await window.RSOffline.loadPack(); } catch { /* not cached */ }
  const R = window.RSOffline;
  const p = {offline: true, reason, pack, confirmed: false, answer: null};
  if (pack && R.fixIsFresh(state.loc)) p.answer = R.answer(pack, state.loc, state.service);
  stopWatch();
  if (R) {
    state.stopWatch = R.watchSatellite(fix => {
      state.loc = fix; save('loc', fix); state.stopWatch = null;
      if (state.plan && state.plan.offline) {
        state.plan.confirmed = true;
        if (state.plan.pack) state.plan.answer = R.answer(state.plan.pack, fix, state.service);
        announce('Updated to GPS now.'); render();
      }
    });
  }
  state.plan = p;
  announce('No internet. ' + (p.answer ? `${p.answer.options.length} saved options.` : 'Showing what is saved on this phone.'));
}
function offlineScreen(s) {
  const p = state.plan, R = window.RSOffline;
  if (!R) {
    return `<h1 tabindex="-1">No internet</h1><p>${esc(p.reason)}</p><p class="card">Nothing is saved on this phone yet.</p>
      <a class="btn btn-primary btn-block" href="tel:108"><span aria-hidden="true">&#9742;</span> Call 108</a>`;
  }
  return R.render(p.answer, {serviceLabel: s.en, locLine: locLine(state.loc), reason: p.reason,
    show102: s.key === 'emergency_csection' || s.key === 'nicu', gettingGps: !!state.stopWatch,
    fresh: p.confirmed || R.fixIsFresh(state.loc), hasPack: !!p.pack});
}
function saveOfflinePack() {
  const l = state.loc;
  needScripts(['/pack.js', '/offline.js']).then(() => window.RSOffline.savePack(l.lat, l.lon)).catch(() => {});
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
    <p class="small muted">${savedLine()}</p>`;
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
      <p id="place-help" class="small muted">PIN works from the data saved on this phone. Or type coordinates, for example 26.59, 85.48.</p>
      <p id="place-err" role="alert"></p>
      <button type="submit" class="btn btn-primary btn-block">Use this place</button>
    </form>
    <div id="district-pick"></div>
    <a class="btn btn-block" href="#/">Cancel</a>`;
}
function bindChange() {
  $('#back-gps').addEventListener('click', () => { location.hash = '#/gps'; });
  districtPicker();
  $('#place-form').addEventListener('submit', e => {
    e.preventDefault();
    const v = $('#place').value.trim();
    const m = v.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
    if (m && +m[1] >= 6 && +m[1] <= 37.5 && +m[2] >= 68 && +m[2] <= 97.5) {
      state.loc = {lat: +m[1], lon: +m[2], accuracy_m: null, source: 'manual', t: Date.now(), label: null};
      save('loc', state.loc); state.msg = ''; location.hash = '#/'; return;
    }
    if (/^\d{6}$/.test(v)) {
      packPlace(p => p.pin(v)).then(ok => {
        if (ok) return;
        $('#place-err').textContent = 'PIN not found in the data saved on this phone. Type coordinates as "lat, lon".';
        $('#place').setAttribute('aria-invalid', 'true');
        $('#place').focus();
      });
      return;
    }
    $('#place-err').textContent = 'Type a 6-digit PIN, or coordinates in India as "lat, lon", for example 26.59, 85.48.';
    $('#place').setAttribute('aria-invalid', 'true');
    $('#place').focus();
  });
}

// Resolve a place from the saved pack (works offline). pick(api) returns {lat, lon, label} or null.
async function packPlace(pick, source = 'pin') {
  try {
    await needScripts(['/pack.js', '/offline.js']);
    const pack = await window.RSOffline.loadPack();
    const hit = pack && pick({pin: v => window.RSOffline.resolvePin(pack, v),
      district: d => window.RSOffline.districtCentre(pack, d)});
    if (!hit) return false;
    state.loc = {lat: hit.lat, lon: hit.lon, accuracy_m: null, source, t: Date.now(), label: hit.label};
    save('loc', state.loc); state.msg = ''; location.hash = '#/';
    return true;
  } catch { return false; }
}
async function districtPicker() {
  if (!load('pack')) return;
  try {
    await needScripts(['/pack.js', '/offline.js']);
    const pack = await window.RSOffline.loadPack();
    if (!pack || !$('#district-pick')) return;
    $('#district-pick').innerHTML = `<label for="district">Or choose a district (saved data)</label>
      <select id="district">${pack.districts.filter(Boolean).map(d => `<option>${esc(d)}</option>`).join('')}</select>
      <button type="button" class="btn btn-block" id="use-district">Use district centre</button>`;
    $('#use-district').addEventListener('click', () => packPlace(p => p.district($('#district').value), 'district'));
  } catch { /* no saved pack */ }
}

// Faithfulness markers (spec 5.4, #30): every value shown from the plan carries its source path in data-f and a
// kind in data-k; app/tests/test_faithfulness.py checks each against the payload. Device-side text (the user's
// location, clock times, call outcomes) is wrapped in data-device instead.
function F(path, text, kind = 'text') { return `<span data-f="${path}" data-k="${kind}">${esc(text)}</span>`; }
function trackHtml(tr, P) {
  if (!tr) return 'Listings like this: not checked yet';
  if (tr.n < 10) return `Listings like this: too few checks yet (${F(P + '.n', tr.n, 'num')} checked)`;
  return `About ${F(P, Math.round(10 * tr.k_confirmed / tr.n), 'tenths')} in 10 listings like this checked out ` +
    `(${F(P + '.n', tr.n, 'num')} checked)`;
}
function travelHtml(t, P) {
  return `${F(P + '.km', Math.round(t.km), 'num')} km, about ${F(P + '.low', t.low, 'num')}-` +
    `${F(P + '.high', t.high, 'num')} min (${F(P + '.method', t.method === 'osrm' ? 'road route' : 'rough', 'method')})`;
}
function bandHtml(o, P) {
  const word = o.band === 'not_verified' ? 'NOT VERIFIED: call to confirm' : o.band_word.toUpperCase();
  return `<span class="band band-${o.band}" data-f="${P}.band" data-k="band"><span aria-hidden="true">${BAND_ICON[o.band]}</span> ${esc(word)}</span>`;
}
function quoteHtml(e, P) {
  return `"${F(P + '.quote', e.quote)}" <span class="tag">${F(P + '.field', e.field)}</span>` +
    ` <span class="tag">${F(P + '.claim_id', e.claim_id)}</span>`;
}
function card(o, label, i) {
  const P = `options.${i}`;
  const q = o.evidence[0];
  return `<article class="card" aria-labelledby="opt-${o.rank}">
    ${o.call_first ? '<p class="call-first">Call first</p>' : ''}
    <p>${F(P + '.rank', o.rank, 'num')}. ${bandHtml(o, P)}</p>
    <h3 id="opt-${o.rank}">${F(P + '.name', o.name)}</h3>
    <p class="small">${F(P + '.town', o.town)}. ${o.operator === 'private' ? 'Private: may charge.' : o.operator === 'public' ? 'Government.' : ''}</p>
    <p>${travelHtml(o.travel, P + '.travel')}</p>
    ${q ? `<blockquote>${quoteHtml(q, P + '.evidence.0')}</blockquote>` : ''}
    <p class="small">${trackHtml(o.track_record, P + '.track_record')}. About the listing, not about today. Call to check a slot.</p>
    <div class="row"><a class="btn" href="#/why/${o.rank}#call">Call ahead</a>
      <a class="btn" href="#/why/${o.rank}">Why this? <span class="visually-hidden">${F(P + '.name', o.name)}</span></a></div>
  </article>`;
}
function planScreen() {
  const s = svc(state.service);
  if (!s || !state.loc) return home();
  const p = state.plan;
  if (p && p.offline) return offlineScreen(s);
  const head = `<h1 tabindex="-1">${esc(s.en)} near you</h1><p class="small" data-device>${locLine(state.loc)}</p>`;
  if (!p) return head + '<p>Finding options...</p>';
  if (p.error) return head + `<p class="card" role="alert">${esc(p.error)}</p><a class="btn btn-block" href="#/">Back</a>`;
  const label = p.query.service_label.en;
  const depth = state.depth || 'quick';
  const toggle = `<div class="row" role="group" aria-label="Detail">${['quick', 'compare', 'area'].map(d =>
    `<button type="button" data-depth="${d}" aria-pressed="${depth === d}">${d[0].toUpperCase() + d.slice(1)}</button>`).join('')}</div>`;
  const foot = `<p class="small muted">Data as of ${F('as_of', p.as_of)}. ${p.meta.stub ? 'Sample data from a stub, not a real recommendation.' : ''}</p>
    <a class="btn btn-block" href="#/">New search</a>`;
  if (depth === 'compare') return head + toggle + compareHtml(p) + foot;
  if (depth === 'area') return head + toggle + areaHtml(state.area) + foot;
  let body;
  if (p.abstain) {
    const oo = p.abstain.outside_option;
    body = `<p class="card"><strong>${F('abstain.text', p.abstain.text)}</strong></p>
      <h2>Call to confirm</h2>${p.options.map((o, i) => card(o, label, i)).join('')}
      ${oo ? `<article class="card"><h3>${F('abstain.outside_option.name', oo.name)}</h3>
        <p>${F('abstain.outside_option.text', oo.text)}</p>
        <p>${travelHtml(oo.travel, 'abstain.outside_option.travel')}</p></article>` : ''}`;
  } else {
    body = '<h2>Options to call</h2>' + p.options.map((o, i) => card(o, label, i)).join('') + (p.why_not.length ? `<details><summary>Why not the nearer ones?</summary>
      ${p.why_not.map((w, k) => `<p><strong>${F(`why_not.${k}.name`, w.name)}</strong>,
        ${F(`why_not.${k}.travel.km`, Math.round(w.travel.km), 'num')} km: ${F(`why_not.${k}.reason`, w.reason)}</p>`).join('')}
      <p class="small muted">This describes our data, not the facility.</p></details>` : '');
  }
  return head + toggle + body + foot;
}

// ---------- Compare depth (S10): same rows for every option; table on desk, cards on phone ----------
const COMPARE_ROWS = [
  ['Band', (o, P) => bandHtml(o, P)],
  ['Offers (range)', (o, P) => `${F(P + '.p', o.p.toFixed(2), 'num')} (${F(P + '.p_lo', o.p_lo.toFixed(2), 'num')} to ${F(P + '.p_hi', o.p_hi.toFixed(2), 'num')})`],
  ['Track record', (o, P) => o.track_record ? `${F(P + '.track_record.k_confirmed', o.track_record.k_confirmed, 'num')} of ${F(P + '.track_record.n', o.track_record.n, 'num')} confirmed` : 'not checked yet'],
  ['Exists / where', (o, P) => `${F(P + '.p_e', o.p_e.toFixed(2), 'num')} / ${F(P + '.p_l', o.p_l.toFixed(2), 'num')}`],
  ['Road km, min', (o, P) => `${F(P + '.travel.km', Math.round(o.travel.km), 'num')}, ${F(P + '.travel.low', o.travel.low, 'num')}-${F(P + '.travel.high', o.travel.high, 'num')}`],
  ['Quote', (o, P) => o.evidence.length ? quoteHtml(o.evidence[0], P + '.evidence.0') : 'none in our data'],
  ['Warnings', (o, P) => o.flags.length ? o.flags.map((f, j) => F(`${P}.flags.${j}`, f)).join('; ') : 'none'],
  ['Phone', (o, P) => !o.phone || !o.phone.e164 ? 'no number in our data'
    : o.phone.shared_listings > 1 ? `shared by ${F(P + '.phone.shared_listings', o.phone.shared_listings, 'num')} listings` : 'number on file, not shared'],
  ['Public / private', (o, P) => F(P + '.operator', o.operator)],
  ['Ask on call', (o, P) => o.call_ahead.length ? F(P + '.call_ahead.0.question', o.call_ahead[0].question) : '-'],
  ['Phone result', o => { const r = (state.outcomes || {})[o.rank]; return r ? `<span data-device>${esc(r.said)} ${timeStr(r.at)}</span>` : '-'; }],
];
function compareHtml(p) {
  if (state.patientHere == null) {
    return `<fieldset class="card"><legend>Is the patient here, at this location?</legend>
      <label class="check"><input type="radio" name="here" value="yes"> Yes</label>
      <label class="check"><input type="radio" name="here" value="no"> No</label></fieldset>
      <p class="small">Choose one to see the comparison.</p>`;
  }
  const opts = p.options;
  const P = i => `options.${i}`;
  const atLeast = 1 - opts.reduce((a, o) => a * (1 - o.p), 1);
  const names = opts.map((o, i) => F(P(i) + '.name', o.name)).join(', then ');
  const head = `<p>${state.patientHere ? 'Patient is at this location.' : 'Patient is elsewhere: distances are from this location.'}</p>
    <p>Plan: ${names}.</p>
    <p>Chance at least one listing checks out: ${F('options', atLeast.toFixed(2), 'atleast')} (assumes they fail independently).</p>`;
  const table = `<div class="compare-table"><table><caption>${F('query.service_label.en', p.query.service_label.en)}: options side by side</caption>
    <thead><tr><th scope="col">Row</th>${opts.map((o, i) => `<th scope="col">${F(P(i) + '.rank', o.rank, 'num')}. ${F(P(i) + '.name', o.name)}</th>`).join('')}</tr></thead>
    <tbody>${COMPARE_ROWS.map(([lab, fn]) => `<tr><th scope="row">${esc(lab)}</th>${opts.map((o, i) => `<td>${fn(o, P(i))}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
  const cards = `<div class="compare-cards">${opts.map((o, i) => `<article class="card" aria-labelledby="cmp-${o.rank}">
    <h3 id="cmp-${o.rank}">${F(P(i) + '.rank', o.rank, 'num')}. ${F(P(i) + '.name', o.name)}</h3>
    <dl class="rows">${COMPARE_ROWS.map(([lab, fn]) => `<dt>${esc(lab)}</dt><dd>${fn(o, P(i))}</dd>`).join('')}</dl>
    <a class="btn" href="#/why/${o.rank}">Why / how <span class="visually-hidden">${F(P(i) + '.name', o.name)}</span></a></article>`).join('')}</div>`;
  const why = opts[0] && opts[0].why_first_text ? `<p><strong>Why first:</strong> ${F(P(0) + '.why_first_text', opts[0].why_first_text)}</p>` : '';
  return head + '<h2>Side by side</h2>' + table + cards + why;
}

// ---------- Area depth (S11 standing plan, S12 ten calls); data from POST /api/area ----------
function areaHtml(a) {
  if (!a || a.loading) return '<p>Loading the area plan...</p>';
  if (a.error) return `<p class="card" role="alert">${esc(a.error)}</p>`;
  const S = a.summary;
  const n = x => F('area.' + x, (x.split('.').reduce((o, k) => o[k], a)).toFixed(2), 'num');
  const rows = a.pins.map((r, i) => {
    const R = `area.pins.${i}`;
    return r.first
      ? `<tr><th scope="row">${F(R + '.pin', r.pin, 'num')}</th><td>${F(R + '.first.name', r.first.name)}</td>
          <td>${F(R + '.backup.name', r.backup.name)}</td>
          <td>${F(R + '.travel.low', r.travel.low, 'num')}-${F(R + '.travel.high', r.travel.high, 'num')}</td>
          <td>${F(R + '.call_first', r.call_first)}</td></tr>`
      : `<tr><th scope="row">${F(R + '.pin', r.pin, 'num')}</th><td colspan="4"><span aria-hidden="true">&#9888;</span>
          No option with public evidence within ${F('area.area.window_min', a.area.window_min, 'num')} min;
          nearest ${F(R + '.nearest_km', r.nearest_km, 'num')} km</td></tr>`;
  }).join('');
  const calls = a.ten_calls.map((c, i) => {
    const C = `area.ten_calls.${i}`;
    return `<tr><th scope="row">${F(C + '.rank', c.rank, 'num')}</th><td>${F(C + '.name', c.name)}</td>
      <td>${F(C + '.phone_kind', c.phone_kind)}</td><td class="num">${F(C + '.areas', c.areas, 'num')}</td>
      <td class="num">+${F(C + '.access_gain', c.access_gain.toFixed(3), 'num')}</td></tr>`;
  }).join('');
  const csv = [['pin', 'first_choice', 'backup', 'min_low', 'min_high', 'call_first', 'nearest_km_if_none']]
    .concat(a.pins.map(r => [r.pin, r.first ? r.first.name : '', r.backup ? r.backup.name : '', r.travel ? r.travel.low : '',
      r.travel ? r.travel.high : '', r.call_first || '', r.nearest_km ?? '']))
    .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  return `<h2>Standing referral plan: ${F('area.query.service_label.en', a.query.service_label.en)}</h2>
    <p>${F('area.area.district', a.area.district)}, ${F('area.area.state', a.area.state)}.
      ${F('area.summary.n_pins', S.n_pins, 'num')} PIN areas.</p>
    <p><strong>${F('area.summary.n_without_option', S.n_without_option, 'num')} of ${F('area.summary.n_pins', S.n_pins, 'num')}
      PIN areas: no option with public evidence within ${F('area.area.window_min', a.area.window_min, 'num')} min.</strong></p>
    <table><caption>Access to ${F('area.query.service_label.en', a.query.service_label.en)}, share of the area</caption><tbody>
      <tr><th scope="row">Access now</th><td class="num">${n('summary.access_now')}</td></tr>
      <tr><th scope="row">If calls confirm the listings</th><td class="num">${n('summary.access_if_confirmed')}</td></tr>
      <tr><th scope="row">Calls could close</th><td class="num">${n('summary.calls_could_close')}</td></tr>
      <tr><th scope="row">No public evidence of care</th><td class="num">${n('summary.no_public_evidence')}</td></tr>
    </tbody></table>
    <p>${F('area.caveat', a.caveat)}</p>
    <table><caption>Plan per PIN area</caption>
      <thead><tr><th scope="col">PIN</th><th scope="col">First choice</th><th scope="col">Backup</th><th scope="col">Minutes</th><th scope="col">Call first</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <h2 id="ten-calls">Calls that close the most of the gap</h2>
    <table><caption>Ten calls, most gain first. A yes on the phone is shown, the score does not change.</caption>
      <thead><tr><th scope="col">#</th><th scope="col">Facility</th><th scope="col">Phone</th><th scope="col" class="num">Areas</th><th scope="col" class="num">Access gain</th></tr></thead>
      <tbody>${calls}</tbody></table>
    <div class="row"><a class="btn" download="area_plan.csv" href="data:text/csv;charset=utf-8,${encodeURIComponent(csv)}">Download CSV</a>
      <button type="button" id="area-print">Print chart</button></div>
    ${a.meta && a.meta.stub ? '<p class="small muted">Sample area data from a stub; the model export replaces it.</p>' : ''}`;
}
async function bindPlan() {
  if (state.plan && state.plan.offline) {
    $('#patient-here')?.addEventListener('click', () => {
      const p = state.plan;
      p.confirmed = true;
      if (p.pack) p.answer = window.RSOffline.answer(p.pack, state.loc, state.service);
      render();
    });
    return;
  }
  document.querySelectorAll('[data-depth]').forEach(b => b.addEventListener('click', () => {
    state.depth = b.dataset.depth; render();
  }));
  document.querySelectorAll('input[name=here]').forEach(r => r.addEventListener('change', () => {
    state.patientHere = r.value === 'yes'; render();
  }));
  $('#area-print')?.addEventListener('click', () => window.print());
  if (state.plan && !state.plan.error && state.depth === 'area' && !state.area) {
    loadArea();
    return;
  }
  if (!state.service || !state.loc || state.plan) return;
  // Offline per spec 3.2.3: navigator.onLine false, a failed /api call, or one slower than 8 s.
  if (!navigator.onLine) { await offlinePlan('This phone has no internet.'); render(); return; }
  const l = state.loc;
  // Rounded to 0.01 deg on the phone too; the point goes in the body, never the URL.
  const body = {service: state.service, lat: +l.lat.toFixed(2), lon: +l.lon.toFixed(2), accuracy_m: l.accuracy_m,
    source: l.source, depth: 'quick'};
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch('/api/plan', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body), redirect: 'manual', signal: ctl.signal});
    if (r.type === 'opaqueredirect') {
      await offlinePlan('Signed out. Reload the page to sign in again. Showing saved data meanwhile.');
    } else if (r.status >= 500) {
      await offlinePlan('The server is not answering. Showing saved data.');
    } else if (!r.ok) {
      state.plan = {error: 'The server could not make a plan (' + r.status + ').'};
      announce(state.plan.error);
    } else {
      state.plan = await r.json();
      announce(state.plan.abstain ? 'No confident option. Showing places to call.' : `${state.plan.options.length} options found.`);
      saveOfflinePack();  // background, never on the critical path
    }
  } catch (e) {
    await offlinePlan(e.name === 'AbortError' ? 'The server took more than 8 seconds. Showing saved data.'
      : 'Could not reach the server. Showing saved data.');
  } finally {
    clearTimeout(timer);
  }
  render();
}

function whyScreen(rank) {
  const p = state.plan;
  const o = p && !p.error && p.options.find(x => x.rank === rank);
  if (!o) return `<h1 tabindex="-1">Option not found</h1><a class="btn btn-block" href="#/">Start again</a>`;
  const P = `options.${p.options.indexOf(o)}`;
  const label = p.query.service_label.en;
  const L = F('query.service_label.en', label);
  const total = o.contributions.reduce((a, c) => a + c.points, 0);
  const width = o.p_hi - o.p_lo;
  const sign = n => (n > 0 ? '+' : '');
  const phone = o.phone && o.phone.e164
    ? `<a class="btn btn-primary btn-block" href="tel:${esc(o.phone.e164)}"><span aria-hidden="true">&#9742;</span> Call ${F(P + '.phone.display', o.phone.display)}</a>`
    : '<p class="card">No dialable number in our data for this listing.</p>';
  const maps = `https://www.google.com/maps/dir/?api=1&destination=${o.lat},${o.lon}&travelmode=driving`;
  const split = o.track_record && o.track_record.split === 'test' ? 'final test' : 'dev, not final test';
  return `<a class="btn" href="#/plan">&larr; Plan</a>
    <h1 tabindex="-1">${F(P + '.name', o.name)} ${bandHtml(o, P)}</h1>
    <h2>Say this to the family</h2><p>"${F(P + '.say_to_family.en', o.say_to_family.en)}"</p>
    <h2>From its own listing</h2>
    ${o.evidence.length ? o.evidence.map((e, j) => `<blockquote>${quoteHtml(e, `${P}.evidence.${j}`)}
      <br><a class="small" href="${esc(e.source_url)}" rel="noopener noreferrer">Source page</a></blockquote>`).join('')
      : `<p>Our data has no own sentence about ${L} for this listing.</p>`}
    <h2>Check the website now</h2>
    <p class="small">Opens this facility's own website now (a few pages, a few seconds). It does not change the label above.</p>
    <button type="button" id="verify-btn" class="btn-block">Check website now</button>
    <div id="verify-out" aria-live="polite">${verifyHtml((state.verify || {})[o.facility_id])}</div>
    <h2>Is it real</h2><p>${o.is_real.map((x, j) => F(`${P}.is_real.${j}`, x)).join('; ')}</p>
    <h2>Where</h2><p>${F(P + '.where_check', o.where_check)}</p>
    ${o.flags.length ? `<h2>Warnings and what we ignored</h2><ul>${o.flags.map((f, j) => `<li>${F(`${P}.flags.${j}`, f)}</li>`).join('')}</ul>` : ''}
    <h2>How sure</h2><p>${F(P + '.band_word', o.band_word)} (${F(P + '.p', o.p.toFixed(2), 'num')}, range
      ${F(P + '.p_lo', o.p_lo.toFixed(2), 'num')} to ${F(P + '.p_hi', o.p_hi.toFixed(2), 'num')}).
      ${width > 0.4 ? 'We are very unsure about this one. ' : ''}${trackHtml(o.track_record, P + '.track_record')} (${split}).</p>
    ${o.why_first_text ? `<h2>Why it ranks here</h2><p>${F(P + '.why_first_text', o.why_first_text)}</p>` : ''}
    <h2>Distance</h2><p>${F(P + '.travel.km', o.travel.km, 'num')} km by road, ${F(P + '.travel.low', o.travel.low, 'num')}-${F(P + '.travel.high', o.travel.high, 'num')} min
      (${F(P + '.travel.label', o.travel.label)}).</p>
    <a class="btn btn-block" href="${esc(maps)}" rel="noopener noreferrer">Directions in Google Maps</a>
    <a class="btn btn-block" href="#/slip/${o.rank}">Make referral slip</a>

    <h2 id="how">How we decided</h2>
    <table><caption>Points for "offers ${L}"</caption>
      <thead><tr><th scope="col">What we weighed</th><th scope="col" class="num">Points</th></tr></thead>
      <tbody>${o.contributions.map((c, j) => `<tr><td>${F(`${P}.contributions.${j}.label`, c.label)}</td>
        <td class="num">${F(`${P}.contributions.${j}.points`, sign(c.points) + c.points, 'num')}</td></tr>`).join('')}</tbody>
      <tfoot><tr><th scope="row">Total</th><td class="num">${F(P + '.contributions', sign(total) + total, 'sum')} &rarr;
        ${F(P + '.p', o.p.toFixed(2), 'num')}</td></tr></tfoot>
    </table>
    <p class="small muted">Model ${F('meta.model_hash', p.meta.model_hash)}. Facility id ${F(P + '.facility_id', o.facility_id)}.</p>

    <h2 id="call" tabindex="-1">Call ahead</h2>
    ${isEmergency() ? '<p><strong>Call 108 first. Do not wait for this call to send the patient.</strong></p>' : ''}
    ${phone}
    <ol class="script">
      <li>"Is this ${F(P + '.name', o.name)}, ${F(P + '.town', o.town)}?"</li>
      <li>"I have a patient who needs ${L}."</li>
      ${o.call_ahead.map((c, j) => `<li>"${F(`${P}.call_ahead.${j}.question`, c.question)}" <span class="small muted">(asked because:
        ${F(`${P}.call_ahead.${j}.asked_because`, c.asked_because)})</span></li>`).join('')}
      <li>"If you cannot, which hospital nearby can?"</li>
      <li>"Whom should we ask for when we arrive?"</li>
    </ol>
    <div class="row" role="group" aria-label="What did they say?">
      ${['Said yes', 'Said no', 'No answer', 'Wrong number'].map(x => `<button type="button" data-outcome="${x}">${x}</button>`).join('')}
    </div>`;
}
// ---------- live website check (#37): a dated line next to the plan; never changes the band ----------
function verifyHtml(v) {
  if (!v) return '';
  if (v.loading) return '<p>Checking the website...</p>';
  if (v.error) return `<p class="card">${esc(v.error)}</p>`;
  const d = new Date(v.checked_at_ms);
  const day = d.toDateString() === new Date().toDateString() ? 'today' : d.toLocaleDateString([], {day: 'numeric', month: 'short'});
  const when = `Checked ${F('verify.checked_at_ms', timeStr(v.checked_at_ms), 'clock')} ${esc(day)}`;
  const q = (x, j) => `<blockquote>"${F(`verify.quotes.${j}.text`, x.text)}"
    <br><a class="small" href="${esc(x.url)}" rel="noopener noreferrer">${F(`verify.quotes.${j}.url`, x.url)}</a></blockquote>`;
  if (v.status === 'found') {
    return `<p class="card">${when}: ${F('verify.status_text', v.status_text)}:</p>${v.quotes.map(q).join('')}`;
  }
  const said = v.quotes.length ? `<p>It mentions it only like this:</p>${v.quotes.map(q).join('')}` : '';
  return `<p class="card">${when}: ${F('verify.status_text', v.status_text)}.</p>${said}`;
}
async function runVerify(o) {
  const key = o.facility_id;
  (state.verify ||= {})[key] = {loading: true};
  $('#verify-out').innerHTML = verifyHtml(state.verify[key]);
  try {
    const r = await fetch('/api/verify', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({facility_id: o.facility_id, service_id: state.service}), redirect: 'manual'});
    const body = r.ok || r.status === 503 ? await r.json() : null;
    state.verify[key] = r.ok ? body : {error: body && body.error ? 'Website check not available: ' + body.error + '.'
      : `Website check failed (${r.status || 'signed out'}).`};
  } catch {
    state.verify[key] = {error: 'Website check needs internet.'};
  }
  const out = $('#verify-out');
  if (out) {
    out.innerHTML = verifyHtml(state.verify[key]);
    announce(state.verify[key].error || `Website checked: ${state.verify[key].status_text}.`);
  }
}
function bindWhy() {
  const rank = parseInt(location.hash.split('/')[2], 10);
  const o = state.plan && !state.plan.error && state.plan.options.find(x => x.rank === rank);
  if (o) $('#verify-btn')?.addEventListener('click', () => runVerify(o));
  document.querySelectorAll('[data-outcome]').forEach(b => b.addEventListener('click', () => {
    // Kept in page memory only, for the slip (#24); never sent or stored.
    (state.outcomes ||= {})[parseInt(location.hash.split('/')[2], 10)] = {said: b.dataset.outcome, at: Date.now()};
    announce(`Noted: ${b.dataset.outcome}. It goes on the referral slip; nothing is sent.`);
  }));
  if (location.hash.endsWith('#call')) $('#call')?.focus();
}

// ---------- referral slip (S8, #24): slip.js loads only on this route ----------
function slipScreen(rank) {
  const p = state.plan;
  const o = p && !p.error && p.options.find(x => x.rank === rank);
  if (!o) return `<h1 tabindex="-1">Option not found</h1><a class="btn btn-block" href="#/">Start again</a>`;
  const lang = state.slipLang || 'en';
  return `<a class="btn no-print" href="#/why/${rank}">&larr; Why this</a>
    <h1 tabindex="-1" class="no-print">Referral slip</h1>
    <div class="row no-print" role="group" aria-label="Slip language">
      <button type="button" data-slip-lang="en" aria-pressed="${lang === 'en'}">English</button>
      <button type="button" data-slip-lang="hi" aria-pressed="${lang === 'hi'}"><span lang="hi">\u0939\u093f\u0928\u094d\u0926\u0940</span></button>
    </div>
    <p class="no-print"><strong>Ask the patient before sending.</strong> No patient name or location goes on the slip.</p>
    <div id="slip-out"><p>Preparing slip...</p></div>
    <div class="row no-print">
      <button type="button" id="slip-big">Show big</button>
      <button type="button" id="slip-print">Print</button>
      <a class="btn" id="slip-wa" href="#" rel="noopener noreferrer">Send on WhatsApp</a>
      <a class="btn" id="slip-sms" href="#">Send by SMS</a>
    </div>`;
}
function loadSlipJs() {
  if (window.RSSlip) return Promise.resolve();
  return new Promise((ok, fail) => {
    const s = document.createElement('script');
    s.src = '/slip.js';
    s.onload = ok;
    s.onerror = fail;
    document.head.appendChild(s);
  });
}
async function bindSlip() {
  const rank = parseInt(location.hash.split('/')[2], 10);
  const p = state.plan;
  const o = p && !p.error && p.options.find(x => x.rank === rank);
  if (!o) return;
  try { await loadSlipJs(); } catch { $('#slip-out').innerHTML = '<p role="alert">Could not load the slip. Check the connection.</p>'; return; }
  const backup = p.options.find(x => x.rank !== rank) || null;
  const lang = state.slipLang || 'en';
  const m = RSSlip.slipModel(p, o, backup, (state.outcomes || {})[rank] || null);
  $('#slip-out').innerHTML = RSSlip.toHtml(m, lang);
  $('#slip-wa').href = RSSlip.toWhatsApp(m, lang).url;
  $('#slip-sms').href = RSSlip.toSms(m, lang).url;
  document.querySelectorAll('[data-slip-lang]').forEach(b => b.addEventListener('click', () => {
    state.slipLang = b.dataset.slipLang;
    render();
  }));
  $('#slip-big').addEventListener('click', () => {
    const on = document.body.classList.toggle('slip-big');
    $('#slip-big').textContent = on ? 'Normal size' : 'Show big';
  });
  $('#slip-print').addEventListener('click', () => window.print());
}

// ---------- router ----------
function render() {
  const h = location.hash || '#/';
  let html, bind;
  if (h === '#/gps') [html, bind] = [gpsScreen(), bindGps];
  else if (h === '#/change') [html, bind] = [changeScreen(), bindChange];
  else if (h === '#/plan') [html, bind] = [planScreen(), bindPlan];
  else if (h.startsWith('#/why/')) [html, bind] = [whyScreen(parseInt(h.split('/')[2], 10)), bindWhy];
  else if (h.startsWith('#/slip/')) [html, bind] = [slipScreen(parseInt(h.split('/')[2], 10)), bindSlip];
  else [html, bind] = [home(), bindHome];
  $('#main').innerHTML = html;
  document.body.classList.toggle('wide', h === '#/plan' && (state.depth === 'compare' || state.depth === 'area'));
  renderBar();
  const h1 = $('#main h1');
  if (h1 && !h.endsWith('#call')) h1.focus({preventScroll: false});
  document.title = (h1 ? h1.textContent.trim() + ' - ' : '') + 'Referral Saathi';
  bind();
}
window.addEventListener('hashchange', () => {
  if (location.hash === '#/' || location.hash === '#/change') {
    state.plan = null; state.outcomes = {}; state.area = null; state.patientHere = null; state.verify = {}; stopWatch();
  }
  document.body.classList.remove('slip-big');
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
