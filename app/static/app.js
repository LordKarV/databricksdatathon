// Referral Saathi (UI2, design/ui2/SPEC.md). Plain JS, no framework, hash routes:
//   #/lang chooser  #/ home  #/gps  #/change  #/plan answer  #/why/<rank>  #/slip/<rank>  #/settings
//   #/recent  #/area  #/pulse  #/how  #/stories  #/describe  #/note  #/report
// One language on screen at a time: every string comes from /i18n/<lang>.json through ts() / th().
'use strict';

const SERVICES = [  // fixed order, emergencies first (spec 3.1); labels come from the strings files (svc.<key>)
  ['emergency_csection', 'emergency'], ['nicu', 'urgent'], ['trauma_emergency', 'emergency'], ['burn_care', 'emergency'],
  ['dialysis', 'scheduled'], ['mri', 'planned'], ['cardiac_surgery', 'planned'], ['other', null],
].map(([key, profile]) => ({key, profile,
  get en() { return (I18N.en || {})['svc.' + key] || key; }, get hi() { return (I18N.hi || {})['svc.' + key] || key; },
  get label() { return ts('svc.' + key); }}));
const N_DANGER = 6;
const I18N = {};
const LANGS = ['hi', 'en'];
const SIZES = [100, 125, 150];

const state = {loc: load('loc'), service: null, danger: new Set(), plan: null, msg: '', lang: null};

function load(k) { try { return JSON.parse(localStorage.getItem('rs.' + k)); } catch { return null; } }
function save(k, v) { try { localStorage.setItem('rs.' + k, JSON.stringify(v)); return true; } catch { return false; } }  // false: private mode or full
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
const $ = sel => document.querySelector(sel);
const svc = key => SERVICES.find(s => s.key === key);
function announce(text) { $('#status').textContent = ''; setTimeout(() => { $('#status').textContent = text; }, 50); }
function timeStr(t) {  // Hindi: 24-hour (Chromium's hi-IN data writes a Latin am/pm)
  return new Date(t).toLocaleTimeString(state.lang === 'hi' ? 'hi-IN' : 'en-IN',
    state.lang === 'hi' ? {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'} : {hour: '2-digit', minute: '2-digit'});
}
const locale = () => (state.lang === 'hi' ? 'hi-IN' : 'en-IN');

// ---------- strings ----------
function raw(key) { return (I18N[state.lang] || {})[key] ?? (I18N.en || {})[key] ?? key; }
// ts: plain text (announcements, labels, speech). th: HTML; the template is escaped, vars go in as given (callers
// pass escaped text or F() markup, so payload values keep their data-f marker inside a translated sentence).
function ts(key, vars = {}) { return raw(key).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)); }
function th(key, vars = {}) { return esc(raw(key)).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)); }
window.ts = ts;
window.rsEngHi = text => engHi(String(text), curQuery());  // slip.js and journey.js: the same Hindi templates
window.th = th;
async function loadStrings() {
  const get = l => fetch(`/i18n/${l}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  [I18N.en, I18N.hi] = await Promise.all([get('en'), get('hi')]);
}
function pickLang() {
  const l = load('lang');
  if (l === 'hi' || l === 'en') return l;
  const old = (load('voice') || {}).lang;  // UI1 kept a read-aloud language; it becomes the app language once
  return old === 'hi' || old === 'en' ? old : null;
}
function phoneLang() { const l = (navigator.language || '').toLowerCase(); return l.startsWith('hi') || l.endsWith('-in') ? 'hi' : 'en'; }

// Engine text (band reasons, why-not reasons, call-ahead questions, route words) is English in the payload. In Hindi
// the reviewed template from hi.json "engine" is shown, marked data-k="template" with the payload path; a sentence
// joined with "; " is translated clause by clause; text with no template stays English, marked lang="en".
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function engHi(text, q, mark = false) {
  const map = (I18N.hi || {}).engine || {};
  const one = part => {
    if (map[part] != null) return map[part];
    for (const [k, v] of Object.entries(map)) {
      if (!k.includes('{') || k.startsWith('_')) continue;
      const names = [];
      let pat = reEsc(k);
      if (q) pat = pat.split('\\{label\\}').join(reEsc(q.service_label.en));
      pat = pat.replace(/\\\{(\w+)\\\}/g, (_, n) => { names.push(n); return '(.+?)'; });
      const m = part.match(new RegExp('^' + pat + '$'));
      if (!m) continue;
      const vals = {label: q ? q.service_label.hi : ''};
      names.forEach((n, i) => {
        const hi = n === 'need' && (map._needs || {})[m[i + 1]];
        vals[n] = hi || (mark && /[A-Za-z]/.test(m[i + 1]) ? '\u0001' + m[i + 1] + '\u0002' : m[i + 1]);
      });
      return v.replace(/\{(\w+)\}/g, (_, n) => vals[n] ?? '');
    }
    return null;
  };
  const whole = one(text);
  if (whole != null || !text.includes('; ')) return whole;
  const parts = text.split('; ').map((p, i) => one(i ? p[0].toUpperCase() + p.slice(1) : p));
  return parts.every(p => p != null) ? parts.join('; ') : null;
}
function E(path, text, q = curQuery()) {
  if (state.lang !== 'hi') return F(path, text);
  const hi = engHi(String(text), q, true);
  const html = hi == null ? '' : esc(hi).replace(/\u0001/g, '<span lang="en">').replace(/\u0002/g, '</span>');
  return hi != null ? `<span data-f="${path}" data-k="template">${html}</span>` : `<span lang="en">${F(path, text)}</span>`;
}
const curQuery = () => (state.plan && state.plan.query) || (state.area && state.area.query) || null;

// ---------- icons: 24 px grid, 2 px stroke, round ends (design/ui2/SPEC.md, components) ----------
const ICONS = {
  pin: '<path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  phone: '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>',
  speaker: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  map: '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7"/><path d="M12 17h.01"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  wifiOff: '<path d="M3 3l18 18"/><path d="M8.5 16.5a5 5 0 0 1 7 0M5 12.5a10 10 0 0 1 5-2.7M14.5 9.9A10 10 0 0 1 19 12.5M2 8.8A15 15 0 0 1 6.6 6M11 5.1A15 15 0 0 1 22 8.8"/><path d="M12 20h.01"/>',
  ok: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
  warn: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="1"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  camera: '<path d="M4 7h3l2-3h6l2 3h3v13H4z"/><circle cx="12" cy="13" r="4"/>',
  emergency_csection: '<circle cx="11" cy="4.5" r="2"/><path d="M9 21v-6l-1-1V9.5A2.5 2.5 0 0 1 10.5 7h1A3.5 3.5 0 0 1 15 10.5c1.7.6 2.5 2 2.5 3.5 0 1.9-1.6 3-3.5 3H13v4"/>',
  nicu: '<path d="M3 19h18M5 19v-6a7 7 0 0 1 14 0v6"/><circle cx="9.5" cy="14.5" r="2"/><path d="M11.5 15.5h4"/>',
  trauma_emergency: '<rect x="2.5" y="8" width="19" height="8" rx="4" transform="rotate(-45 12 12)"/><path d="M10 10h.01M14 14h.01M10 14h.01M14 10h.01"/>',
  burn_care: '<path d="M12 21c-4 0-7-2.7-7-6.5 0-3.5 3-5.5 3-9 2.5 1.5 4 3.5 4 6 1-1 1.5-2 1.5-3.5 2.5 2 4.5 4.5 4.5 7 0 3.6-2.5 6-6 6z"/>',
  dialysis: '<path d="M14 4c-4-1.5-9 1.5-9 7.5S9 21 13 20c2.5-.6 2.5-3 1.5-4.5S12 12 14.5 10.5 18 6 14 4z"/><path d="M19 12.5l1.5 2.5a1.8 1.8 0 1 1-3 0z"/>',
  mri: '<circle cx="12" cy="10" r="7"/><circle cx="12" cy="10" r="3"/><path d="M3 20h18M7 17v3M17 17v3"/>',
  cardiac_surgery: '<path d="M12 20s-8-4.8-8-10.5A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 8 2.5C20 15.2 12 20 12 20z"/><path d="M4.5 12H9l1.5-2.5 2 5L14 12h5.5"/>',
};
ICONS.other = ICONS.help;
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
window.rsIcon = icon;
const BAND_SVG = {
  likely: '<circle cx="8" cy="8" r="7"/><path d="M4.5 8.5l2.2 2.2 4.8-5" fill="none"/>',
  not_verified: '<path d="M8 1l7 7-7 7-7-7z"/><path d="M6.4 6.3a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.6-.7 1.1M8 11.4v.1" fill="none"/>',
  unlikely: '<rect x="1.5" y="1.5" width="13" height="13"/><path d="M5 5l6 6M11 5l-6 6"/>',
};
const bandSvg = b => `<svg class="bs" viewBox="0 0 16 16" aria-hidden="true">${BAND_SVG[b] || BAND_SVG.not_verified}</svg>`;

// ---------- 108 bar ----------
function isEmergency() {
  const s = svc(state.service);
  return state.danger.size > 0 || !!state.dangerText || (s && (s.profile === 'emergency' || s.profile === 'urgent'));
}
const has102 = key => key === 'emergency_csection' || key === 'nicu';
function sosHtml(with102) {
  return `<a href="tel:108">${icon('phone')}<span><b>${th('sos.108')}</b> <span>${th('sos.free')}</span></span></a>
    ${with102 ? `<a href="tel:102">${icon('phone')}<span><b>${th('sos.102')}</b> <span>${th('sos.102_sub')}</span></span></a>` : ''}`;
}
function renderBar() {
  const s = svc(state.service);
  const h = location.hash;
  const onPlan = h.startsWith('#/plan') || h.startsWith('#/why') || h === '#/gps';
  if (!(isEmergency() && (onPlan || state.danger.size || state.dangerText))) { $('#bar108').innerHTML = ''; return; }
  $('#bar108').innerHTML = `<nav class="sos" aria-label="${th('sos.label')}">${sosHtml(s && has102(s.key))}</nav>`;
}

// ---------- location ----------
const coordText = loc => `${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)}`;
function nearHtml(n) {
  const en = x => `<span lang="en">${esc(x)}</span>`;
  return th(n.place ? 'home.near' : 'home.near_district', {place: en(n.place), district: en(n.district), pin: esc(n.pin)});
}
function fixTime(t) {
  return new Date(t).toLocaleTimeString(locale(), {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
}
function locLine(loc) {
  if (!loc) return th('loc.none');
  const src = {gps: ts('loc.gps', {m: loc.accuracy_m ?? '?'}), last_fix: ts('loc.last_fix'), manual: ts('loc.manual'),
    pin: ts('loc.pin'), district: ts('loc.district'), place: ts('loc.place')}[loc.source] || loc.source;
  if (loc.near) {
    return `${nearHtml(loc.near)}${th('punct.stop')} ${esc(src)}, ${fixTime(loc.t)} <span class="coords">${coordText(loc)}</span>`;
  }
  if (loc.label && ['pin', 'district', 'place'].includes(loc.source)) return `<span lang="en">${esc(loc.label)}</span>, ${fixTime(loc.t)}`;
  return `${esc(loc.label || coordText(loc))}. ${esc(src)}, ${fixTime(loc.t)}`;
}
async function fetchNear() {
  const l = state.loc;
  if (!l || l.near || !['gps', 'last_fix', 'manual'].includes(l.source)) return;
  try {
    const r = await fetch('/api/place/near', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lat: l.lat, lon: l.lon}), signal: AbortSignal.timeout(8000)});
    const n = r.ok && await r.json();
    if (!n || !n.district || state.loc !== l) return;
    l.near = n;
    save('loc', l);
    const el = $('#where-line');
    if (el) el.innerHTML = locLine(l);
  } catch {}
}
function getGps(onDone) {
  if (!('geolocation' in navigator)) { onDone(ts('gps.none')); return; }
  navigator.geolocation.getCurrentPosition(p => {
    state.loc = {lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy),
      source: 'gps', t: Date.now(), label: null};
    save('loc', state.loc); state.gpsDenied = false;
    onDone(null);
  }, e => {
    if (e.code === 1) state.gpsDenied = true;
    onDone(e.code === 1 ? ts('gps.blocked') : ts('gps.failed'));
  },
  {enableHighAccuracy: true, timeout: 120000, maximumAge: 60000});
}

// ---------- offline (spec S9; logic in offline.js, loaded lazily) ----------
function savedLine() {
  const m = load('pack');
  if (!m) return th('offline.not_yet');
  return th('offline.saved', {state: esc(m.state), date: esc(new Date(m.saved_at).toLocaleDateString(locale(), {day: 'numeric', month: 'short'}))});
}
function needScripts(srcs) {
  return Promise.all(srcs.map(src => document.querySelector(`script[src="${src}"]`)?.dataset.loaded === '1'
    ? Promise.resolve() : new Promise((ok, fail) => {
      const el = document.querySelector(`script[src="${src}"]`) || document.head.appendChild(Object.assign(
        document.createElement('script'), {src}));
      el.addEventListener('load', () => { el.dataset.loaded = '1'; ok(); });
      el.addEventListener('error', () => { el.remove(); fail(); });  // removed, so a later call retries
    })));
}
async function loadArea() {
  const l = state.loc;
  state.area = {loading: true};
  try {
    const r = await fetch('/api/area', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({service: state.service, lat: +l.lat.toFixed(2), lon: +l.lon.toFixed(2)}), redirect: 'manual'});
    if (!r.ok) throw new Error(ts('area.unavailable', {code: r.status || ts('err.signed_out')}));
    state.area = await r.json();
    announce(ts('area.loaded'));
  } catch (e) {
    state.area = {error: navigator.onLine ? e.message : ts('area.needs_net')};
  }
  render();
}
function stopWatch() { if (state.stopWatch) { state.stopWatch(); state.stopWatch = null; } }
const OFFLINE_PACK_MS = 6000;  // a hanging network (weak 2G): the saved answer after 6 s, not "Finding..." forever
async function offlinePlan(reason, live = () => true) {  // reason: a strings key, shown in the language at render time
  let pack = null;
  try {
    pack = await Promise.race([needScripts(['/pack.js', '/offline.js']).then(() => window.RSOffline.loadPack()),
      new Promise((_, no) => setTimeout(() => no(new Error('pack timeout')), OFFLINE_PACK_MS))]);
  } catch { /* not cached, or the network hangs */ }
  if (!live()) return false;
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
        announce(ts('gps.updated')); render();
      }
    }, () => { state.stopWatch = null; if (state.plan && state.plan.offline) render(); });
  }
  state.plan = p;
  announce(ts('off.h') + '. ' + (p.answer ? ts('off.n_saved', {n: p.answer.options.length}) : ts('off.showing')));
  return true;
}
function offlineScreen(s) {
  const p = state.plan, R = window.RSOffline;
  if (!R) {
    return `<h1 tabindex="-1">${th('off.h')}</h1>${offNotice(ts(p.reason))}<p class="panel">${th('off.nothing')}</p>
      <a class="btn btn-hazard btn-block" href="tel:108">${icon('phone')} ${th('sos.108')}</a>`;
  }
  const fresh = p.confirmed || R.fixIsFresh(state.loc);
  const body = R.render(p.answer, {serviceLabel: s.label, locLine: locLine(state.loc), reason: ts(p.reason),
    show102: has102(s.key), gettingGps: !!state.stopWatch, fresh, hasPack: !!p.pack});
  // #140 DA-1: saved cards to call come first; the notice and Retry follow (the heading's dates say it is saved)
  return fresh && p.answer && p.answer.options.length ? body + offNotice(ts(p.reason)) : offNotice(ts(p.reason)) + body;
}
function offNotice(reason) {
  return `<div class="offline-note" role="status">${icon('wifiOff')}<div><b>${th('off.h')}</b><p>${esc(reason)}</p>
    <p>${th('off.next')}</p></div></div>
    <button type="button" class="btn btn-block" id="retry">${th('off.retry')}</button>`;
}
function saveOfflinePack() {
  const l = state.loc;
  needScripts(['/pack.js', '/offline.js']).then(() => window.RSOffline.savePack(l.lat, l.lon)).catch(() => {});
}

// ---------- chooser (first launch) ----------
function chooserScreen() {
  const pre = state.lang || phoneLang();
  const order = LANGS;  // Hindi first (#140 3f)
  const S = l => I18N[l] || {};
  return `<div class="chooser">
    <svg class="mark" viewBox="0 0 28 28" aria-hidden="true"><path d="M5 14h18" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
      <circle cx="6" cy="14" r="4" fill="var(--surface)" stroke="currentColor" stroke-width="2.5"/><circle cx="22" cy="14" r="4.5" fill="var(--go)"/></svg>
    <h1 tabindex="-1" lang="${order[0]}">${esc(S(order[0])['lang.choose_h'])}</h1><p class="sub" lang="${order[1]}">${esc(S(order[1])['lang.choose_h'])}</p>
    <fieldset><legend class="visually-hidden">${esc(S('hi')['lang.choose_h'])} / ${esc(S('en')['lang.choose_h'])}</legend><div class="choice">
      ${order.map(l => `<label lang="${l}"><input type="radio" name="first-lang" value="${l}" ${l === pre ? 'checked' : ''}> ${esc(S(l)['lang.name'])}</label>`).join('')}
    </div></fieldset>
    <button type="button" class="btn btn-block btn-big btn-ink" id="lang-go" lang="${pre}">${esc(S(pre)['lang.continue'])}</button>
    <p class="note" id="lang-note" lang="${pre}">${esc(S(pre)['lang.later'])}</p></div>`;
}
function bindChooser() {
  document.querySelectorAll('input[name=first-lang]').forEach(r => r.addEventListener('change', () => {
    const l = r.value;
    Object.assign($('#lang-go'), {lang: l, textContent: I18N[l]['lang.continue']});
    Object.assign($('#lang-note'), {lang: l, textContent: I18N[l]['lang.later']});
  }));
  $('#lang-go').addEventListener('click', () => {
    setLang(document.querySelector('input[name=first-lang]:checked').value, {rerender: false});
    location.hash = state.afterLang || '#/';
    state.afterLang = null;
  });
}

// ---------- home ----------
function home() {
  const tiles = SERVICES.map(s => `<button type="button" class="tile${s.profile === 'emergency' || s.profile === 'urgent' ? ' emergency' : ''}"
      data-svc="${s.key}" aria-pressed="${state.service === s.key}">${icon(s.key)}<span>${esc(s.label)}</span></button>`).join('');
  const where = state.loc
    ? `<a class="where" href="#/change">${icon('pin')}<span class="where-text"><b data-device id="where-line">${locLine(state.loc)}</b></span>
        <span class="where-change">${th('home.change')}</span></a>
       <button type="button" class="btn btn-block" id="regps">${th('home.update_gps')}</button>`
    : state.gpsDenied  // #121 bug 5: with GPS blocked, typing the place is the way in, so it comes first
      ? `<p class="note place-hint">${th('gps.blocked')}</p>
         <a class="btn btn-ink btn-block" href="#/change">${th('place.type')}</a>
         <button type="button" class="btn btn-block" id="gps">${icon('pin')} ${th('home.use_gps')}</button>`
      : `<button type="button" class="btn btn-ink btn-block" id="gps">${icon('pin')} ${th('home.use_gps')}</button>
         <a class="btn btn-block" href="#/change">${th('home.choose_place')}</a>`;
  const boxes = Array.from({length: N_DANGER}, (_, i) => `<label class="check"><input type="checkbox" data-danger="${i}"
      ${state.danger.has(i) ? 'checked' : ''}> ${th('danger.' + i)}</label>`).join('');
  return `<h1 class="visually-hidden" tabindex="-1">${th('home.h')}</h1>
    <div class="sos-home"><div class="sos-row"><p>${th('home.sos')}</p><a class="btn btn-hazard" href="tel:108">${icon('phone')} 108</a></div>
      <div class="sos-row"><p>${th('home.sos_102')}</p><a class="btn btn-hazard" href="tel:102">${icon('phone')} 102</a></div></div>
    ${state.msg ? `<p class="panel" role="alert">${esc(state.msg)}</p>` : ''}
    <section class="section" aria-labelledby="h-where"><h2 id="h-where">${th('home.where')}</h2><div class="stack-sm">${where}</div></section>
    <section class="section" aria-labelledby="h-need"><h2 id="h-need">${th('home.need_h')}</h2>
      <a class="btn btn-block btn-big btn-ink" href="#/describe">${icon('mic')} ${th('home.speak')}</a>
      <label for="q" class="search-label">${th('home.search')}</label>
      <input id="q" type="search" autocomplete="off" placeholder="${th('home.search_ph')}">
      <div id="matches"></div>
      <div class="tiles" role="group" aria-label="${th('home.need_h')}">${tiles}</div>
      <div class="pair"><a class="btn" href="#/describe">${icon('keyboard')} ${th('home.type')}</a>
        <a class="btn" href="#/note">${icon('camera')} ${th('home.scan')}</a></div></section>
    <details class="section"><summary>${th('home.danger_h')}</summary>${boxes}
      <p class="note">${th('home.danger_note')}</p></details>
    ${RECENT().length ? `<a class="btn btn-block section" href="#/report">${th('report.link')}</a>` : ''}
    <p class="note section">${savedLine()}</p>`;
}
function bindHome() {
  fetchNear();
  $('#gps')?.addEventListener('click', () => { location.hash = '#/gps'; });
  $('#regps')?.addEventListener('click', () => { location.hash = '#/gps'; });
  document.querySelectorAll('[data-svc]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.svc)));
  document.querySelectorAll('[data-danger]').forEach(c => c.addEventListener('change', () => {
    c.checked ? state.danger.add(+c.dataset.danger) : state.danger.delete(+c.dataset.danger);
    renderBar();
    if (c.checked) announce(ts('home.danger_ticked'));
  }));
  $('#q').addEventListener('input', e => {
    const v = e.target.value.trim().toLowerCase();
    RSInput.setDanger(RSInput.dangerHit(v));
    const hits = RSInput.searchHits(v);
    $('#matches').innerHTML = hits.map(k => `<button type="button" class="btn btn-block" data-svc="${k}">
      ${esc(svc(k).label)}</button>`).join('') || (v.length >= 2 ? `<p class="note">${th('home.no_match')}</p>` : '');
    $('#matches').querySelectorAll('[data-svc]').forEach(b => b.addEventListener('click', () => pickService(b.dataset.svc)));
  });
}
function pickService(key) {
  if (key === 'other') { location.hash = '#/describe'; return; }
  state.service = key; state.msg = '';
  if (!state.loc) { state.msg = ts('home.where_first'); render(); return; }
  if (location.hash === '#/plan') render();  // same hash: no hashchange would fire
  else location.hash = '#/plan';
}

function gpsScreen() {
  return `<h1 tabindex="-1">${th('gps.h')}</h1>
    <p>${th('gps.wait')}</p>
    ${state.loc ? `<p data-device>${th('gps.using', {loc: locLine(state.loc)})}</p>` : ''}
    <a class="btn btn-block section" href="#/change">${th('home.choose_place')}</a>
    <a class="btn btn-block" href="#/">${th('nav.back')}</a>`;
}
function bindGps() {
  getGps(err => {
    state.msg = err || '';
    if (!err) announce(ts('gps.found'));
    // GPS blocked: go straight to typing the place, which then comes first (#121 bug 5).
    location.hash = state.gpsDenied && !state.loc ? '#/change' : '#/';
  });
}

// Typed place (#121 bug 5): online the server resolves PINs, districts, towns and post offices (/api/place);
// offline only the saved pack can, so PINs and districts of a saved state. Coordinates always work.
const PLACE_SOURCE = {pin: 'pin', district: 'district', town: 'place', post_office: 'place'};
function changeScreen() {
  const gpsBtn = `<button type="button" class="btn btn-block section" id="back-gps">${icon('pin')} ${th(state.gpsDenied ? 'place.try_gps' : 'place.back_gps')}</button>`;
  return `<h1 tabindex="-1">${th('place.h')}</h1>
    ${state.gpsDenied ? `<p class="panel place-hint section">${th('place.gps_blocked_hint')}</p>` : gpsBtn}
    <form id="place-form" class="section" novalidate>
      <label for="place">${th('place.label')}</label>
      <input id="place" type="text" inputmode="text" autocomplete="off" maxlength="80" aria-describedby="place-help place-err">
      <p id="place-help" class="note">${th('place.help')}</p>
      <p id="place-err" class="err" role="alert">${state.placeMsg ? esc(state.placeMsg) : ''}</p>
      <div id="place-choices"></div>
      <button type="submit" class="btn btn-ink btn-block">${th('place.use')}</button>
    </form>
    <div id="district-pick" class="section"></div>
    ${state.gpsDenied ? gpsBtn : ''}
    <a class="btn btn-block section" href="#/">${th('nav.cancel')}</a>`;
}
// The six digits of a typed PIN ("848 125", "848-125", "PIN 848125", "pin: 848125", "848125."), else null.
// Same rule as pin_of() in facts/places.py, so a PIN that resolves online also resolves from a saved pack.
function pinOf(v) {
  const m = String(v || '').trim().match(/^(?:(?:pin|\u092a\u093f\u0928)(?:\s*code|\s*\u0915\u094b\u0921)?\s*[:#.-]?\s*)?([0-9](?:[0-9\s-]*[0-9])?)[.,;:!]*$/i);
  const d = m ? m[1].replace(/[\s-]/g, '') : '';
  return d.length === 6 ? d : null;
}
function usePlace(hit, source) {
  state.loc = {lat: hit.lat, lon: hit.lon, accuracy_m: null, source, t: Date.now(), label: hit.label};
  save('loc', state.loc); state.msg = ''; location.hash = '#/';
}
function placeErr(text) {
  $('#place-err').textContent = text;
  $('#place').setAttribute('aria-invalid', 'true');
  $('#place').focus();
}
// {matches} from the server ([] when it knows no such place), or null when it cannot answer (offline, signed out).
async function serverPlace(q) {
  if (!navigator.onLine) return null;
  try {
    const r = await fetch('/api/place', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({q}), redirect: 'manual'});
    const j = r.ok || r.status === 404 ? await r.json() : null;
    return j && Array.isArray(j.matches) ? j : null;
  } catch { return null; }
}
function placeChoices(matches) {
  $('#place-choices').innerHTML = `<div role="group" aria-labelledby="place-choices-h" class="place-choices">
    <p id="place-choices-h">${th('place.choose', {n: matches.length})}</p>
    ${matches.map((m, i) => `<button type="button" class="btn btn-block" data-place="${i}">${esc(m.label)}</button>`).join('')}
    </div>`;
  $('#place-choices').querySelectorAll('[data-place]').forEach(b => b.addEventListener('click', () => {
    const m = matches[+b.dataset.place];
    usePlace(m, PLACE_SOURCE[m.kind] || 'place');
  }));
  $('#place-choices [data-place]').focus();
}
// Offline: a PIN, or a district name, from every saved pack.
async function packHit(v) {
  try {
    await needScripts(['/pack.js', '/offline.js']);
    const pack = await window.RSOffline.loadPack();
    if (!pack) return {pack: null};
    const pin = pinOf(v);
    if (pin) return {pack, hit: window.RSOffline.resolvePin(pack, pin), source: 'pin'};
    const key = s => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim()
      .replace(/ (district|dist|zila|zilla|jila)$/, '');
    for (const p of pack.packs || [pack]) {
      const d = p.districts.find(x => x && key(x) === key(v));
      if (d) return {pack, hit: window.RSOffline.districtCentre(p, d), source: 'district'};
    }
    return {pack, hit: null};
  } catch { return {pack: null}; }
}
function bindChange() {
  $('#back-gps').addEventListener('click', () => { location.hash = '#/gps'; });
  if (state.placeMsg) { state.placeMsg = ''; $('#place').focus(); }  // #134: straight to typing the place
  districtPicker();
  $('#place-form').addEventListener('submit', async e => {
    e.preventDefault();
    const v = $('#place').value.trim();
    $('#place-err').textContent = ''; $('#place-choices').innerHTML = '';
    const m = v.match(/^(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)$/);  // "26.59, 85.48" or "26.59 85.48"
    if (m && +m[1] >= 6 && +m[1] <= 37.5 && +m[2] >= 68 && +m[2] <= 97.5) {
      usePlace({lat: +m[1], lon: +m[2], label: null}, 'manual'); return;
    }
    if (m && !pinOf(v)) { placeErr(ts('place.coords_outside')); return; }  // coordinates, not in India (#134); "848 125" is a PIN
    if (!v) { placeErr(ts('place.empty')); return; }
    const online = await serverPlace(v);
    if (online && online.matches.length === 1) { usePlace(online.matches[0], PLACE_SOURCE[online.matches[0].kind] || 'place'); return; }
    if (online && online.matches.length > 1) { placeChoices(online.matches); return; }
    if (online) { placeErr(pinOf(v) ? ts('place.pin_missing', {v: pinOf(v)}) : ts('place.name_missing', {v})); return; }
    const {pack, hit, source} = await packHit(v);
    if (hit) { usePlace(hit, source); return; }
    const why = ts(navigator.onLine ? 'place.no_answer' : 'place.no_net');
    const saved = load('pack');
    placeErr(pack ? ts('place.not_saved', {why, v, st: saved ? saved.state : ''}) : ts('place.nothing_saved', {why}));
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
    $('#district-pick').innerHTML = `<label for="district">${th('place.district')}</label>
      <select id="district">${pack.districts.filter(Boolean).map(d => `<option>${esc(d)}</option>`).join('')}</select>
      <button type="button" class="btn btn-block" id="use-district">${th('place.use_district')}</button>`;
    $('#use-district').addEventListener('click', () => packPlace(p => p.district($('#district').value), 'district'));
  } catch { /* no saved pack */ }
}

// Faithfulness markers (spec 5.4, #30): every value shown from the plan carries its source path in data-f and a
// kind in data-k; app/tests/test_faithfulness.py checks each against the payload. Device-side text (the user's
// location, clock times, call outcomes) is wrapped in data-device instead.
function F(path, text, kind = 'text') { return `<span data-f="${path}" data-k="${kind}">${esc(text)}</span>`; }
const N = (path, v) => F(path, v, 'num');
// Model v2's p_lo / p_hi are the score bin's observed confirmed rate (derived/v2 field_descriptions), not an interval
// around p, so they are shown apart from p as a percent, never in brackets next to it (#121). Interim scores keep a range.
function similarHtml(o, P) {
  const pc = x => String(Math.round(100 * x));
  return o.range_kind === 'similar_scores'
    ? th('num.similar', {lo: F(P + '.p_lo', pc(o.p_lo), 'pct'), hi: F(P + '.p_hi', pc(o.p_hi), 'pct')})
    : th('num.range', {lo: N(P + '.p_lo', o.p_lo.toFixed(2)), hi: N(P + '.p_hi', o.p_hi.toFixed(2))});
}
// Three outcomes (#82 H2): no information is the most common result of a check, so it is shown, not hidden.
function trackHtml(tr, P) {
  if (!tr) return th('track.none');
  if (tr.n < 10) return th('track.few', {n: N(P + '.n', tr.n)});
  if (tr.k_no_info === null || tr.k_no_info === undefined) {
    return th('track.tenths', {k: F(P, Math.round(10 * tr.k_confirmed / tr.n), 'tenths'), n: N(P + '.n', tr.n)});
  }
  return th('track.full', {n: N(P + '.n', tr.n), basis: E(P + '.basis', tr.basis), k: N(P + '.k_confirmed', tr.k_confirmed),
    c: N(P + '.k_contradicted', tr.k_contradicted), u: N(P + '.k_no_info', tr.k_no_info)});
}
function trackBar(tr) {
  if (!tr || tr.n < 10 || tr.k_no_info == null) return '';
  const pct = v => (100 * v / tr.n).toFixed(1);
  return `<div class="track-bar" aria-hidden="true"><i class="tb-k" style="width:${pct(tr.k_confirmed)}%"></i><i class="tb-c" style="width:${pct(tr.k_contradicted)}%"></i><i class="tb-u" style="width:${pct(tr.k_no_info)}%"></i></div>
    <ul class="track-key" aria-hidden="true"><li><span class="sw tb-k"></span>${th('track.k')}</li><li><span class="sw tb-c"></span>${th('track.c')}</li><li><span class="sw tb-u"></span>${th('track.u')}</li></ul>`;
}
// Sealed TEST record of the Likely band (#86, #66): every number and hash from meta.test_record, which app/facts/build.py
// copies from model/gold/v3/test_eval/results.json.
function testRecordHtml(tr) {
  if (!tr) return '';
  const num = k => ['k', 'n', 'pct', 'lo_pct', 'hi_pct', 'public_n'].includes(k);
  const M = k => (num(k) ? F('meta.test_record.' + k, tr[k], 'num') : `<span lang="en">${F('meta.test_record.' + k, tr[k])}</span>`);
  return `<div class="test-record"><p class="note"><strong>${th('test.h')}</strong>: ${th('test.line', {k: M('k'), n: M('n'),
    pct: M('pct'), lo: M('lo_pct'), hi: M('hi_pct'), pub: M('public_n')})}</p>
    <details class="note"><summary>${th('test.hashes')}</summary>
      <p><a href="${esc(tr.log_url)}" rel="noopener noreferrer">${M('log')}</a>, ${th('test.opened', {when: `<span lang="en">${F('meta.test_record.opened', tr.opened)} UTC</span>`})}
      ${th('test.results')}: ${M('source')}.</p>
      <p>${th('test.model_version')} <code>${M('model_version')}</code><br>${th('test.pred_hash')}
        <code>${M('predictions_sha256')}</code><br>${th('test.label_hash')} <code>${M('labels_sha256')}</code></p>
    </details></div>`;
}
function methodHtml(t, P) { return F(P + '.method', ts(t.method === 'osrm' ? 'travel.road' : 'travel.rough'), 'method'); }
function travelHtml(t, P) {
  return th('travel.line', {km: N(P + '.km', Math.round(t.km)), low: N(P + '.low', t.low), high: N(P + '.high', t.high),
    method: methodHtml(t, P)});
}
// Band: a shape plus the word (never colour alone). NO SERVICE TEXT names the service (#118).
const SL = 'query.service_label';
function bandHtml(o, P) {
  const q = state.plan.query;
  if (o.model_band === 'NO_SERVICE_TEXT') {
    return `<span class="band band-${o.band}">${bandSvg(o.band)}<span>${th('band.no_text', {
      word: `<span data-f="${P}.model_band" data-k="band">${th('band.no_text_word')}</span>`,
      label: F(SL + '.' + labelLang(q), q.service_label[labelLang(q)])})}</span></span>`;
  }
  return `<span class="band band-${o.band}">${bandSvg(o.band)}<span data-f="${P}.band" data-k="band">${th('band.' + o.band)}</span></span>`;
}
const labelLang = q => (state.lang === 'hi' && q.service_label.hi ? 'hi' : 'en');
const labelF = (q = state.plan.query) => F(SL + '.' + labelLang(q), q.service_label[labelLang(q)]);
// Caption above the quotes of a NO SERVICE TEXT option: they are the listing's general lines, not about the service.
function noTextCaptionHtml(o, q) {
  if (o.model_band !== 'NO_SERVICE_TEXT' || !o.evidence.length) return '';
  return `<p class="note quote-caption">${th(q.service === 'trauma_emergency' ? 'quote.caption_trauma' : 'quote.caption', {label: labelF(q)})}</p>`;
}
// Data-quality warnings inside the citation (#86): from the claims pipeline and the source-page check.
function quoteFlagsHtml(e, P) {
  return (e.flags || []).map((f, j) => {
    const Q = `${P}.flags.${j}`;
    return `<span class="audit${f.weak ? ' audit-weak' : ''}">${icon('warn')} ${E(Q + '.text', f.text)}` +
      `${f.place ? `: ${F(Q + '.place', f.place)}` : ''}${f.km != null ? `, ${th('quote.km_away', {km: N(Q + '.km', f.km)})}` : ''}</span>`;
  }).join('');
}
// A quote's claim id stays in the page (marked, for the evidence ledger and the faithfulness test) but is not printed:
// "61731339:proc:3" means nothing to a family (#121).
function claimHtml(path, id) { return `<span hidden>${F(path, id)}</span>`; }
function quoteHtml(e, P) {
  return `<p lang="en">"${F(P + '.quote', e.quote)}"</p><p class="tags"><span class="tag">${E(P + '.field', e.field)}</span>` +
    `${claimHtml(P + '.claim_id', e.claim_id)}</p>${quoteFlagsHtml(e, P)}`;
}
// "Why not the nearest?" (#86): the nearest listings other than the first choice, each with one reason from the
// engine, plus the one phone call that would change the answer. Minutes are relative to the first choice.
function deltaHtml(path, v) {
  return F(path, v === 0 ? ts('delta.same') : ts(v < 0 ? 'delta.closer' : 'delta.farther', {n: Math.abs(v)}), 'delta');
}
function changeHtml(p) {
  const c = p.what_would_change;
  if (!c) return '';
  const d = deltaHtml('what_would_change.minutes_vs_first', c.minutes_vs_first);
  const line = c.kind === 'confirm_nearer'
    ? th('whynot.confirm_nearer', {name: `<span lang="en">${F('what_would_change.name', c.name)}</span>`, label: labelF(p.query), d})
    : th('whynot.first_says_no', {first: `<span lang="en">${F('what_would_change.first_name', c.first_name)}</span>`,
      name: `<span lang="en">${F('what_would_change.name', c.name)}</span>`, d});
  return `<p><strong>${th('whynot.change_h')}</strong> ${line}</p>`;
}
// The answer's first line when option 1 misses the service's time window (#86, lead's decision on the issue): say so,
// show 108/102, and the nearest hospital the public standard expects to offer the care, never as verified.
function windowHtml(p) {
  const w = p.time_window;
  if (!w || !w.first_outside || !p.options.length) return '';
  const po = p.public_option;
  // Kept short above the card (the sentence and one compact 108/102 row) so Call stays on screen on a 320x568 phone;
  // the public hospital goes under the card (windowBelowHtml).
  return `<section class="panel window-miss" aria-label="${th('window.label')}">
    <p><strong>${th('window.miss', {min: N('options.0.travel.minutes', p.options[0].travel.minutes), win: N('time_window.window_min', w.window_min)})}</strong></p>
    <div class="sos-inline">${sosCompact(has102(p.query.service))}</div>
  </section>`;
}
const sosCompact = with102 => `<a href="tel:108">${icon('phone')}<b>${th('sos.108_short')}</b></a>${with102
  ? ` <a href="tel:102">${icon('phone')}<b>${th('sos.102_short')}</b></a>` : ''}`;
function windowBelowHtml(p) {
  const w = p.time_window, po = p.public_option;
  if (!w || !w.first_outside || !p.options.length) return '';
  // On a narrow phone the sticky bar's 102 sub-line is clipped from view, so it is said here once, under the card.
  return `<p class="panel window-public">${po ? `${th('window.public', {name: `<strong lang="en">${F('public_option.name', po.name)}</strong>`, label: E('public_option.label', po.label)})}
    ${travelHtml(po.travel, 'public_option.travel')}.` : th('window.no_public')}</p>${has102(p.query.service) ? `<p class="note">${th('sos.102_sub')}</p> ` : ''}`;
}
function whyNotHtml(p) {
  const rows = p.why_not || [];
  if (!rows.length && !p.what_would_change) return '';
  const items = rows.map((w, k) => {
    const W = `why_not.${k}`;
    const where = w.minutes_vs_first != null ? ` (${deltaHtml(W + '.minutes_vs_first', w.minutes_vs_first)})` : '';
    return `<li><b lang="en">${F(W + '.name', w.name)}</b>${w.option_rank ? `, ${th('whynot.option', {n: N(W + '.option_rank', w.option_rank)})}` : ''}:
      ${N(W + '.travel.km', Math.round(w.travel.km))} ${th('unit.km')}${where}${th('punct.stop')} ${E(W + '.reason', w.reason)}${th('punct.stop')}</li>`;
  }).join('');
  // #121: when option 1 is already the nearest, say so; the rows are then farther places, not nearer alternatives.
  const nearest = p.first_is_nearest && p.options.length
    ? `<p class="why-not-nearest">${th('whynot.nearest', {label: labelF(p.query)})}${rows.length ? ' ' + th('whynot.below_farther') : ''}</p>` : '';
  return `<section class="section" aria-labelledby="why-not-h"><h2 id="why-not-h">${th('whynot.h')}</h2>
    ${nearest}${items ? `<ul class="rows why-not">${items}</ul>` : ''}${changeHtml(p)}
    <p class="note">${th('whynot.about_data')}</p></section>`;
}
// Field reports (community/field.py): the server's dated lines, in the app language, shown verbatim and marked.
function fieldHtml(o, P) {
  const f = o.field;
  if (!f || !(f.lines.length || f.notes.length)) return '';
  const l = state.lang === 'hi' ? 'hi' : 'en';
  const one = (x, Q) => `<p class="note">${F(Q + '.' + l, x[l])}</p>`;
  return `<div class="field-reports${f.disagree ? ' disagree' : ''}"><p class="note"><strong>${th('field.h')}</strong></p>
    ${f.lines.map((x, j) => one(x, `${P}.field.lines.${j}`)).join('')}
    ${f.notes.map((x, j) => one(x, `${P}.field.notes.${j}`)).join('')}</div>`;
}
// Tie-break from health-worker reports (#86): one named row on the why page of each tied option.
function tieHtml(p, o) {
  const t = p.tie_break, T = 'tie_break';
  if (!t || !t.options.some(x => x.facility_id === o.facility_id)) return '';
  const each = t.options.map((x, j) => {
    const i = p.options.findIndex(y => y.facility_id === x.facility_id), Q = `${T}.options.${j}`;
    return `${N(`options.${i}.rank`, p.options[i].rank)}. ${F(`options.${i}.name`, p.options[i].name)}: ` +
      (x.net === null ? th('tie.few', {n: N(T + '.min_reporters', t.min_reporters)})
        : th('tie.net', {net: N(Q + '.net', x.net.toFixed(2)), n: N(Q + '.n_reporters', x.n_reporters)}));
  }).join('; ');
  return `<table class="ledger tie-break"><caption>${th('tie.caption')}</caption><tbody><tr>
    <th scope="row">${F(T + '.label', t.label)}</th><td>${th('tie.rule', {p: N(T + '.p_within', t.p_within.toFixed(2)),
      m: N(T + '.minutes_within', t.minutes_within)})} ${each}.</td></tr></tbody></table>`;
}
const RECENT = () => (load('recent') || []).filter(r => r && !r.reported && Date.now() - r.at < 7 * 864e5);
// Lead's rule on #42: when the nearest verified option is far and nearer ones are not verified, say so up front.
function farVerifiedNote(p) {
  const opts = p.options;
  if (!opts.length || opts[0].band === 'likely') return '';
  const likely = opts.filter(o => o.band === 'likely').sort((a, b) => a.travel.minutes - b.travel.minutes)[0];
  if (!likely) return '';
  const nearer = opts.filter(o => o.band !== 'likely' && o.travel.minutes < likely.travel.minutes);
  if (!nearer.length) return '';
  const k = opts.indexOf(likely);
  const r = o => N(`options.${opts.indexOf(o)}.rank`, o.rank);
  return `<p class="panel"><strong>${th('far.line', {label: labelF(p.query), km: N(`options.${k}.travel.km`, Math.round(likely.travel.km)), rank: r(likely)})}</strong>
    ${th(nearer.length === 1 ? 'far.one' : 'far.many', {ranks: nearer.map(r).join(', ')})}</p>`;
}

// ---------- Multi-stop route (#47): in /route.js, loaded with the plan request (off the first-paint bytes) ----------
const routeOrNone = p => (typeof routeHtml === 'function' ? routeHtml(p) : '');

// ---------- the answer (S3): one readout, then the next two, then the route ----------
// A listed website flagged by the facts build (#136): its label, and why it is unreliable, in the app language.
function websiteHtml(o, P) {
  const w = o.website, l = state.lang === 'hi' && o.website && o.website.label.hi ? 'hi' : 'en';
  if (!w) return '';
  return `<p class="note site-line">${F(`${P}.website.label.${l}`, w.label[l])}${w.reason_line
    ? `<br>${F(`${P}.website.reason_line.${l}`, w.reason_line[l])}` : ''}</p>`;
}
function telOf(o) { return o.phone && o.phone.e164 ? `tel:${esc(o.phone.e164)}` : null; }
function opLabel(o) { return o.operator === 'private' ? th('op.private') : o.operator === 'public' ? th('op.public') : ''; }
function sureHtml(o, P) {
  const key = o.model_band === 'NO_SERVICE_TEXT' ? 'no_text' : o.band;
  const cls = o.band === 'likely' ? 'sure-ok' : o.band === 'unlikely' ? 'sure-no' : 'sure-nv';
  // NO SERVICE TEXT: the chip already says "call to ask", so no second line (keeps Call above the fold)
  return `<p class="sure ${cls}">${bandHtml(o, P)}${key === 'no_text' ? '' : `<span>${th('sure.' + key)}</span>`}</p>`;
}
// WS1 1d: the map point may be wrong (engine location_doubt, #147). Say so in amber with the listing's address and,
// when the engine has it, the time from the PIN centre (travel.alt), so the worker asks the way on the call.
// A no-op on payloads without the field.
function doubtHtml(o, P) {
  if (!o.location_doubt) return '';
  const alt = o.travel && o.travel.alt;
  return `<p class="doubt">${icon('warn')}<span>${th('ans.doubt.line', {address: `<span lang="en">${F(P + '.address', o.address || o.town)}</span>`})}${
    alt ? ' ' + th('ans.doubt.alt', {low: N(P + '.travel.alt.low', alt.low), high: N(P + '.travel.alt.high', alt.high)}) : ''} ${th('ans.doubt.ask')}</span></p>`;
}
// WS1 1b, the receipt: the first listing sentence, cut at 60 characters (kind 'part': the shown text is a piece of
// the stored quote), in English as written, with its source page. A NO SERVICE TEXT option says its lines are general.
const RECEIPT_CUT = 60;
// Which quote: the first one with no weak flag whose field is not a generic description; else the first, shown with
// its warning (#171 review). The cut ends at a word: the last space at or before 60 characters.
function receiptQuote(o) {
  const ok = e => !(e.flags || []).some(f => f.weak) && e.field !== 'description';
  const j = o.evidence.findIndex(ok);
  return j >= 0 ? j : 0;
}
function cutAtWord(q) {
  if (q.length <= RECEIPT_CUT) return q;
  const sp = q.lastIndexOf(' ', RECEIPT_CUT);
  return (sp > 0 ? q.slice(0, sp) : q.slice(0, RECEIPT_CUT)).trimEnd();
}
function receiptHtml(p, o, P) {
  if (!o.evidence.length) return '';
  const j = receiptQuote(o), e = o.evidence[j];
  const Q = `${P}.evidence.${j}`;
  const cut = cutAtWord(e.quote);
  const lead = o.model_band === 'NO_SERVICE_TEXT'
    ? th(p.query.service === 'trauma_emergency' ? 'quote.caption_trauma' : 'quote.caption', {label: labelF(p.query)})
    : th('ans.receipt.from');
  return `<p class="receipt">${lead}: <span lang="en">"${F(Q + '.quote', cut, 'part')}${cut.length < e.quote.length ? '...' : ''}"</span>${
    claimHtml(Q + '.claim_id', e.claim_id)}${e.source_url
    ? ` <a href="${esc(e.source_url)}" rel="noopener noreferrer">${th('ans.receipt.source')}</a>` : ''}${quoteFlagsHtml(e, Q)}</p>`;
}
// WS1 1b, why this one first, in one line: nearest-first emergencies name the Likely option they put second and how
// much farther it is; planned care names the two ledger rows that add most; otherwise the engine's rank rule.
function whyFirstHtml(p, o, P) {
  const two = p.options[1], rule = p.rank_rule || {};
  if (rule.code === 'nearest_plausible' && two && two.band === 'likely' && o.band !== 'likely') {
    const k = (p.why_not || []).findIndex(w => w.facility_id === two.facility_id && w.minutes_vs_first > 0);
    if (k >= 0) {
      const W = `why_not.${k}`, name = `<span lang="en">${F(W + '.name', p.why_not[k].name)}</span>`;
      return `<p class="why-first">${th('ans.why_first.nearest', {name, n: N(W + '.minutes_vs_first', p.why_not[k].minutes_vs_first)})}</p>`;
    }
  }
  if (p.profile === 'planned' || p.profile === 'scheduled') {
    const top = o.contributions.map((c, j) => [c, j]).filter(([c]) => c.family && c.family !== 'base' && c.points > 0)
      .sort((a, b) => b[0].points - a[0].points).slice(0, 2)
      .map(([c, j]) => `${rowLabel(c, `${P}.contributions.${j}`)} (${F(`${P}.contributions.${j}.points`, signed(c.points), 'num')})`);
    if (top.length) return `<p class="why-first">${th('ans.why_first.rows', {rows: top.join('; ')})}</p>`;
  }
  return rule.text ? `<p class="why-first">${th('ans.why_first.rule', {rule: E('rank_rule.text', rule.text)})}</p>` : '';
}
function answerPanel(p, o, i, describedBy = '') {
  const P = `options.${i}`, tr = o.travel, tel = telOf(o);
  const fb = p.itinerary && p.itinerary.fallback;  // the route only if card 1 cannot treat (#126)
  return `<article class="card answer${o.band === 'likely' ? ' likely' : ''}" aria-labelledby="opt-${o.rank}"${describedBy ? ` aria-describedby="${describedBy}"` : ''}>
    <h2 class="kicker">${th(o.call_first || i === 0 ? 'ans.call_first' : 'ans.option', {n: N(P + '.rank', o.rank)})}</h2>
    <h3 id="opt-${o.rank}" class="name" lang="en">${F(P + '.name', o.name)}</h3>
    <p class="place"><span lang="en">${F(P + '.town', o.town)}</span>${opLabel(o) ? th('punct.stop') + ' ' + opLabel(o) : ''}</p>
    ${o.route_reason ? `<p class="note">${E(P + '.route_reason', o.route_reason)}</p>` : ''}
    ${websiteHtml(o, P)}
    ${i === 0 && fb ? `<p class="note"><strong>${E('itinerary.fallback.ask', fb.ask)}</strong> ${E('itinerary.fallback.text', fb.text)}</p>` : ''}
    <p class="readout"><span class="big">${N(P + '.travel.minutes', tr.minutes)}</span><span class="unit">${th('unit.min')}</span>
      <span class="sub">${travelHtml(tr, P + '.travel')}</span></p>
    ${doubtHtml(o, P)}
    ${sureHtml(o, P)}
    ${receiptHtml(p, o, P)}
    ${i === 0 ? whyFirstHtml(p, o, P) : ''}
    ${tel ? `<a class="btn btn-go btn-block btn-big call-main" href="${tel}">${icon('phone')} ${th('ans.call')} <span class="num">${F(P + '.phone.display', o.phone.display || o.phone.e164)}</span></a>
      <p class="note call-note">${th('call.number_note')}</p>`
      : `<p class="note">${th('ans.no_phone')}</p>`}
    ${askLineHtml(o, P)}
    ${i ? '' : `<div id="call-loop">${window.RSCommunity?.callLoopHtml(p) || ''}</div>`}
    <div class="pair">${RSInput.speakHtml()}<a class="btn" href="#/why/${o.rank}">${th('ans.why')}<span class="visually-hidden"> ${F(P + '.name', o.name)}</span></a></div>
    <p id="speak-note" class="note" aria-live="polite"></p>
  </article>`;
}
const askLineHtml = (o, P) => (o.call_ahead.length ? `<p class="note ask-line"><strong>${th('call.ask')}</strong> ${E(P + '.call_ahead.0.question', o.call_ahead[0].question)}</p>` : '');
document.addEventListener('click', e => {
  if (location.hash === '#/plan' && e.target.closest('a[href^="tel:"],[data-call-out]')) loadScript('/community.js', 'RSCommunity').then(() => RSCommunity.onCall(e.target)).catch(() => {});
});
function nextRows(p, from) {
  const rows = p.options.slice(from).map((o, j) => {
    const i = j + from, P = `options.${i}`, tel = telOf(o);
    return `<li class="next-row"><span class="rank">${N(P + '.rank', o.rank)}</span>
      <a class="nm" href="#/why/${o.rank}"><b lang="en">${F(P + '.name', o.name)}</b>
        <span>${th('ans.eta', {low: N(P + '.travel.low', o.travel.low), high: N(P + '.travel.high', o.travel.high)})}, ${bandHtml(o, P)}</span>${websiteHtml(o, P)}</a>
      ${tel ? `<a class="btn btn-go-line call" href="${tel}" aria-label="${esc(ts('ans.call_name', {name: o.name}))}">${icon('phone')}</a>` : ''}</li>`;
  }).join('');
  return rows ? `<section class="section" aria-labelledby="h-no"><h2 id="h-no">${th('ans.if_no')}</h2><ol class="rows">${rows}</ol></section>` : '';
}
function planScreen() {
  const s = svc(state.service);
  if (!s || !state.loc) return home();
  const p = state.plan;
  if (p && p.offline) return offlineScreen(s);
  const head = `<h1 tabindex="-1">${esc(s.label)}</h1><p class="note loc-line" data-device>${locLine(state.loc)}</p>`;
  if (!p) return head + `<p class="section">${th('ans.finding')}</p>`;
  if (p.error) return head + `<p class="panel section" role="alert">${esc(p.error)}</p><a class="btn btn-block" href="#/">${th('nav.back')}</a>`;
  const depth = state.depth || 'quick';
  const foot = `<p class="note section">${th('ans.as_of', {date: F('as_of', p.as_of)})} ${th('ans.not_advice')}
      ${p.meta.stub ? th('ans.stub') : ''}</p>
    ${p.field_reports && p.field_reports.note ? `<p class="note">${F('field_reports.note.' + (state.lang === 'hi' ? 'hi' : 'en'), p.field_reports.note[state.lang === 'hi' ? 'hi' : 'en'])}</p>` : ''}
    <div class="pair section"><button type="button" class="btn" data-depth="${depth === 'compare' ? 'quick' : 'compare'}">${th(depth === 'compare' ? 'ans.back_answer' : 'ans.compare')}</button>
      <a class="btn" href="#/">${th('ans.new')}</a></div>`;
  state.speak = {danger: isEmergency()};  // read aloud: options, route and questions, from p only
  if (depth === 'compare') return head + compareHtml(p) + foot;
  let body;
  if (p.abstain) {
    const oo = p.abstain.outside_option;
    // With a window-miss panel above as well, the "none confirmed" notice goes under the card, so Call stays on
    // screen on a 320x568 phone (the window line stays the answer's first line).
    // The card is described by the notice (aria-describedby), so a screen reader hears it with the card and its Call.
    const notice = `<p class="panel section" id="abstain-note"><strong>${E('abstain.text', p.abstain.text)}</strong></p>`, low = !!windowHtml(p);
    body = `${low ? '' : notice}
      ${p.options.length ? `<div class="section">${answerPanel(p, p.options[0], 0, low ? 'abstain-note' : '')}</div>` : ''}${low ? notice : ''}${windowBelowHtml(p)}${nextRows(p, 1)}
      ${oo && !windowHtml(p) ? `<article class="panel section"><h3 lang="en">${F('abstain.outside_option.name', oo.name)}</h3>
        ${oo.label ? `<p class="note"><strong>${E('abstain.outside_option.label', oo.label)}</strong></p>` : ''}
        <p>${E('abstain.outside_option.text', oo.text)}</p>
        <p>${travelHtml(oo.travel, 'abstain.outside_option.travel')}</p></article>` : ''}${routeOrNone(p)}`;
    if (!p.options.length) body = body + `<p class="note">${RSInput.speakHtml()}</p><p id="speak-note" class="note" aria-live="polite"></p>`;
  } else {
    // The readout first, so Call is above the fold on small phones; the far-verified note qualifies it right under it.
    body = (p.options.length ? `<div class="section">${answerPanel(p, p.options[0], 0)}</div>` : '') + windowBelowHtml(p) + farVerifiedNote(p) + nextRows(p, 1) + routeOrNone(p);
  }
  return head + windowHtml(p) + body + foot;
}

// ---------- Compare depth (S10): same rows for every option; table on desk, cards on phone ----------
const COMPARE_ROWS = [
  ['cmp.band', (o, P) => bandHtml(o, P)],
  ['cmp.offers', (o, P) => o.model_band === 'NO_SERVICE_TEXT' ? th('cmp.no_sentence') : `${th('num.score')} ${N(P + '.p', o.p.toFixed(2))}; ${similarHtml(o, P)}`],
  ['cmp.track', (o, P) => o.track_record ? th('cmp.track_line', {k: N(P + '.track_record.k_confirmed', o.track_record.k_confirmed), n: N(P + '.track_record.n', o.track_record.n)}) : th('track.none')],
  ['cmp.exists', (o, P) => `${N(P + '.p_e', o.p_e.toFixed(2))} / ${N(P + '.p_l', o.p_l.toFixed(2))}`],
  ['cmp.road', (o, P) => `${N(P + '.travel.km', Math.round(o.travel.km))}, ${N(P + '.travel.low', o.travel.low)}-${N(P + '.travel.high', o.travel.high)}`],
  ['cmp.quote', (o, P) => o.evidence.length ? noTextCaptionHtml(o, state.plan.query) + quoteHtml(o.evidence[0], P + '.evidence.0') : th('cmp.none_data')],
  ['cmp.warnings', (o, P) => o.flags.length ? o.flags.map((f, j) => E(`${P}.flags.${j}`, f)).join('; ') : th('cmp.none')],
  ['cmp.phone', (o, P) => !o.phone || !o.phone.e164 ? th('cmp.no_number')
    : o.phone.shared_listings > 1 ? th('cmp.shared', {n: N(P + '.phone.shared_listings', o.phone.shared_listings)}) : th('cmp.not_shared')],
  ['cmp.operator', (o, P) => F(P + '.operator', o.operator)],
  ['cmp.ask', (o, P) => o.call_ahead.length ? E(P + '.call_ahead.0.question', o.call_ahead[0].question) : '-'],
  ['cmp.result', o => { const r = (state.outcomes || {})[o.rank]; return r ? `<span data-device>${th('why.out.' + r.said)} ${timeStr(r.at)}</span>` : '-'; }],
];
function compareHtml(p) {
  if (state.patientHere == null) {
    return `<fieldset class="panel section"><legend>${th('cmp.here_q')}</legend>
      <label class="check"><input type="radio" name="here" value="yes"> ${th('cmp.yes')}</label>
      <label class="check"><input type="radio" name="here" value="no"> ${th('cmp.no')}</label></fieldset>
      <p class="note">${th('cmp.choose')}</p>`;
  }
  const opts = p.options;
  const P = i => `options.${i}`;
  // #140 3e: band counts, not "chance at least one checks out" (a product of model scores that assumed
  // independent failures). Each number is marked: k counts Likely options, n counts options.
  const nLikely = opts.filter(o => o.band === 'likely').length;
  const names = opts.map((o, i) => F(P(i) + '.name', o.name)).join(', ');
  const head = `<p class="section">${th(state.patientHere ? 'cmp.here' : 'cmp.elsewhere')}</p>
    <p>${th('cmp.plan', {names})}</p>
    ${opts.length ? `<p>${th('cmp.likely_count', {k: F('options', nLikely, 'likely'), n: F('options', opts.length, 'count')})}</p>` : ''}`;
  const table = `<div class="compare-table table-scroll" tabindex="0" role="region" aria-label="${th('cmp.h')}"><table class="ledger"><caption>${th('cmp.caption', {label: labelF(p.query)})}</caption>
    <thead><tr><th scope="col">${th('cmp.row')}</th>${opts.map((o, i) => `<th scope="col">${N(P(i) + '.rank', o.rank)}. ${F(P(i) + '.name', o.name)}</th>`).join('')}</tr></thead>
    <tbody>${COMPARE_ROWS.map(([lab, fn]) => `<tr><th scope="row">${th(lab)}</th>${opts.map((o, i) => `<td>${fn(o, P(i))}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
  const cards = `<div class="compare-cards">${opts.map((o, i) => `<article class="panel" aria-labelledby="cmp-${o.rank}">
    <h3 id="cmp-${o.rank}">${N(P(i) + '.rank', o.rank)}. <span lang="en">${F(P(i) + '.name', o.name)}</span></h3>
    <dl class="facts">${COMPARE_ROWS.map(([lab, fn]) => `<div><dt>${th(lab)}</dt><dd>${fn(o, P(i))}</dd></div>`).join('')}</dl>
    <a class="btn btn-block" href="#/why/${o.rank}">${th('ans.why')}<span class="visually-hidden"> ${F(P(i) + '.name', o.name)}</span></a></article>`).join('')}</div>`;
  const why = opts[0] && opts[0].why_first_text ? `<p><strong>${th('cmp.why_first')}</strong> ${E(P(0) + '.why_first_text', opts[0].why_first_text)}</p>` : '';
  return head + `<h2 class="section">${th('cmp.h')}</h2>` + table + cards + why;
}

// ---------- Area (S11 standing plan, S12 ten calls); data from POST /api/area; the bottom-nav "Area" tab ----------
// Data gap vs care gap (#86): "no listing claims it" means we cannot tell; "claimed but not confirmed / far" is care.
function gapHtml(a) {
  const g = a.gap;
  if (!g) return '';
  const G = k => N('area.gap.' + k, g[k]);
  const W = N('area.area.window_min', a.area.window_min);
  const L = F('area.query.service_label.' + labelLang(a.query), a.query.service_label[labelLang(a.query)]);
  const allCare = g.pins_sampled > 0 && g.covered === 0 && g.no_claim === 0;
  return `<h3 class="section">${th('area.gap_h')}</h3>
    ${allCare ? `<p class="panel">${th('area.all_care', {n: G('pins_sampled'), w: W})}</p>` : ''}
    ${emergencyNumbers(a)}
    <p>${th('area.claiming', {n: G('district_claiming'), district: F('area.area.district', a.area.district), label: L, k: G('district_confirmed')})}
      ${th('area.other_districts')}</p>
    <ul class="gap">
      <li>${th('area.covered', {n: G('covered'), w: W})}</li>
      <li>${th('area.not_confirmed', {n: G('not_confirmed'), w: W})}</li>
      <li>${th('area.far', {n: G('far'), w: W})}</li>
      <li>${th('area.no_claim', {n: G('no_claim'), r: G('radius_km')})}</li>
    </ul>
    <p class="note">${th('area.sample', {n: G('pins_sampled'), of: G('pins_in_district')})}</p>
    ${publicHtml(a)}`;
}
// Emergency care with no confirmed option in reach: the area plan says what to do until the gap closes (#86 item 3).
function emergencyNumbers(a) {
  const s = svc(a.query.service);
  if (!s || !(s.profile === 'emergency' || s.profile === 'urgent') || a.summary.n_without_option === 0) return '';
  return `<p>${th(has102(s.key) ? 'area.until_102' : 'area.until')}</p>`;
}
// Where the area shows no public evidence, name the hospitals the public standard expects to offer acute care (#86).
function publicHtml(a) {
  const ps = a.gap.public_standard;
  if (!ps || !(a.summary.n_without_option > 0 || a.summary.no_public_evidence > 0)) return '';
  if (!ps.length) {
    const g = a.gap, D = F('area.area.district', a.area.district), pn = g.public_nearest;
    return `<p>${th('area.public_none', {district: D, n: N('area.gap.district_listings', g.district_listings)})}</p>
      <p>${pn ? th('area.public_nearest', {name: F('area.gap.public_nearest.name', pn.name), label: E('area.gap.public_nearest.label', pn.label),
        km: N('area.gap.public_nearest.km', pn.km)}) : th('area.public_far', {r: N('area.gap.radius_km', g.radius_km)})}</p>`;
  }
  return `<p>${th('area.public_list', {district: F('area.area.district', a.area.district)})}</p>
    <ul class="gap">${ps.map((h, k) => `<li>${F(`area.gap.public_standard.${k}.name`, h.name)}
      (${E(`area.gap.public_standard.${k}.label`, h.label)})</li>`).join('')}</ul>`;
}
function areaHtml(a) {
  if (!a || a.loading) return `<p>${th('area.loading')}</p>`;
  if (a.error) return `<p class="panel" role="alert">${esc(a.error)}</p>`;
  const S = a.summary;
  const n = x => N('area.' + x, (x.split('.').reduce((o, k) => o[k], a)).toFixed(2));
  const W = N('area.area.window_min', a.area.window_min);
  const rows = a.pins.map((r, i) => {
    const R = `area.pins.${i}`;
    return r.first
      ? `<tr><th scope="row">${N(R + '.pin', r.pin)}</th><td>${F(R + '.first.name', r.first.name)}</td>
          <td>${r.backup ? F(R + '.backup.name', r.backup.name) : th('area.none')}</td>
          <td>${N(R + '.travel.low', r.travel.low)}-${N(R + '.travel.high', r.travel.high)}</td></tr>`
      : `<tr><th scope="row">${N(R + '.pin', r.pin)}</th><td colspan="3">${icon('warn')}
          ${th('area.pin_none', {w: W})}
          ${r.nearest_km != null ? th('area.nearest', {km: N(R + '.nearest_km', r.nearest_km)}) : th('area.none_sentence')}${r.public ? `.<br>${th('area.public_row', {
            name: F(R + '.public.name', r.public.name), label: E(R + '.public.label', r.public.label), km: N(R + '.public.km', r.public.km)})}` : ''}</td></tr>`;
  }).join('');
  const calls = a.ten_calls.map((c, i) => {
    const C = `area.ten_calls.${i}`;
    return `<tr><th scope="row">${N(C + '.rank', c.rank)}</th><td>${F(C + '.name', c.name)}</td>
      <td>${F(C + '.phone_kind', c.phone_kind)}</td><td class="num">${N(C + '.areas', c.areas)}</td>
      <td class="num">+${N(C + '.access_gain', c.access_gain.toFixed(3))}</td></tr>`;
  }).join('');
  const csv = [['pin', 'first_choice', 'backup', 'min_low', 'min_high', 'call_first', 'nearest_km_if_none']]
    .concat(a.pins.map(r => [r.pin, r.first ? r.first.name : '', r.backup ? r.backup.name : '', r.travel ? r.travel.low : '',
      r.travel ? r.travel.high : '', r.call_first || '', r.nearest_km ?? '']))
    .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  const L = F('area.query.service_label.' + labelLang(a.query), a.query.service_label[labelLang(a.query)]);
  return `<h2>${th('area.plan_h', {label: L})}</h2>
    <p>${F('area.area.district', a.area.district)}, ${F('area.area.state', a.area.state)}. ${th('area.n_pins', {n: N('area.summary.n_pins', S.n_pins)})}</p>
    <p><strong>${th('area.without', {k: N('area.summary.n_without_option', S.n_without_option), n: N('area.summary.n_pins', S.n_pins), w: W})}</strong></p>
    ${briefHtml(a, W)}
    <div class="table-scroll" tabindex="0" role="region" aria-label="${th('area.access_caption_short')}"><table class="ledger"><caption>${th('area.access_caption', {label: L, w: W})}</caption><tbody>
      <tr><th scope="row">${th('area.row_now')}</th><td class="num">${n('summary.access_now')}</td></tr>
      <tr><th scope="row">${th('area.row_confirmed')}</th><td class="num">${n('summary.access_if_confirmed')}</td></tr>
      <tr><th scope="row">${th('area.row_close')}</th><td class="num">${n('summary.calls_could_close')}</td></tr>
      <tr><th scope="row">${th('area.row_none')}</th><td class="num">${n('summary.no_public_evidence')}</td></tr>
    </tbody></table></div>
    <p>${E('area.caveat', a.caveat)}</p>
    ${gapHtml(a)}
    <div class="table-scroll section" tabindex="0" role="region" aria-label="${th('area.pins_caption')}"><table class="ledger"><caption>${th('area.pins_caption')}</caption>
      <thead><tr><th scope="col">PIN</th><th scope="col">${th('area.col_first')}</th><th scope="col">${th('area.col_backup')}</th><th scope="col">${th('area.col_min')}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <h2 id="ten-calls" class="section">${th('area.calls_h')}</h2>
    ${calls ? `<div class="table-scroll" tabindex="0" role="region" aria-label="${th('area.calls_h')}"><table class="ledger"><caption>${th('area.calls_caption')}</caption>
      <thead><tr><th scope="col">#</th><th scope="col">${th('area.col_facility')}</th><th scope="col">${th('area.col_phone')}</th><th scope="col" class="num">${th('area.col_areas')}</th><th scope="col" class="num">${th('area.col_gain')}</th></tr></thead>
      <tbody>${calls}</tbody></table></div>` : `<p>${th('area.no_calls')}</p>`}
    <div class="pair section"><a class="btn" download="area_plan.csv" href="data:text/csv;charset=utf-8,${encodeURIComponent(csv)}">${th('area.csv')}</a>
      <button type="button" class="btn" id="area-print">${th('area.print')}</button></div>
    ${a.meta && a.meta.stub ? `<p class="note">${th('area.stub')}</p>` : ''}`;
}
// WS4 4b: the district brief. People and listings per million against India's; for birth care the NFHS-5 rates, a
// district survey estimate and not facility data; the government lists for this care; the one call that would change
// the most, or why there is none; and where each number comes from. Every number is a payload value.
function briefHtml(a, W) {
  const nd = a.area.need, gov = a.area.gov_list || [], h = a.headline, D = 'area.area.need';
  const svcKey = a.query.service, lines = [], src = [];
  const en = html => `<span lang="en">${html}</span>`;  // names and source credits are English in both languages
  if (nd) {
    lines.push(th('area.need.people', {people: N(D + '.population', nd.population.toLocaleString('en-IN')),
      district: F(D + '.lgd_district', nd.lgd_district)}));
    lines.push(th('area.need.listings', {n: N(D + '.listings', nd.listings),
      per_m: N(D + '.listings_per_million', nd.listings_per_million), india: N(D + '.india_per_million', nd.india_per_million)}));
    src.push(en(F(D + '.source.people', nd.source.people)), en(F(D + '.source.listings', nd.source.listings)));
    if (has102(svcKey) && nd.csection_pct != null) {
      const parts = [th('area.need.cs', {cs: N(D + '.csection_pct', nd.csection_pct)})];
      const pub = nd.public_csection_pct, priv = nd.private_csection_pct;  // NFHS-5 suppresses small samples: null
      const pv = {pub: N(D + '.public_csection_pct', pub), priv: N(D + '.private_csection_pct', priv)};
      if (pub != null || priv != null) parts.push(th(priv == null ? 'area.need.cs_public' : pub == null ? 'area.need.cs_private' : 'area.need.cs_split', pv));
      if (nd.institutional_pct != null) parts.push(th('area.need.inst', {inst: N(D + '.institutional_pct', nd.institutional_pct)}));
      lines.push(`${th('area.need.nfhs', {district: F(D + '.nfhs_district', nd.nfhs_district)})} ${parts.join(' ')}`);
      src.push(en(F(D + '.source.nfhs', nd.source.nfhs)));
    }
  }
  const govLines = gov.map((g, j) => {
    const G = `area.area.gov_list.${j}`;
    if (g.list === 'pmndp') {
      return th('area.gov.pmndp', {centres: N(G + '.centres', g.centres), working: N(G + '.districts_working', g.districts_working),
        total: N(G + '.districts_total', g.districts_total), state: F('area.area.state', a.area.state)});
    }
    const status = g.status && g.status !== 'Certified' ? ` (${F(G + '.status', g.status)})` : '';
    return th(g.expired ? 'area.gov.laqshya_expired' : 'area.gov.laqshya', {name: en(F(G + '.name', g.name)),
      date: F(G + '.valid_to', g.valid_to)}) + status;
  });
  [...new Set(gov.map(g => g.source))].forEach(x => src.push(en(F(`area.area.gov_list.${gov.findIndex(g => g.source === x)}.source`, x))));
  const govHtml = govLines.length ? `<ul>${govLines.map(x => `<li>${x}</li>`).join('')}</ul>`
    : svcKey === 'emergency_csection' ? `<p>${th('area.gov.none')}</p>` : '';
  const head = !h ? '' : h.kind === 'if_confirms' && a.ten_calls.length
    ? th('area.need.headline', {name: en(F('area.ten_calls.0.name', a.ten_calls[0].name)), k: N('area.headline.k', h.k),
      n: N('area.headline.n', h.n), now: N('area.headline.now', h.now), w: N('area.headline.window_min', h.window_min)})
    : th(h.kind === 'all_covered' ? 'area.need.headline_all' : 'area.need.headline_none',
      {n: N('area.headline.n', h.n), w: N('area.headline.window_min', h.window_min)});
  if (!lines.length && !govHtml && !head) return '';
  return `<section id="area-brief" class="section" aria-labelledby="h-brief"><h2 id="h-brief">${th('area.need.h')}</h2>
    ${lines.map(x => `<p>${x}</p>`).join('')}
    ${govHtml ? `<h3>${th('area.gov.h')}</h3>${govHtml}` : ''}
    ${head ? `<p><strong>${head}</strong></p>` : ''}
    ${src.length ? `<p class="note">${th('area.need.sources', {list: src.join('; ')})}</p>` : ''}</section>`;
}
function areaScreen() {
  const s = svc(state.service);
  const plan = s && s.profile && state.loc
    ? `<p class="note" data-device>${esc(s.label)}. ${locLine(state.loc)}</p>${areaHtml(state.area)}`
    : `<p class="panel">${th('area.pick_first')}</p>`;
  return `<h1 tabindex="-1">${th('area.h')}</h1>${plan}
    <a class="btn btn-block section" href="#/pulse">${th('area.pulse_link')}</a>`;
}
function bindArea() {
  $('#area-print')?.addEventListener('click', () => window.print());
  const s = svc(state.service);
  if (s && s.profile && state.loc && !state.area) loadArea();
}

// /api/plan 422 with a location code (#134, BE-T2): say what is wrong in the app language (the server's text, or ours)
// and open Change location with the box focused. Never the generic "could not make a plan" for these.
const LOCATION_CODES = {location_outside_india: 'place.outside_india', location_too_coarse: 'place.too_coarse'};
async function badLocation(r) {
  let body = null;
  try { body = await r.clone().json(); } catch { return false; }
  const key = body && LOCATION_CODES[body.code];
  if (!key) return false;
  const l = state.lang === 'hi' ? 'hi' : 'en';
  const pick = x => (x && typeof x === 'object' ? x[l] : null);
  state.placeMsg = pick(body.text) || pick(body.message) || (typeof body[l] === 'string' ? body[l] : null) || ts(key);
  announce(state.placeMsg);
  location.hash = '#/change';
  return true;
}
let planReq = null;  // the /api/plan request in flight: a reply that is no longer for this screen is dropped (#140 B1)
async function bindPlan() {
  $('#retry')?.addEventListener('click', () => { state.plan = null; render(); });
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
  if (!state.service || !state.loc || state.plan) return;
  const l = state.loc, key = [state.service, l.lat, l.lon, l.source].join('|');
  if (planReq && planReq.key === key) return;  // a re-render while it loads does not ask twice
  const req = planReq = {key};
  // Live: still the newest request, still on the answer screen, same service and place, nothing shown yet.
  // A reply for a screen that is gone (Back, Change place, another service) is dropped, not drawn over it.
  const live = () => planReq === req && location.hash === '#/plan' && !state.plan && !!state.loc
    && [state.service, state.loc.lat, state.loc.lon, state.loc.source].join('|') === key;
  const done = () => { if (planReq === req) planReq = null; };
  // Offline per spec 3.2.3: navigator.onLine false, a failed /api call, or one slower than 8 s.
  if (!navigator.onLine) { if (await offlinePlan('off.no_net', live)) render(); done(); return; }
  // Rounded to 0.01 deg on the phone too; the point goes in the body, never the URL.
  const body = {service: state.service, lat: +l.lat.toFixed(2), lon: +l.lon.toFixed(2), accuracy_m: l.accuracy_m,
    source: l.source, depth: 'quick'};
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  needScripts(['/route.js']).catch(() => {});  // fetched alongside the plan; render() re-renders when it arrives
  try {
    const r = await fetch('/api/plan', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body), redirect: 'manual', signal: ctl.signal});
    if (!live()) return;
    if (r.type === 'opaqueredirect') {
      if (!await offlinePlan('off.signed_out', live)) return;
    } else if (r.status >= 500) {
      if (!await offlinePlan('off.server_down', live)) return;
    } else if (r.status === 422 && await badLocation(r)) {
      return;  // #134: the phone's point is outside India or too rough; typing the place is the way on
    } else if (!r.ok) {
      state.plan = {error: ts('err.plan', {code: r.status})};
      announce(state.plan.error);
    } else {
      const plan = await r.json();
      if (!live()) return;
      state.plan = plan;
      const o = plan.options[0];
      announce(state.plan.abstain ? ts('ans.abstain_found') : o ? ts('ans.found', {n: state.plan.options.length, name: o.name}) : '');
      saveOfflinePack();  // background, never on the critical path
    }
  } catch (e) {
    if (!live() || !await offlinePlan(e.name === 'AbortError' ? 'off.slow' : 'off.unreachable', live)) return;
  } finally {
    clearTimeout(timer);
    done();
  }
  render();
}

// ---------- Why this place? (S4 + S5 + S6): evidence, call-ahead, track record, ledger, checks ----------
function whyScreen(rank) {
  const p = state.plan;
  const o = p && !p.error && !p.offline && p.options.find(x => x.rank === rank);
  if (!o) return notFound();
  const i = p.options.indexOf(o), P = `options.${i}`;
  const width = o.p_hi - o.p_lo;
  const tel = telOf(o);
  const maps = `https://www.google.com/maps/dir/?api=1&destination=${o.lat},${o.lon}&travelmode=driving`;
  const split = ts(o.track_record && o.track_record.split === 'test' ? 'why.split_test' : 'why.split_dev');
  state.speak = {danger: isEmergency(), only: i};  // this option, its reason and its questions
  const quotes = o.evidence.length ? o.evidence.map((e, j) => `<blockquote><p class="from">${th('why.quote_from')}</p>${quoteHtml(e, `${P}.evidence.${j}`)}
      ${e.source_url ? `<p class="quote-tools"><a href="${esc(e.source_url)}" rel="noopener noreferrer">${th('why.source')}</a></p>` : ''}</blockquote>`).join('')
    : `<p>${th('why.no_quote', {label: labelF(p.query)})}</p>`;
  const sure = o.model_band === 'NO_SERVICE_TEXT'
    ? noTextSureHtml(o, P, p.query)
    : th('why.sure_score', {band: E(P + '.band_word', o.band_word), p: N(P + '.p', o.p.toFixed(2)), similar: similarHtml(o, P)});
  const outcomes = ['yes', 'no', 'none', 'wrong'];
  return `<a class="back" href="#/plan">${icon('back')} ${th('why.back')}</a>
    <header class="why-head"><h1 tabindex="-1"><span lang="en">${F(P + '.name', o.name)}</span></h1>
      <p>${bandHtml(o, P)}</p><p class="note"><span lang="en">${F(P + '.town', o.town)}</span>${opLabel(o) ? th('punct.stop') + ' ' + opLabel(o) : ''}</p>
      <p>${th('why.distance', {km: N(P + '.travel.km', o.travel.km), low: N(P + '.travel.low', o.travel.low), high: N(P + '.travel.high', o.travel.high)})}
        <span class="note">(${E(P + '.travel.label', o.travel.label)})</span></p>
      ${tel ? `<a class="btn btn-go btn-block" href="${tel}">${icon('phone')} ${th('ans.call')}</a>` : ''}</header>

    <section class="section" aria-labelledby="h-q"><h2 id="h-q">${th('why.quotes_h')}</h2>${noTextCaptionHtml(o, p.query)}${quotes}</section>
    <section class="section" aria-labelledby="how"><h2 id="how">${th('why.ledger_h')}</h2>
      ${ledgerHtml(o, P, p.query)}
      <p class="note">${th('why.model', {hash: F('meta.model_hash', p.meta.model_hash), id: F(P + '.facility_id', o.facility_id)})}</p></section>

    <section class="section" aria-labelledby="h-fam"><h2 id="h-fam">${th('why.family_h')}</h2>
      <p class="panel">${E(P + '.say_to_family.en', o.say_to_family.en)}</p></section>

    <section class="section" aria-labelledby="call"><h2 id="call" tabindex="-1">${th('why.ask_h')}</h2>
      ${isEmergency() ? `<p><strong>${th('why.call_108_first')}</strong></p>` : ''}
      ${tel ? `<a class="btn btn-go btn-block btn-big" href="${tel}">${icon('phone')} ${th('ans.call')} <span class="num">${F(P + '.phone.display', o.phone.display)}</span></a>`
        : `<p class="panel">${th('why.no_dial')}</p>`}
      <div class="pair">${RSInput.speakHtml()}</div><p id="speak-note" class="note" aria-live="polite"></p>
      <ol class="script">
        <li>${th('script.is_this', {name: `<span lang="en">${F(P + '.name', o.name)}</span>`, town: `<span lang="en">${F(P + '.town', o.town)}</span>`})}</li>
        <li>${th('script.need', {label: labelF(p.query)})}</li>
        ${o.call_ahead.map((c, j) => `<li>${E(`${P}.call_ahead.${j}.question`, c.question)}
          <span class="because">${th('why.ask_because', {why: E(`${P}.call_ahead.${j}.asked_because`, c.asked_because)})}</span></li>`).join('')}
        <li>${th('script.if_not')}</li>
        <li>${th('script.whom')}</li>
      </ol>
      <h3 class="section">${th('why.outcome_h')}</h3>
      <div class="outcomes" role="group" aria-label="${th('why.outcome_h')}">${outcomes.map(k => `<button type="button" class="btn" aria-pressed="false" data-outcome="${k}">${th('why.out.' + k)}</button>`).join('')}</div>
      <div id="reason-step"></div>
      <p class="note">${th('why.out_note')}</p></section>

    <section class="section" aria-labelledby="h-sure"><h2 id="h-sure">${th('why.sure_h')}</h2>
      <p id="how-sure">${sure} ${width > 0.4 ? th('why.very_unsure') : ''}</p>
      <p>${trackHtml(o.track_record, P + '.track_record')} (${esc(split)}).</p>${trackBar(o.track_record)}
      ${o.band === 'likely' ? testRecordHtml(p.meta.test_record) : ''}
      ${fieldHtml(o, P)}
      ${o.why_first_text ? `<p><strong>${th('why.ranks_h')}</strong> ${E(P + '.why_first_text', o.why_first_text)}</p>` : ''}
      ${tieHtml(p, o)}</section>

    ${i === 0 ? whyNotHtml(p) : ''}

    <section class="section" aria-labelledby="h-chk"><h2 id="h-chk">${th('why.checks_h')}</h2><dl class="facts">
      <div><dt>${th('why.real')}</dt><dd>${o.is_real.map((x, j) => E(`${P}.is_real.${j}`, x)).join('; ')}</dd></div>
      <div><dt>${th('why.where')}</dt><dd>${E(P + '.where_check', o.where_check)}</dd></div>
      ${o.website ? `<div><dt>${th('why.website')}</dt><dd>${F(`${P}.website.text.${state.lang === 'hi' && o.website.text.hi ? 'hi' : 'en'}`,
        o.website.text[state.lang === 'hi' && o.website.text.hi ? 'hi' : 'en'])}</dd></div>` : ''}
      ${listsHtml(o, P)}
      ${o.flags.map((f, j) => `<div><dt>${th('why.warn')}</dt><dd class="warn">${icon('warn')}<span>${E(`${P}.flags.${j}`, f)}</span></dd></div>`).join('')}
      </dl></section>

    <section class="section" aria-labelledby="h-web"><h2 id="h-web">${th('why.web_h')}</h2>
      <p class="note">${th('why.web_note')}</p>
      <button type="button" id="verify-btn" class="btn btn-block">${th('why.web')}</button>
      <div id="verify-out" aria-live="polite">${verifyHtml((state.verify || {})[o.facility_id])}</div></section>

    <section class="section stack-sm" aria-labelledby="h-act"><h2 id="h-act">${th('why.actions_h')}</h2>
      <a class="btn btn-block" href="#/slip/${o.rank}">${th('why.slip')}</a>
      <a class="btn btn-block" href="${esc(maps)}" rel="noopener noreferrer">${th('why.maps')}</a></section>`;
}
// The model's witness ledger (derived/v2, #132): one row per named term, in points (10 per unit of log-odds), summing to
// the total that maps to p. A row that cites the listing's own sentences opens to show them. Families the model cannot
// see for this listing add nothing and share one muted line. Hindi shows each row's own label_hi from the payload.
const signed = n => (n > 0 ? '+' : '') + (Number.isInteger(n) ? String(n) : n.toFixed(1));
function rowLabel(c, path) {
  if (state.lang === 'hi' && c.label_hi) return F(path + '.label_hi', c.label_hi);
  return c.label_hi === undefined ? E(path + '.label', c.label) : F(path + '.label', c.label);
}
function ledgerHtml(o, P, q) {
  const total = o.contributions.reduce((a, c) => a + c.points, 0);
  const rows = o.contributions.map((c, j) => {
    const C = `${P}.contributions.${j}`;
    const label = rowLabel(c, C);
    const quotes = (c.quotes || []).map((e, k) => `<blockquote>${quoteHtml(e, `${C}.quotes.${k}`)}</blockquote>`).join('');
    const cites = (c.cites || []).map((x, k) => citeHtml(x, `${C}.cites.${k}`)).join('');
    // the row's quotes and list entries go full width under it, so a 320 px screen never scrolls sideways
    return `<tr${quotes || cites ? ' class="has-ev"' : ''}><td>${label}</td><td class="pts">${F(C + '.points', signed(c.points), 'num')}</td></tr>
      ${quotes ? `<tr class="ev"><td colspan="2"><details><summary>${th('why.ledger_quotes', {n: F(C + '.quotes', c.quotes.length, 'count')})}</summary>${quotes}</details></td></tr>` : ''}
      ${cites ? `<tr class="ev"><td colspan="2"><details><summary>${th('why.cite.summary', {n: F(C + '.cites', c.cites.length, 'count')})}</summary>${cites}</details></td></tr>` : ''}`;
  }).join('');
  const unseen = o.not_observed || [];
  return `<table class="ledger"><caption>${th('why.ledger_caption', {label: labelF(q)})}</caption>
      <thead><tr><th scope="col">${th('why.ledger_col')}</th><th scope="col" class="pts">${th('why.ledger_pts')}</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><th scope="row">${th('why.ledger_total')}</th><td class="pts">${F(P + '.contributions', signed(total), 'sum')} &rarr;
        ${N(P + '.p', o.p.toFixed(2))}</td></tr></tfoot>
    </table>
    ${unseen.length ? `<p class="note">${th('why.not_observed', {list: unseen.map((x, j) => rowLabel(x, `${P}.not_observed.${j}`)).join('; ')})}</p>` : ''}`;
}
// WS4 4a: the official-list or OpenStreetMap row a ledger term rests on, with its link, its source and how often our
// matches to that list were right. A NABH row says which kind of entry it is (an entry-level certificate or a CGHS/ECHS
// empanelment is not accreditation); in Hindi that kind is the reviewed string and the entry number stays as listed.
const enSpan = html => (state.lang === 'hi' ? `<span lang="en">${html}</span>` : html);
function citeText(x, path) {
  if (state.lang === 'hi' && x.tier && raw('why.cite.tier.' + x.tier) !== 'why.cite.tier.' + x.tier) {
    return th('why.cite.tier.' + x.tier, {id: enSpan(F(path + '.id', x.id))});
  }
  return enSpan(F(path + '.text', x.text));
}
function citeHtml(x, path) {
  const prec = x.precision_k != null && x.precision_n
    ? ' ' + th('why.cite.precision', {k: N(path + '.precision_k', x.precision_k), n: N(path + '.precision_n', x.precision_n)}) : '';
  return `<p class="cite">${citeText(x, path)}${th('punct.stop')}
    ${x.url ? `<a href="${esc(x.url)}" rel="noopener noreferrer">${th('why.cite.link')}</a>` : ''}
    <span class="note">${th('why.cite.from', {source: enSpan(F(path + '.source', x.source))})}${prec}</span></p>`;
}
function listsHtml(o, P) {
  const lists = o.public_lists || [];
  return lists.length ? `<div><dt>${th('why.cite.lists')}</dt><dd>${lists.map((x, j) => (x.text
    ? citeText(x, `${P}.public_lists.${j}`) : enSpan(F(`${P}.public_lists.${j}.name`, x.name)))).join('; ')}</dd></div>` : '';
}
// How sure for NO SERVICE TEXT (derived/v2/README): never Likely, but its score still comes from the ledger's other
// rows; the two that add most are named, so this line and the ledger agree.
function noTextSureHtml(o, P, q) {
  const top = o.contributions.map((c, j) => [c, j]).filter(([c]) => c.family && c.family !== 'base' && c.points > 0)
    .sort((a, b) => b[0].points - a[0].points).slice(0, 2)
    .map(([c, j]) => `${rowLabel(c, `${P}.contributions.${j}`)} (${F(`${P}.contributions.${j}.points`, signed(c.points), 'num')})`);
  return th(q.service === 'trauma_emergency' && o.evidence.length ? 'why.no_text_trauma' : 'why.no_text_other',
    {band: E(P + '.band_word', o.band_word), label: labelF(q), p: N(P + '.p', o.p.toFixed(2))})
    + (top.length ? ' ' + th('why.largest', {rows: top.join('; ')}) : '') + ' ' + th('why.call_to_ask');
}
// A #/why or #/slip link with no plan in memory: after a reload, from a shared link, or offline (#121).
function notFound() {
  const back = svc(state.service) && state.loc ? '#/plan' : '#/';  // the saved answer, or the service tiles
  return `<h1 tabindex="-1">${th('err.not_found')}</h1><p>${th('err.not_found_help')}</p>
    <a class="btn btn-ink btn-block section" href="${back}">${th('err.search_again')}</a>`;
}
// ---------- live website check (#37): a dated line next to the plan; never changes the band ----------
function verifyHtml(v) {
  if (!v) return '';
  if (v.loading) return `<p>${th('verify.loading')}</p>`;
  if (v.error) return `<p class="panel">${esc(v.error)}</p>`;
  const d = new Date(v.checked_at_ms);
  const day = d.toDateString() === new Date().toDateString() ? ts('verify.today') : d.toLocaleDateString(locale(), {day: 'numeric', month: 'short'});
  const when = th('verify.when', {time: F('verify.checked_at_ms', timeStr(v.checked_at_ms), 'clock'), day: esc(day)});
  const q = (x, j) => `<blockquote><p lang="en">"${F(`verify.quotes.${j}.text`, x.text)}"</p>
    <p class="quote-tools"><a href="${esc(x.url)}" rel="noopener noreferrer">${F(`verify.quotes.${j}.url`, x.url)}</a></p></blockquote>`;
  const status = `<span lang="en">${F('verify.status_text', v.status_text)}</span>`;
  if (v.status === 'found') return `<p class="panel">${when}: ${status}:</p>${v.quotes.map(q).join('')}`;
  const said = v.quotes.length ? `<p>${th('verify.only')}</p>${v.quotes.map(q).join('')}` : '';
  return `<p class="panel">${when}: ${status}.</p>${said}`;
}
async function runVerify(o) {
  const key = o.facility_id;
  (state.verify ||= {})[key] = {loading: true};
  $('#verify-out').innerHTML = verifyHtml(state.verify[key]);
  try {
    const r = await fetch('/api/verify', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({facility_id: o.facility_id, service_id: state.service}), redirect: 'manual'});
    const body = r.ok || r.status === 503 ? await r.json() : null;
    state.verify[key] = r.ok ? body : {error: body && body.error ? ts('verify.na', {why: body.error})
      : ts('verify.failed', {code: r.status || ts('err.signed_out')})};
  } catch {
    state.verify[key] = {error: ts('verify.needs_net')};
  }
  const out = $('#verify-out');
  if (out) {
    out.innerHTML = verifyHtml(state.verify[key]);
    announce(state.verify[key].error || ts('verify.done', {status: state.verify[key].status_text}));
  }
}
// Outcome buttons carry a code; the slip and the outcome queue use the same codes (said: yes | no | none | wrong).
function bindWhy() {
  const rank = parseInt(location.hash.split('/')[2], 10);
  const o = state.plan && !state.plan.error && !state.plan.offline && state.plan.options.find(x => x.rank === rank);
  if (o) $('#verify-btn')?.addEventListener('click', () => runVerify(o));
  loadScript('/community.js', 'RSCommunity').catch(() => {});  // the reason step; without it a "no" goes alone
  document.querySelectorAll('[data-outcome]').forEach(b => b.addEventListener('click', () => {
    const at = Date.now(), said = b.dataset.outcome;
    document.querySelectorAll('[data-outcome]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    (state.outcomes ||= {})[rank] = {said, at};  // for the slip (#24)
    window.RSCommunity?.callAfter(state.plan, o, said);
    window.RSCommunity?.dropPending();  // a corrected tap replaces an unsent "no"
    $('#reason-step').innerHTML = '';
    if (said === 'no' && o && window.RSCommunity) {
      RSCommunity.askReason($('#reason-step'), reason => queueOutcome(o, said, at, reason ? {reason} : {}), announce);
      announce(ts('why.noted_no'));
      return;
    }
    const sent = o && queueOutcome(o, said, at);
    announce(ts(sent ? 'why.noted_sent' : 'why.noted', {said: ts('why.out.' + said)}));
  }));
  if (location.hash.endsWith('#call')) $('#call')?.focus();
}

// ---------- call outcomes (#65): ids, the answer, a district; queued offline, flushed when back online ----------
const OUTCOME_CODE = {yes: 'yes', no: 'no', none: 'no_answer'};  // "Wrong number" is not sent
function queueOutcome(o, said, at, extra = {}) {
  const outcome = OUTCOME_CODE[said];
  if (!outcome || !state.loc || !state.service) return false;
  queueItem({outcome_id: crypto.randomUUID(), facility_id: o.facility_id, service_id: state.service, outcome,
    said_at_ms: at, lat: Math.round(state.loc.lat * 100) / 100, lon: Math.round(state.loc.lon * 100) / 100, ...extra});
  return true;
}
// ponytail: when storage is blocked or full the queue lives in memory, so it is sent this session but lost on reload
let memQ = null;
function outQ() { return memQ || load('outq') || []; }
function setOutQ(q) { memQ = save('outq', q) ? null : q; }
function queueItem(item) {  // also the visit reports from community.js
  setOutQ([...outQ(), item].slice(-50));
  flushOutcomes();
}
let flushing = false;
async function flushOutcomes() {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    for (let item; (item = outQ()[0]);) {  // re-read each time: an item queued while this runs is sent too
      let drop = false;
      try {
        const r = await fetch('/api/outcome', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(item), signal: AbortSignal.timeout(15000)});
        drop = r.ok || (r.status >= 400 && r.status < 500);  // 4xx will never succeed; 5xx and network errors retry
      } catch { /* offline again: keep it */ }
      if (!drop) break;
      setOutQ(outQ().filter(x => x.outcome_id !== item.outcome_id));
    }
  } finally { flushing = false; }
}
window.addEventListener('online', flushOutcomes);

// ---------- referral slip (S8, #24): slip.js loads only on this route; its language is the app language ----------
function slipScreen(rank) {
  const p = state.plan;
  const o = p && !p.error && !p.offline && p.options.find(x => x.rank === rank);
  if (!o) return notFound();
  return `<a class="back no-print" href="#/why/${rank}">${icon('back')} ${th('slip.back')}</a>
    <h1 tabindex="-1" class="no-print">${th('slip.h')}</h1>
    <p class="no-print"><strong>${th('slip.ask')}</strong> ${th('slip.no_name')}</p>
    <div id="slip-out"><p>${th('slip.preparing')}</p></div>
    <div class="pair no-print section">
      <button type="button" class="btn" id="slip-big">${th('slip.big')}</button>
      <button type="button" class="btn" id="slip-print">${th('slip.print')}</button>
      <a class="btn" id="slip-wa" href="#" rel="noopener noreferrer">${th('slip.wa')}</a>
      <a class="btn" id="slip-sms" href="#">${th('slip.sms')}</a>
      <button type="button" class="btn btn-ink" id="slip-card">${th('slip.card')}</button>
    </div>
    <p class="note no-print">${th('slip.card_note')}</p>`;
}
function loadSlipJs() { return loadScript('/slip.js', 'RSSlip'); }
async function bindSlip() {
  const rank = parseInt(location.hash.split('/')[2], 10);
  const p = state.plan;
  const o = p && !p.error && !p.offline && p.options.find(x => x.rank === rank);
  if (!o) return;
  try { await loadSlipJs(); } catch { $('#slip-out').innerHTML = `<p role="alert">${th('slip.load_failed')}</p>`; return; }
  const backup = p.options.find(x => x.rank !== rank) || null;
  const lang = state.lang;
  const out = (state.outcomes || {})[rank];
  const m = RSSlip.slipModel(p, o, backup, out ? {said: {yes: 'Said yes', no: 'Said no', none: 'No answer', wrong: 'Wrong number'}[out.said], at: out.at} : null);
  $('#slip-out').innerHTML = RSSlip.toHtml(m, lang);
  $('#slip-wa').href = RSSlip.toWhatsApp(m, lang).url;
  $('#slip-sms').href = RSSlip.toSms(m, lang).url;
  $('#slip-big').addEventListener('click', () => {
    const on = document.body.classList.toggle('slip-big');
    $('#slip-big').textContent = ts(on ? 'slip.normal' : 'slip.big');
  });
  $('#slip-print').addEventListener('click', () => window.print());
  loadScript('/community.js', 'RSCommunity').then(() => RSCommunity.remember(p, o, state.loc)).catch(() => {});
  $('#slip-card').addEventListener('click', async () => {
    const C = window.RSCommunity;
    const msg = k => (C ? C.say(k) : '');
    try {
      const r = await RSSlip.shareJourney(p, lang, {rank});
      announce(msg(r === 'downloaded' ? 'cardSaved' : r === 'shared' ? 'cardShared' : 'cardCancelled'));
    } catch {
      announce(msg('cardFailed') || ts('slip.card_failed'));
    }
  });
}

// ---------- How this works (#45) and Data stories (#53): long English pages built from the data ----------
function enOnly() { return state.lang === 'hi' ? `<p class="panel" lang="hi">${th('page.english_only')}</p>` : ''; }
function howScreen() { return `<h1 tabindex="-1">${th('nav.how')}</h1>${enOnly()}<div id="how-out"><p>${th('page.loading')}</p></div>`; }
// One tag per script: a second copy of speech.js loading late would replace RSSpeech with one that has no templates.
function loadScript(src, name) { return window[name] ? Promise.resolve() : needScripts([src]); }
async function bindHow() {
  try {
    const [, r] = await Promise.all([loadScript('/how.js', 'RSHow'), fetch('/api/how', {redirect: 'manual'})]);
    if (!r.ok) throw new Error();
    $('#main').innerHTML = enOnly() + `<div lang="en">${RSHow.render(await r.json())}</div>
      <a class="btn btn-block section" href="#/stories">${th('nav.stories')}</a>`;
    $('#main h1').focus();
  } catch {
    $('#how-out').innerHTML = `<p role="alert">${th('page.failed')}</p>`;
    return;
  }
  liveOutcomes();
}
// Live count from the call_outcomes table (#65). Marked data-device: a live reading, not a page-data number.
async function liveOutcomes() {
  let s;
  try {
    const r = await fetch('/api/outcomes/summary', {signal: AbortSignal.timeout(10000)});
    if (!r.ok) return;
    s = await r.json();
  } catch { return; }
  const built = [...document.querySelectorAll('#main p.small.muted')].pop();
  if (!built) return;
  const sec = document.createElement('section');
  sec.innerHTML = `<h2>What callers told us</h2><p data-device>${s.recorded} call results recorded so far
    (${s.yes} said yes, ${s.no} said no, ${s.no_answer} no answer). Of the ${s.answered} answered calls,
    ${s.contradicted} contradicted the label the app showed and ${s.agreed} agreed with it; the rest were for
    "Not verified" options. Live from the call_outcomes table at ${esc(timeStr(s.as_of))}. These results are
    reviewed, not fed back into the scores automatically.</p>`;
  built.before(sec);
}
function storiesScreen() { return `<h1 tabindex="-1">${th('nav.stories')}</h1>${enOnly()}<div id="stories-out"><p>${th('page.loading')}</p></div>`; }
async function bindStories() {
  try {
    const [, r] = await Promise.all([loadScript('/stories.js', 'RSStories'), fetch('/api/stories', {redirect: 'manual'})]);
    if (!r.ok) throw new Error();
    $('#main').innerHTML = enOnly() + `<div lang="en">${RSStories.render(await r.json())}</div>`;
    RSStories.bind($('#main'));
    $('#main h1').focus();
  } catch {
    $('#stories-out').innerHTML = `<p role="alert">${th('page.failed')}</p>`;
  }
}

// ---------- Recent: referrals made on this phone, and "How did this referral go?" ----------
function recentScreen() {
  const list = RECENT();
  return `<h1 tabindex="-1">${th('nav.recent')}</h1>
    ${list.length ? `<ul class="rows section">${list.map(r => `<li class="recent-row"><b lang="en">${esc(r.name)}</b>
      <span class="note">${esc(svc(r.service)?.label || r.service)}</span></li>`).join('')}</ul>
      <a class="btn btn-ink btn-block section" href="#/report">${th('report.link')}</a>`
      : `<p class="panel section">${th('recent.none')}</p>`}`;
}
function bindReport() {
  loadScript('/community.js', 'RSCommunity').then(() => RSCommunity.bindReport($('#report-out'), queueItem, announce))
    .catch(() => { $('#report-out').innerHTML += `<p role="alert">${th('page.failed')}</p>`; });
}
// ---------- Your area (pulse.js): anonymous district counts, loaded only on this route ----------
function bindPulse() {
  const out = $('#pulse-out');
  const cards = Object.fromEntries((state.plan?.options || []).map(o => [o.facility_id, `#/why/${o.rank}`]));
  loadScript('/pulse.js', 'RSPulse')
    .then(() => RSPulse.initPulse(out, {services: SERVICES.filter(s => s.profile), service: state.service, loc: state.loc, cards, lang: state.lang}))
    .catch(() => { out.innerHTML += `<p role="alert">${th('page.failed')}</p>`; });
}

// ---------- Settings: language, text size, voice, screen colour, saved data ----------
function settingsScreen() {
  const radio = (name, v, label, cur, attrs = '') => `<label ${attrs}><input type="radio" name="${name}" id="${name}-${v}" value="${v}" ${String(cur) === String(v) ? 'checked' : ''}> <span>${label}</span></label>`;
  const size = load('size') || 100, theme = load('theme') || 'system';
  return `<h1 tabindex="-1">${th('set.h')}</h1>
    <fieldset class="section"><legend>${th('set.lang_h')}</legend><div class="choice">
      ${LANGS.map(l => radio('lang', l, esc(I18N[l]['lang.name']), state.lang, `lang="${l}"`)).join('')}</div>
      <p class="note">${th('set.lang_note')}</p></fieldset>
    <fieldset class="section"><legend>${th('set.size_h')}</legend><div class="seg">
      ${SIZES.map(v => radio('size', v, `${v}%`, size)).join('')}</div>
      <p class="panel sample">${th('set.size_sample')}</p></fieldset>
    <fieldset class="section"><legend>${th('set.voice_h')}</legend>
      <label class="check"><input type="checkbox" id="opt-say" ${load('say') !== false ? 'checked' : ''}> ${th('set.read')}</label></fieldset>
    <fieldset class="section"><legend>${th('set.theme_h')}</legend><div class="seg">
      ${['system', 'light', 'dark'].map(v => radio('theme', v, th('set.theme.' + v), theme)).join('')}</div></fieldset>
    <section class="section" aria-labelledby="h-off"><h2 id="h-off">${th('set.offline_h')}</h2><p>${savedLine()}</p></section>`;
}
function bindSettings() {
  document.querySelectorAll('input[name=lang]').forEach(r => r.addEventListener('change', () => setLang(r.value, {focus: '#lang-' + r.value})));
  document.querySelectorAll('input[name=size]').forEach(r => r.addEventListener('change', () => { save('size', +r.value); applyPrefs(); }));
  document.querySelectorAll('input[name=theme]').forEach(r => r.addEventListener('change', () => { save('theme', r.value); applyPrefs(); }));
  $('#opt-say').addEventListener('change', e => save('say', e.target.checked));
}
function applyPrefs() {
  const html = document.documentElement, size = load('size') || 100, theme = load('theme') || 'system';
  html.style.fontSize = SIZES.includes(size) && size !== 100 ? size + '%' : '';
  if (theme === 'light' || theme === 'dark') html.dataset.theme = theme; else delete html.dataset.theme;
}
// One tap switches every string, read-aloud, voice input, the slip and the card; focus and scroll stay put.
function setLang(l, opts = {}) {
  if (!LANGS.includes(l)) return;
  state.lang = l;
  save('lang', l);
  save('voice', {...(load('voice') || {}), lang: l});  // voice.js and speech read the same language
  document.documentElement.lang = l;
  if (opts.rerender === false) return;
  const y = window.scrollY;
  if (window.speechSynthesis) speechSynthesis.cancel();
  render({keepFocus: true});
  window.scrollTo(0, y);
  $(opts.focus || '#lang-btn')?.focus({preventScroll: true});
  announce(ts('lang.changed'));
}

// ---------- chrome: top bar and bottom navigation ----------
function topBar() {
  const other = state.lang === 'hi' ? 'en' : 'hi';
  $('#top').innerHTML = `<a class="brand" href="#/"><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M5 14h18" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
      <circle cx="6" cy="14" r="4" fill="var(--surface)" stroke="currentColor" stroke-width="2.5"/><circle cx="22" cy="14" r="4.5" fill="var(--go)"/></svg>
      <span>${th('app.name')}</span></a>
    <button type="button" class="btn lang-btn" id="lang-btn" lang="${other}" data-lang="${other}">${esc(I18N[other]['lang.name'])}</button>
    <a class="btn icon-btn" href="#/settings" aria-label="${th('nav.settings')}">${icon('sliders')}</a>`;
  $('#lang-btn').addEventListener('click', e => setLang(e.currentTarget.dataset.lang));
  $('#skip').textContent = ts('skip');
  $('#offline').setAttribute('aria-label', ts('off.h'));
  $('#offline').innerHTML = `${icon('wifiOff')}<span><b>${th('off.h')}</b> ${th('off.banner')}</span>`;
  $('#status').lang = state.lang;
}
function bottomNav(route) {
  const tab = route === 'recent' || route === 'report' ? 'recent' : route === 'area' || route === 'pulse' ? 'area'
    : route === 'how' || route === 'stories' ? 'how' : route === 'settings' ? '' : 'home';
  const item = (href, name, key) => `<a href="${href}"${tab === key ? ' aria-current="page"' : ''}>${icon(name)}<span>${th('nav.' + key)}</span></a>`;
  $('#nav').innerHTML = item('#/', 'home', 'home') + item('#/recent', 'clock', 'recent') + item('#/area', 'map', 'area') + item('#/how', 'help', 'how');
  $('#nav').setAttribute('aria-label', ts('nav.label'));
}

// ---------- router ----------
function render(opts = {}) {
  const h = location.hash || '#/';
  if (!state.lang && h !== '#/lang') {
    // a fresh phone opening a deep link (#/change, #/why/1, a shared link) goes there once the language is chosen
    if (h !== '#/' && h !== '#') state.afterLang = h;
    location.hash = '#/lang';
    return;
  }
  const route = (h.match(/^#\/(\w*)/) || [])[1] || '';
  let html, bind = () => {};
  if (route === 'lang') [html, bind] = [chooserScreen(), bindChooser];
  else if (h === '#/gps') [html, bind] = [gpsScreen(), bindGps];
  else if (h === '#/change') [html, bind] = [changeScreen(), bindChange];
  else if (h === '#/plan') [html, bind] = [planScreen(), bindPlan];
  else if (h.startsWith('#/why/')) [html, bind] = [whyScreen(parseInt(h.split('/')[2], 10)), bindWhy];
  else if (h.startsWith('#/slip/')) [html, bind] = [slipScreen(parseInt(h.split('/')[2], 10)), bindSlip];
  else if (h === '#/how') [html, bind] = [howScreen(), bindHow];
  else if (h === '#/describe') [html, bind] = [RSInput.describeScreen(), RSInput.bindDescribe];
  else if (h === '#/note') [html, bind] = [RSInput.noteScreen(), RSInput.bindNote];
  else if (h === '#/stories') [html, bind] = [storiesScreen(), bindStories];
  else if (h === '#/settings') [html, bind] = [settingsScreen(), bindSettings];
  else if (h === '#/recent') html = recentScreen();
  else if (h === '#/area') [html, bind] = [areaScreen(), bindArea];
  else if (h === '#/report') [html, bind] = [`<div id="report-out"><h1 tabindex="-1">${th('report.link')}</h1><p>${th('page.loading')}</p></div>`, bindReport];
  else if (h === '#/pulse') [html, bind] = [`<div id="pulse-out"><h1 tabindex="-1">${th('pulse.h')}</h1><p>${th('page.loading')}</p></div>`, bindPulse];
  else [html, bind] = [home(), bindHome];
  const bare = route === 'lang';
  document.body.classList.toggle('bare', bare);
  if (!bare) { topBar(); bottomNav(route); }
  $('#main').innerHTML = html;
  document.body.classList.toggle('wide', (h === '#/plan' && state.depth === 'compare') || h === '#/area');
  document.body.classList.toggle('on-plan', h === '#/plan');  // no bottom nav on the answer: Call needs the room
  renderBar();
  if (h.startsWith('#/why/')) needScripts(['/passed.js']).then(() => RSPassed()).catch(() => {});  // UI-PASSED-1, after paint
  if (h.startsWith('#/why/')) needScripts(['/receipt.js']).then(() => RSReceipt()).catch(() => {});  // UI-RECEIPT-1
  if (h === '#/plan' && state.plan && state.plan.itinerary && typeof routeHtml !== 'function') {
    needScripts(['/route.js']).then(() => render({keepFocus: true})).catch(() => {});  // e.g. back to #/plan
  }
  const h1 = $('#main h1');
  if (h1 && !opts.keepFocus && !h.endsWith('#call')) h1.focus({preventScroll: false});
  document.title = (h1 ? h1.textContent.trim() + ' - ' : '') + ts('app.name');
  bind();
  if ($('#speak')) RSInput.bindSpeak(state.speak);
  callBar();
  if (state.lang === 'hi' && state.plan && $('#main [data-f$=".quote"]')) needScripts(['/translate.js']).then(() => RSTranslate.bind($('#main'))).catch(() => {});
}
// On a short screen (under 600 px tall) a fixed Call bar shows whenever any part of the answer card is on screen and
// its own Call button is not fully visible, so Call is reachable whatever stands above the card (#178). It copies the
// card's link without the data-f marks (the card keeps them) and lives outside #main.
function callBar() {
  $('#call-bar')?.remove();
  if (state.callObs) { state.callObs.disconnect(); state.callObs = null; }
  const card = $('#main article.answer'), call = card && card.querySelector('.call-main');
  if (!call || !('IntersectionObserver' in window) || !matchMedia('(max-height: 600px)').matches) return;
  // During the call loop (#181) the card's Call is no longer the next action: no bar (it would redial option 1).
  const c = state.call, p = state.plan;
  if (c && c.plan === p && (c.stage !== 'dialing' || c.rank !== p.options[0].rank)) return;
  const bar = document.createElement('div');
  bar.id = 'call-bar';
  bar.className = 'call-bar';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', ts('ans.call_first'));
  bar.hidden = true;
  const name = ($('#main article.answer .name') || {}).textContent || '';
  bar.innerHTML = call.outerHTML.replace(/ data-[fk]="[^"]*"/g, '').replace('call-main', 'call-fixed')
    .replace('</a>', `<span class="visually-hidden" lang="en"> ${esc(name)}</span></a>`);
  document.body.appendChild(bar);
  let cardOn = false, callOn = false;
  state.callObs = new IntersectionObserver(es => {
    es.forEach(e => { if (e.target === card) cardOn = e.isIntersecting; else callOn = e.intersectionRatio > 0.999; });
    bar.hidden = !(cardOn && !callOn);
  }, {threshold: [0, 1]});
  state.callObs.observe(card);
  state.callObs.observe(call);
}
window.addEventListener('hashchange', () => {
  window.RSCommunity?.sendPending();  // a "no" left without a reason is sent as it is
  if (location.hash === '#/' || location.hash === '#/change') {
    state.plan = null; state.outcomes = {}; state.area = null; state.patientHere = null; state.verify = {}; state.depth = 'quick'; stopWatch();
  }
  document.body.classList.remove('slip-big');
  render();
});
function setOnline() { $('#offline').hidden = navigator.onLine; }
window.addEventListener('online', setOnline);
window.addEventListener('offline', setOnline);

document.addEventListener('DOMContentLoaded', async () => {
  // The skip link must not change the hash: the router owns it.
  $('#skip').addEventListener('click', e => { e.preventDefault(); $('#main').focus(); });
  applyPrefs();
  try { await loadStrings(); } catch {
    $('#main').innerHTML = '<h1>Referral Saathi</h1><p>Could not load the app. In an emergency call <a href="tel:108">108</a>.</p>';
    return;
  }
  state.lang = pickLang();
  if (state.lang) { document.documentElement.lang = state.lang; save('lang', state.lang); }
  setOnline();
  RSInput.load();
  flushOutcomes();
  if (location.hash === '#/plan' && !state.plan) history.replaceState(null, '', '#/');  // a reload drops the plan
  render();
  // GPS is the default: refresh silently when permission is already granted (no prompt on load).
  try {
    const perm = await navigator.permissions?.query({name: 'geolocation'});
    if (perm && perm.state === 'granted' && (location.hash || '#/') === '#/') getGps(err => { if (!err) render(); });
    // Blocked GPS puts typing the place first; unblocking it in site settings puts GPS back (#121 bug 5).
    const onPerm = () => {
      state.gpsDenied = perm.state === 'denied';
      if (['', '#/', '#/change'].includes(location.hash)) render();
    };
    if (perm && perm.state === 'denied') onPerm();
    if (perm) perm.onchange = onPerm;
  } catch { /* Permissions API missing: the GPS button stays */ }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
});
