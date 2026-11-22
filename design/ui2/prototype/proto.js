// UI2 prototype (design/ui2/SPEC.md). Plain JS, hash routes, real /api/plan payloads from data/ (phones replaced).
// One language on screen: every string comes from i18n/<lang>.json through t(); payload values keep data-f markers
// as in app/static/app.js; engine template text is mapped to Hindi through the "engine" table (data-k="template").
'use strict';

const S = {strings: {}, data: {}, lang: null, size: 100, theme: 'system', read: true, mic: true};
const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem('rs2.' + k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem('rs2.' + k, JSON.stringify(v)); } catch { /* private mode: setting lasts this visit */ } },
};

// ---------- strings ----------
function t(key, vars = {}) {
  const s = (S.strings[S.lang] || {})[key] ?? S.strings.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
}
const T = (key, vars) => esc(t(key, vars));
// Faithfulness marker (app.js F()): the shown value equals the payload value at path.
const F = (path, text, kind = 'text') => `<span data-f="${path}" data-k="${kind}">${esc(text)}</span>`;
// Engine text: English as sent; in Hindi, the reviewed template, still marked with its payload path.
function engHi(text, ctx) {
  const map = S.strings.hi.engine;
  if (map[text]) return map[text];
  for (const [k, v] of Object.entries(map)) {
    if (!k.includes('{')) continue;
    const names = [];
    const re = new RegExp('^' + k.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{(\w+)\}/g, (_, n) => { names.push(n); return '(.+?)'; }) + '$');
    const m = text.match(re);
    if (!m) continue;
    const vals = {...ctx};
    names.forEach((n, i) => { vals[n] = m[i + 1]; });
    return v.replace(/\{(\w+)\}/g, (_, n) => vals[n] ?? '');
  }
  return null;
}
function E(path, text, ctx = {}) {
  if (S.lang !== 'hi') return F(path, text);
  const hi = engHi(text, ctx);
  return hi ? `<span data-f="${path}" data-k="template">${esc(hi)}</span>` : `<span data-f="${path}" data-k="text" lang="en">${esc(text)}</span>`;
}
const fmtDate = iso => new Date(iso + 'T00:00:00').toLocaleDateString(S.lang === 'hi' ? 'hi-IN' : 'en-IN', {day: 'numeric', month: 'long', year: 'numeric'});

// ---------- icons: 24 px grid, 2 px stroke, round ends ----------
const P = {
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
P.other = P.help;
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${P[name]}</svg>`;
const BAND_SVG = {
  likely: '<circle cx="8" cy="8" r="7"/><path d="M4.5 8.5l2.2 2.2 4.8-5" fill="none"/>',
  not_verified: '<path d="M8 1l7 7-7 7-7-7z"/><path d="M6.4 6.3a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.6-.7 1.1M8 11.4v.1" fill="none"/>',
  unlikely: '<rect x="1.5" y="1.5" width="13" height="13"/><path d="M5 5l6 6M11 5l-6 6"/>',
};
const bandSvg = b => `<svg viewBox="0 0 16 16" aria-hidden="true">${BAND_SVG[b]}</svg>`;
function bandMark(o, path) {
  const p = o.model_band === 'NO_SERVICE_TEXT' ? `${path}.model_band` : `${path}.band`;
  return `<span class="band band-${o.band}">${bandSvg(o.band)}<span data-f="${p}" data-k="band">${T('band.' + o.band)}</span></span>`;
}

const SERVICES = [
  ['emergency_csection', true], ['nicu', true], ['trauma_emergency', true], ['burn_care', true],
  ['dialysis', false], ['mri', false], ['cardiac_surgery', false], ['other', false]];
const PLAN_OF = {trauma_emergency: 'trauma', dialysis: 'dialysis'};
const isEmergency = p => p.profile === 'emergency' || p.profile === 'urgent';
const opLabel = o => T('op.' + (o.operator in {public: 1, private: 1} ? o.operator : 'unknown'));
const place = p => `${p.location.lat.toFixed(2)}, ${p.location.lon.toFixed(2)}`;
const telOf = o => o.phone && o.phone.e164 ? `tel:${esc(o.phone.e164)}` : null;

// ---------- chrome ----------
function topBar() {
  const other = t('lang.other_code');
  return `<a class="vh skip" href="#main" id="skip">${T('skip')}</a>
  <header class="top">
    <a class="brand" href="#/"><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M5 14h18" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
      <circle cx="6" cy="14" r="4" fill="var(--surface)" stroke="currentColor" stroke-width="2.5"/><circle cx="22" cy="14" r="4.5" fill="var(--go)"/></svg>
      <span>${T('app.name')}</span></a>
    <button type="button" class="btn lang-btn" id="lang-btn" lang="${other}" data-lang="${other}">${T('lang.other')}</button>
    <a class="btn icon-btn" href="#/settings" aria-label="${T('nav.settings')}">${icon('sliders')}</a>
  </header>`;
}
function sosBar(p) {
  const with102 = p.query.service === 'emergency_csection' || p.query.service === 'nicu';
  return `<nav class="sos" aria-label="108"><a href="tel:108">${icon('phone')}<span><b>${T('sos.108')}</b> <span>${T('sos.108_sub')}</span></span></a>
    ${with102 ? `<a href="tel:102">${icon('phone')}<span><b>${T('sos.102')}</b> <span>${T('sos.102_sub')}</span></span></a>` : ''}</nav>`;
}
function bottomNav(active) {
  const item = (href, name, key) => `<a href="${href}" ${active === key ? 'aria-current="page"' : ''}>${icon(name)}<span>${T('nav.' + key)}</span></a>`;
  return `<nav class="nav" aria-label="${T('nav.label')}">${item('#/', 'home', 'home')}${item('#/recent', 'clock', 'recent')}
    ${item('#/area', 'map', 'area')}${item('#/how', 'help', 'how')}</nav>`;
}

// ---------- screens ----------
function chooser() {
  const pre = S.lang || ((navigator.language || '').toLowerCase().startsWith('hi') ? 'hi' : 'en');
  const order = pre === 'hi' ? ['hi', 'en'] : ['en', 'hi'];
  const head = {hi: 'अपनी भाषा चुनें', en: 'Choose your language'};
  const name = {hi: 'हिन्दी', en: 'English'};
  return `<main id="main" class="chooser" tabindex="-1">
    <svg class="mark" viewBox="0 0 28 28" aria-hidden="true"><path d="M5 14h18" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
      <circle cx="6" cy="14" r="4" fill="var(--surface)" stroke="currentColor" stroke-width="2.5"/><circle cx="22" cy="14" r="4.5" fill="var(--go)"/></svg>
    <h1 lang="${order[0]}">${head[order[0]]}</h1><p lang="${order[1]}">${head[order[1]]}</p>
    <fieldset><legend class="vh">${head.hi} / ${head.en}</legend><div class="choice">
      ${order.map(l => `<label lang="${l}"><input type="radio" name="first-lang" value="${l}" ${l === pre ? 'checked' : ''}> ${name[l]}</label>`).join('')}
    </div></fieldset>
    <button type="button" class="btn btn-block btn-big btn-ink" id="lang-go" lang="${pre}">${esc(S.strings[pre]['lang.continue'])}</button>
    <p class="note" id="lang-note" lang="${pre}">${esc(S.strings[pre]['lang.later'])}</p>
  </main>`;
}
function bindChooser() {
  document.querySelectorAll('input[name=first-lang]').forEach(r => r.addEventListener('change', () => {
    const l = r.value;
    Object.assign($('#lang-go'), {lang: l, textContent: S.strings[l]['lang.continue']});
    Object.assign($('#lang-note'), {lang: l, textContent: S.strings[l]['lang.later']});
  }));
  $('#lang-go').addEventListener('click', () => {
    setLang(document.querySelector('input[name=first-lang]:checked').value, false);
    location.hash = '#/';
  });
}

function home() {
  const tiles = SERVICES.map(([k, em]) => `<a class="tile${em ? ' emergency' : ''}" href="${PLAN_OF[k] ? '#/plan/' + PLAN_OF[k] : '#/stub/' + k}">
    ${icon(k)}<span>${T('svc.' + k)}</span></a>`).join('');
  const danger = [0, 1, 2, 3, 4, 5].map(i => `<label class="check"><input type="checkbox"> ${T('danger.' + i)}</label>`).join('');
  return `<main id="main" tabindex="-1" class="stack">
    <h1 class="vh">${T('home.h')}</h1>
    <div class="sos-row"><p>${T('home.sos')}</p><a class="btn btn-hazard" href="tel:108">${icon('phone')} 108</a></div>
    <section class="section" aria-labelledby="h-where"><h2 id="h-where">${T('home.where')}</h2>
      <a class="where" href="#/stub/change">${icon('pin')}<span class="where-text"><b class="num" data-device>25.60, 85.95</b>
        <span class="small muted" data-device>${T('home.where_gps', {m: 40, time: '10:42'})}</span></span><span class="where-change">${T('home.change')}</span></a></section>
    <section class="section" aria-labelledby="h-need"><h2 id="h-need">${T('home.need_h')}</h2>
      <button type="button" class="btn btn-block btn-big btn-ink" aria-pressed="false" id="mic">${icon('mic')} ${T('home.speak')}</button>
      <div class="tiles" style="margin-top:var(--sp3)">${tiles}</div>
      <div class="pair" style="margin-top:var(--sp3)"><a class="btn" href="#/stub/describe">${icon('keyboard')} ${T('home.type')}</a>
        <a class="btn" href="#/stub/note">${icon('camera')} ${T('home.scan')}</a></div></section>
    <details><summary>${T('home.danger_h')}</summary>${danger}<p class="note">${T('home.danger_note')}</p></details>
    <p class="note">${T('home.saved', {state: S.lang === 'hi' ? 'बिहार' : 'Bihar', date: fmtDate('2026-11-21')})}</p>
  </main>`;
}

function answerPanel(p, o) {
  const P0 = 'options.0', tr = o.travel;
  const sureKey = o.model_band === 'NO_SERVICE_TEXT' ? 'no_text' : o.band;
  const sureCls = o.band === 'likely' ? 'sure-ok' : o.band === 'unlikely' ? 'sure-no' : 'sure-nv';
  const tel = telOf(o);
  return `<section class="panel answer${o.band === 'likely' ? ' likely' : ''}" aria-labelledby="h-first">
    <h2 id="h-first">${T('ans.call_first')}</h2>
    <p class="name" lang="en">${F(P0 + '.name', o.name)}</p>
    <p class="place">${F(P0 + '.town', o.town)}. ${opLabel(o)}</p>
    <p class="readout"><span class="big">${F(P0 + '.travel.minutes', tr.minutes, 'num')}</span><span class="unit">${T('ans.min')}</span>
      <span class="sub">${t(tr.method === 'osrm' ? 'ans.range' : 'ans.range_rough', {low: '\u0001', high: '\u0002', km: '\u0003'})
        .replace('\u0001', F(P0 + '.travel.low', tr.low, 'num')).replace('\u0002', F(P0 + '.travel.high', tr.high, 'num'))
        .replace('\u0003', F(P0 + '.travel.km', Math.round(tr.km), 'num'))}</span></p>
    <p class="sure ${sureCls}">${bandSvg(o.band)}<span><span data-f="${o.model_band === 'NO_SERVICE_TEXT' ? P0 + '.model_band' : P0 + '.band'}" data-k="band">${T('band.' + o.band)}</span>${T('punct.stop')} ${T('ans.sure.' + sureKey)}</span></p>
    ${tel ? `<a class="btn btn-go btn-block btn-big" href="${tel}">${icon('phone')} ${T('ans.call')} <span class="num">${F(P0 + '.phone.display', o.phone.display)}</span></a>` : ''}
    <div class="pair"><button type="button" class="btn" id="listen" aria-pressed="false">${icon('speaker')} <span>${T('ans.listen')}</span></button>
      <a class="btn" href="#/why/${S.plan}/1">${T('ans.why')}</a></div>
  </section>`;
}
function nextRows(p) {
  const rows = p.options.slice(1, 3).map((o, j) => {
    const i = j + 1, Q = `options.${i}`, tel = telOf(o);
    return `<li class="next-row"><span class="rank">${F(Q + '.rank', o.rank, 'num')}</span>
      <a class="nm" href="#/why/${S.plan}/${o.rank}"><b lang="en">${F(Q + '.name', o.name)}</b>
        <span>${t('ans.next_meta', {low: '\u0001', high: '\u0002'}).replace('\u0001', F(Q + '.travel.low', o.travel.low, 'num'))
          .replace('\u0002', F(Q + '.travel.high', o.travel.high, 'num'))}, ${bandMark(o, Q)}</span></a>
      ${tel ? `<a class="btn btn-go-line call" href="${tel}" aria-label="${esc(t('ans.call_name', {name: o.name}))}">${icon('phone')}</a>` : ''}</li>`;
  }).join('');
  return `<section class="section" aria-labelledby="h-no"><h2 id="h-no">${T('ans.if_no')}</h2><ol class="rows">${rows}</ol></section>`;
}
function groups(stops) {
  const g = [];
  stops.forEach((s, k) => { if (g.length && g[g.length - 1].s.facility_id === s.facility_id) g[g.length - 1].ks.push(k); else g.push({s, ks: [k]}); });
  return g;
}
function routeSection(p) {
  const it = p.itinerary, r = it && it.plans[0];
  if (!r) return '';
  const R = 'itinerary.plans.0', c = r.window_checks[0];
  const stopLi = (s, k) => `<li><b lang="en">${F(`${R}.stops.${k}.name`, s.name)}</b>
    <span>${E(`${R}.stops.${k}.purpose_word`, s.purpose_word)}${c ? `, ${t('ans.stop_eta', {low: '\u0001', high: '\u0002'})
      .replace('\u0001', F(`${R}.stops.${k}.eta_low`, s.eta_low, 'num')).replace('\u0002', F(`${R}.stops.${k}.eta_high`, s.eta_high, 'num'))}` : ''}</span></li>`;
  if (!c) {  // planned care: the steps, no clock
    return `<section class="section" aria-labelledby="h-route"><h2 id="h-route">${T('ans.steps_h')}</h2>
      <div class="panel"><p class="muted small">${E('itinerary.pathway_name', it.pathway_name)}</p>
      <ol class="stops">${r.stops.map(stopLi).join('')}</ol></div></section>`;
  }
  const lanes = groups(r.stops);
  const span = 1.1 * Math.max(c.limit_minutes, ...lanes.map(l => l.s.eta_high));
  const x = m => +(100 * m / span).toFixed(2);
  const wx = x(c.limit_minutes);
  const line = lanes.map((l, k) => `<line class="eta" x1="${x(l.s.eta_low)}%" x2="${x(l.s.eta_high)}%" y1="24" y2="24"/>`).join('');
  const nodes = lanes.map((l, k) => `<circle class="stop${k === 0 ? ' now' : ''}" cx="${x(l.s.eta_low)}%" cy="24" r="7"/>`).join('');
  const labs = lanes.map((l, k) => {
    const left = x(l.s.eta_low) < 50;
    return `<span class="strip-lab" aria-hidden="true" style="${left ? `left:calc(${x(l.s.eta_low)}% - 7px)` : `right:0;text-align:right`}">${k + 1}. ${esc(shortName(l.s.name))}
      <span class="num">${l.s.eta_low}-${l.s.eta_high}</span></span>`;
  }).join('');
  const met = c.met;
  return `<section class="section" aria-labelledby="h-route"><h2 id="h-route">${T('ans.route_h')}</h2>
    <div class="panel route">
      <div class="strip" aria-hidden="true">
        <svg><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="6" fill="var(--hazard)" opacity=".5"/></pattern></defs>
          <rect class="late" x="${wx}%" y="12" width="${(100 - wx).toFixed(2)}%" height="24"/><line class="limit" x1="${wx}%" x2="${wx}%" y1="2" y2="44"/>
          ${line}<line class="path" x1="0" x2="${x(lanes[lanes.length - 1].s.eta_low)}%" y1="24" y2="24" pathLength="1"/>
          <circle cx="0" cy="24" r="4" fill="var(--text)"/>${nodes}</svg>
        <span class="strip-limit" style="left:calc(${wx}% + 4px)">${esc(String(c.limit_minutes))} ${T('ans.min')}</span>${labs}
      </div>
      <ol class="stops">${lanes.map(l => stopLi(l.s, l.ks[0])).join('')}</ol>
      <p class="window${met ? '' : ' miss'}">${icon(met ? 'ok' : 'warn')}<span>${t(met ? 'ans.window_met' : 'ans.window_miss', {eta: '\u0001', limit: '\u0002'})
        .replace('\u0001', F(`${R}.window_checks.0.eta_minutes`, c.eta_minutes, 'num')).replace('\u0002', F(`${R}.window_checks.0.limit_minutes`, c.limit_minutes, 'num'))}
        <span class="vh">${F(`${R}.window_checks.0.met`, met ? 'met' : 'not met', 'met')}</span></span></p>
      <ul class="legend"><li><span class="sw sw-route"></span>${T('ans.legend_route')}</li><li><span class="sw sw-range"></span>${T('ans.legend_range')}</li>
        <li><span class="sw sw-late"></span>${T('ans.legend_late', {limit: c.limit_minutes})}</li></ul>
    </div></section>`;
}
const shortName = n => n.replace(/^(Sub Divisional|District) Hospital /, 'SDH ').replace(/ Hospital.*$/, '');

function plan(name) {
  const p = S.data[name];
  S.plan = name;
  const o = p.options[0];
  return `${isEmergency(p) ? sosBar(p) : ''}<main id="main" tabindex="-1">
    <h1 tabindex="-1">${T('svc.' + p.query.service)}</h1>
    <p class="note" style="margin-top:var(--sp1)"><span data-device>${T('ans.near', {place: place(p), date: fmtDate(p.as_of)})}</span></p>
    <div style="margin-top:var(--sp4)">${answerPanel(p, o)}</div>
    ${nextRows(p)}
    ${routeSection(p)}
    <p class="note section">${T('ans.not_advice')} ${F('field_reports.note.' + S.lang, p.field_reports.note[S.lang])}</p>
  </main>`;
}

function why(name, rank) {
  const p = S.data[name];
  S.plan = name;
  const i = p.options.findIndex(x => x.rank === rank);
  const o = p.options[i], Q = `options.${i}`;
  const ctx = {label_hi: p.query.service_label.hi};
  const tel = telOf(o);
  const quotes = o.evidence.map((e, j) => `<blockquote lang="en"><p class="from" lang="${S.lang}">${T('why.quote_from')}</p>
      <p>"${F(`${Q}.evidence.${j}.quote`, e.quote)}"</p>
      <div class="quote-tools"><a href="${esc(e.source_url)}" rel="noopener noreferrer" lang="${S.lang}">${T('why.source')}</a>
        ${S.lang === 'hi' ? `<button type="button" class="btn tr-btn" lang="hi" data-tr="${j}">${T('why.translate')}</button>` : ''}</div>
      <div class="tr-out" aria-live="polite" lang="hi"></div></blockquote>`).join('');
  const tr = o.track_record, TR = `${Q}.track_record`;
  const pct = v => (100 * v / tr.n).toFixed(1);
  const track = tr ? `<p>${t('why.track', {n: '\u0001', k: '\u0002', c: '\u0003', u: '\u0004'})
      .replace('\u0001', F(TR + '.n', tr.n, 'num')).replace('\u0002', F(TR + '.k_confirmed', tr.k_confirmed, 'num'))
      .replace('\u0003', F(TR + '.k_contradicted', tr.k_contradicted, 'num')).replace('\u0004', F(TR + '.k_no_info', tr.k_no_info, 'num'))}</p>
    <div class="track-bar" aria-hidden="true"><i class="tb-k" style="width:${pct(tr.k_confirmed)}%"></i><i class="tb-c" style="width:${pct(tr.k_contradicted)}%"></i><i class="tb-u" style="width:${pct(tr.k_no_info)}%"></i></div>
    <ul class="track-key" aria-hidden="true"><li><span class="sw tb-k"></span>${T('why.track_k')}</li><li><span class="sw tb-c"></span>${T('why.track_c')}</li><li><span class="sw tb-u"></span>${T('why.track_u')}</li></ul>` : '';
  const whyNot = (p.why_not || []).map((w, k) => `<li><b lang="en">${F(`why_not.${k}.name`, w.name)}</b>,
      ${F(`why_not.${k}.travel.km`, Math.round(w.travel.km), 'num')} ${T('ans.km')}${T('punct.stop')} ${E(`why_not.${k}.reason`, w.reason)}${T('punct.stop')}</li>`).join('');
  const wc = p.what_would_change;
  const change = wc && wc.kind === 'first_says_no' ? `<p style="margin-top:var(--sp3)">${t('why.change', {first: '\u0001', name: '\u0002'})
    .replace('\u0001', `<span lang="en">${F('what_would_change.first_name', wc.first_name)}</span>`).replace('\u0002', `<span lang="en">${F('what_would_change.name', wc.name)}</span>`)}</p>` : '';
  const total = o.contributions.reduce((a, c) => a + c.points, 0);
  const sign = n => (n > 0 ? '+' : '');
  return `<main id="main" tabindex="-1">
    <a class="back" href="#/plan/${name}">${icon('back')} ${T('why.back')}</a>
    <header class="why-head" style="margin-top:var(--sp2)"><h1 tabindex="-1" lang="en">${F(Q + '.name', o.name)}</h1>
      <p>${bandMark(o, Q)} <span class="muted">${F(Q + '.town', o.town)}. ${opLabel(o)}</span></p></header>

    <section class="section" aria-labelledby="h-q"><h2 id="h-q">${T('why.quotes_h')}</h2>${quotes}</section>
    <section class="section" aria-labelledby="h-fam"><h2 id="h-fam">${T('why.family_h')}</h2>
      <p class="panel">${E(Q + '.say_to_family.en', o.say_to_family.en, ctx)}</p></section>
    <section class="section" aria-labelledby="h-ask"><h2 id="h-ask">${T('why.ask_h')}</h2>
      ${tel ? `<a class="btn btn-go btn-block btn-big" href="${tel}">${icon('phone')} ${T('ans.call')} <span class="num">${F(Q + '.phone.display', o.phone.display)}</span></a>` : ''}
      <ol class="qs" style="margin-top:var(--sp4)">${o.call_ahead.map((c, j) => `<li>${E(`${Q}.call_ahead.${j}.question`, c.question, ctx)}
        <span class="because">${t('why.ask_because', {why: '\u0001'}).replace('\u0001', E(`${Q}.call_ahead.${j}.asked_because`, c.asked_because))}</span></li>`).join('')}</ol>
      <h3 style="margin-top:var(--sp5)">${T('why.outcome_h')}</h3>
      <div class="outcomes" role="group" aria-label="${T('why.outcome_h')}">${['yes', 'no', 'none', 'wrong'].map(k => `<button type="button" class="btn" aria-pressed="false" data-out="${k}">${T('why.out.' + k)}</button>`).join('')}</div>
      <p class="note">${T('why.out_note')}</p></section>
    ${tr ? `<section class="section" aria-labelledby="h-tr"><h2 id="h-tr">${T('why.track_h')}</h2>${track}</section>` : ''}
    ${whyNot ? `<section class="section" aria-labelledby="h-wn"><h2 id="h-wn">${T('why.whynot_h')}</h2><ul class="rows whynot">${whyNot}</ul>${change}</section>` : ''}
    <section class="section" aria-labelledby="h-led"><h2 id="h-led">${T('why.ledger_h')}</h2>
      <table class="ledger"><thead><tr><th scope="col">${T('why.ledger_col')}</th><th scope="col" class="pts">${T('why.ledger_pts')}</th></tr></thead>
        <tbody>${o.contributions.map((c, j) => `<tr><td>${E(`${Q}.contributions.${j}.label`, c.label)}</td><td class="pts">${F(`${Q}.contributions.${j}.points`, sign(c.points) + c.points, 'num')}</td></tr>`).join('')}</tbody>
        <tfoot><tr><th scope="row">${T('why.ledger_total')}</th><td class="pts">${F(Q + '.contributions', sign(total) + total, 'sum')}</td></tr></tfoot></table></section>
    <section class="section" aria-labelledby="h-chk"><h2 id="h-chk">${T('why.checks_h')}</h2><dl class="facts">
      <div><dt>${T('why.real')}</dt><dd>${o.is_real.map((x, j) => E(`${Q}.is_real.${j}`, x)).join('; ')}</dd></div>
      <div><dt>${T('why.where')}</dt><dd>${E(Q + '.where_check', o.where_check)}</dd></div>
      ${o.flags.map((f, j) => `<div><dt>${T('why.warn')}</dt><dd class="warn">${icon('warn')}<span>${E(`${Q}.flags.${j}`, f)}</span></dd></div>`).join('')}
      <div><dt>${T('why.field')}</dt><dd>${F('field_reports.note.' + S.lang, p.field_reports.note[S.lang])}</dd></div></dl></section>
    <section class="section stack" aria-labelledby="h-act"><h2 id="h-act">${T('why.actions_h')}</h2>
      <a class="btn btn-block" href="#/stub/slip">${T('why.slip')}</a>
      <a class="btn btn-block" href="#/stub/family">${T('why.family')}</a>
      <a class="btn btn-block" href="https://www.google.com/maps/dir/?api=1&amp;destination=${o.lat},${o.lon}" rel="noopener noreferrer">${T('why.maps')}</a>
      <button type="button" class="btn btn-block">${T('why.web')}</button><p class="note">${T('why.web_note')}</p></section>
  </main>`;
}
// Stand-in for translate.js (PR #109): the app asks /api/translate; the prototype shows a fixed rendering.
const DEMO_TR = {'Emergency services available': 'इमरजेंसी सेवाएँ उपलब्ध हैं', 'Has 32+ emergency services': '32 से ज़्यादा इमरजेंसी सेवाएँ हैं',
  'Hemodialysis is performed in the Hemodialysis Unit': 'हीमोडायलिसिस, हीमोडायलिसिस यूनिट में किया जाता है', 'Hemodialysis treatment is provided': 'हीमोडायलिसिस का इलाज दिया जाता है',
  'Hemodialysis unit available': 'हीमोडायलिसिस यूनिट उपलब्ध है'};
function bindWhy() {
  document.querySelectorAll('[data-out]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-out]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    announce(b.textContent);
  }));
  document.querySelectorAll('[data-tr]').forEach(b => b.addEventListener('click', () => {
    const bq = b.closest('blockquote'), q = bq.querySelector('[data-f$=".quote"]').textContent;
    bq.querySelector('.tr-out').innerHTML = `<p class="from">मशीन से अनुवाद, जाँचा नहीं गया</p><p>${esc(DEMO_TR[q] || 'अनुवाद अभी उपलब्ध नहीं')}</p>`;
  }));
}

function settings() {
  const radio = (name, v, label, cur, extra = '') => `<label ${extra}><input type="radio" name="${name}" id="${name}-${v}" value="${v}" ${String(cur) === String(v) ? 'checked' : ''}> <span>${label}</span></label>`;
  return `<main id="main" tabindex="-1">
    <h1 tabindex="-1">${T('set.h')}</h1>
    <fieldset class="section"><legend>${T('set.lang_h')}</legend><div class="choice">
      ${radio('lang', 'hi', 'हिन्दी', S.lang, 'lang="hi"')}${radio('lang', 'en', 'English', S.lang, 'lang="en"')}</div>
      <p class="note">${T('set.lang_note')}</p></fieldset>
    <fieldset class="section"><legend>${T('set.size_h')}</legend><div class="seg">
      ${[100, 125, 150].map(v => radio('size', v, `<span class="num">${v}</span>%`, S.size)).join('')}</div>
      <p class="panel" style="margin-top:var(--sp3)" lang="en">${T('set.size_sample')}</p></fieldset>
    <fieldset class="section"><legend>${T('set.voice_h')}</legend>
      <label class="check"><input type="checkbox" id="opt-read" ${S.read ? 'checked' : ''}> ${T('set.read')}</label>
      <label class="check"><input type="checkbox" id="opt-mic" ${S.mic ? 'checked' : ''}> ${T('set.mic')}</label></fieldset>
    <fieldset class="section"><legend>${T('set.theme_h')}</legend><div class="seg">
      ${['system', 'light', 'dark'].map(v => radio('theme', v, T('set.theme.' + v), S.theme)).join('')}</div></fieldset>
    <section class="section" aria-labelledby="h-off"><h2 id="h-off">${T('set.offline_h')}</h2>
      <p>${T('set.offline', {state: S.lang === 'hi' ? 'बिहार' : 'Bihar', date: fmtDate('2026-11-21')})}</p>
      <button type="button" class="btn btn-block" style="margin-top:var(--sp3)">${T('set.offline_btn')}</button></section>
  </main>`;
}
function bindSettings() {
  document.querySelectorAll('input[name=lang]').forEach(r => r.addEventListener('change', () => setLang(r.value, true, '#lang-' + r.value)));
  document.querySelectorAll('input[name=size]').forEach(r => r.addEventListener('change', () => { S.size = +r.value; store.set('size', S.size); applyPrefs(); }));
  document.querySelectorAll('input[name=theme]').forEach(r => r.addEventListener('change', () => { S.theme = r.value; store.set('theme', S.theme); applyPrefs(); }));
  $('#opt-read').addEventListener('change', e => { S.read = e.target.checked; store.set('read', S.read); });
  $('#opt-mic').addEventListener('change', e => { S.mic = e.target.checked; store.set('mic', S.mic); });
}

function offline(name) {
  const p = S.data[name];
  // pack.js ranks by straight-line km; the prototype does the same with the saved payload's points.
  const km = o => {
    const R = 6371, d = Math.PI / 180, a = p.location, la = (o.lat - a.lat) * d, lo = (o.lon - a.lon) * d;
    return 2 * R * Math.asin(Math.sqrt(Math.sin(la / 2) ** 2 + Math.cos(a.lat * d) * Math.cos(o.lat * d) * Math.sin(lo / 2) ** 2));
  };
  const opts = [...p.options].sort((a, b) => km(a) - km(b));
  const o = opts[0], tel = telOf(o);
  return `${isEmergency(p) ? sosBar(p) : ''}<main id="main" tabindex="-1">
    <h1 tabindex="-1">${T('svc.' + p.query.service)}</h1>
    <div class="offline section" role="status">${icon('wifiOff')}<div><b>${T('off.h')}</b><p>${T('off.what', {date: fmtDate('2026-11-21')})}</p></div></div>
    <p class="section" style="margin-top:var(--sp3)">${T('off.next')}</p>
    <button type="button" class="btn btn-block" style="margin-top:var(--sp3)">${T('off.retry')}</button>
    <section class="panel answer section${o.band === 'likely' ? ' likely' : ''}" aria-labelledby="h-first">
      <h2 id="h-first">${T('ans.call_first')}</h2><p class="name" lang="en">${esc(o.name)}</p><p class="place">${esc(o.town)}. ${opLabel(o)}</p>
      <p class="readout"><span class="big">${km(o).toFixed(1)}</span><span class="unit">${T('ans.km')}</span><span class="sub">${T('off.straight', {km: km(o).toFixed(1)})}</span></p>
      <p class="sure ${o.band === 'likely' ? 'sure-ok' : 'sure-nv'}">${bandSvg(o.band)}<span>${T('band.' + o.band)}${T('punct.stop')} ${T('ans.sure.' + (o.model_band === 'NO_SERVICE_TEXT' ? 'no_text' : o.band))}</span></p>
      ${tel ? `<a class="btn btn-go btn-block btn-big" href="${tel}">${icon('phone')} ${T('ans.call')} <span class="num">${esc(o.phone.display)}</span></a>` : ''}</section>
    <section class="section" aria-labelledby="h-no"><h2 id="h-no">${T('ans.if_no')}</h2><ol class="rows">${opts.slice(1, 3).map(x => `<li class="next-row">
      <span class="rank num">${x.rank}</span><span class="nm" style="flex:1"><b lang="en" style="display:block;font-weight:600">${esc(x.name)}</b>
      <span class="muted small">${T('off.straight', {km: km(x).toFixed(1)})}, ${T('band.' + x.band)}</span></span>
      ${telOf(x) ? `<a class="btn btn-go-line call" href="${telOf(x)}" aria-label="${esc(t('ans.call_name', {name: x.name}))}">${icon('phone')}</a>` : ''}</li>`).join('')}</ol></section>
    <p class="note section">${T('off.age', {days: 1})}</p>
  </main>`;
}
function stub(key) {
  const title = {recent: 'nav.recent', area: 'nav.area', how: 'nav.how'}[key] || ('svc.' + key);
  return `<main id="main" tabindex="-1"><h1 tabindex="-1">${T(S.strings.en[title] ? title : 'proto.screens')}</h1>
    <p class="section">${T('proto.stub')}</p><a class="btn btn-block section" href="#/">${T('nav.home')}</a></main>`;
}
function index() {
  const links = [['#/lang', 'Language chooser'], ['#/', 'Home'], ['#/plan/trauma', 'Emergency answer: Pusa trauma'],
    ['#/plan/dialysis', 'Planned answer: Patna dialysis'], ['#/why/trauma/1', 'Why page: Pusa'], ['#/settings', 'Settings'], ['#/offline/trauma', 'Offline']];
  return `<main id="main" tabindex="-1"><h1 tabindex="-1">${T('proto.screens')}</h1>
    <ul class="proto-list rows section">${links.map(([h, l]) => `<li><a href="${h}" lang="en">${l}</a></li>`).join('')}</ul></main>`;
}

// ---------- read aloud (speech.js in the app; templates from the strings file) ----------
function speakText(p) {
  const [a, b] = p.options;
  const sure = t('band.' + a.band) + t('punct.stop') + ' ' + t('ans.sure.' + (a.model_band === 'NO_SERVICE_TEXT' ? 'no_text' : a.band));
  return [isEmergency(p) ? t('speak.108') : '', t('speak.first', {name: a.name, low: a.travel.low, high: a.travel.high, sure}),
    b ? t('speak.next', {name: b.name, low: b.travel.low, high: b.travel.high}) : ''].filter(Boolean).join(' ');
}
function bindListen() {
  const b = $('#listen');
  if (!b) return;
  if (!('speechSynthesis' in window)) { b.disabled = true; return; }
  b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') === 'true';
    speechSynthesis.cancel();
    const set = v => { b.setAttribute('aria-pressed', String(v)); b.querySelector('span').textContent = t(v ? 'ans.stop' : 'ans.listen'); };
    if (on) { set(false); return; }
    const u = new SpeechSynthesisUtterance(speakText(S.data[S.plan]));
    u.lang = S.lang === 'hi' ? 'hi-IN' : 'en-IN';
    u.onend = () => set(false);
    set(true);
    speechSynthesis.speak(u);
  });
}

// ---------- language, prefs, router ----------
function announce(text) { const s = $('#status'); s.textContent = ''; setTimeout(() => { s.textContent = text; }, 50); }
function setLang(l, rerender = true, focusSel = '#lang-btn') {
  S.lang = l;
  store.set('lang', l);
  document.documentElement.lang = l;
  if (!rerender) return;
  const y = window.scrollY;
  render({keepFocus: true});
  window.scrollTo(0, y);
  $(focusSel)?.focus({preventScroll: true});
}
function applyPrefs() {
  const html = document.documentElement;
  html.style.fontSize = S.size === 100 ? '' : S.size + '%';
  if (S.theme === 'system') html.removeAttribute('data-theme'); else html.dataset.theme = S.theme;
}
function render(opts = {}) {
  const h = location.hash || '#/';
  if (!S.lang && h !== '#/lang') { location.hash = '#/lang'; return; }
  const m = h.match(/^#\/(\w+)(?:\/(\w+))?(?:\/(\d+))?/) || [];
  const [route, arg, num] = [m[1] || '', m[2], m[3]];
  document.body.classList.toggle('bare', route === 'lang');
  let body, bind = () => {}, nav = route === 'plan' || route === 'why' || route === 'offline' ? 'home' : route || 'home';
  if (route === 'lang') [body, bind] = [chooser(), bindChooser];
  else if (route === 'plan' && S.data[arg]) [body, bind] = [plan(arg), bindListen];
  else if (route === 'why' && S.data[arg]) [body, bind] = [why(arg, +num || 1), bindWhy];
  else if (route === 'settings') [body, bind] = [settings(), bindSettings];
  else if (route === 'offline' && S.data[arg]) body = offline(arg);
  else if (route === 'index') body = index();
  else if (['recent', 'area', 'how', 'stub'].includes(route)) body = stub(arg || route);
  else body = home();
  $('#app').innerHTML = route === 'lang' ? body : topBar() + body + bottomNav(nav);
  document.title = ($('#main h1')?.textContent.trim() || '') + ' - ' + t('app.name');
  bind();
  $('#lang-btn')?.addEventListener('click', e => setLang(e.currentTarget.dataset.lang));
  $('#skip')?.addEventListener('click', e => { e.preventDefault(); $('#main').focus(); });
  if (!opts.keepFocus) ($('#main h1[tabindex]') || $('#main'))?.focus({preventScroll: true});
  if (route === 'plan' && S.data[arg]) announce(t('ans.found', {n: S.data[arg].options.length, name: S.data[arg].options[0].name}));
}

async function start() {
  const q = new URLSearchParams(location.search);
  const get = async u => (await fetch(u)).json();
  [S.strings.en, S.strings.hi, S.data.trauma, S.data.dialysis] = await Promise.all(
    ['i18n/en.json', 'i18n/hi.json', 'data/trauma.json', 'data/dialysis.json'].map(get));
  S.lang = q.get('lang') || store.get('lang');
  S.size = +(q.get('size') || store.get('size') || 100);
  S.theme = q.get('theme') || store.get('theme') || 'system';
  S.read = store.get('read') ?? true;
  S.mic = store.get('mic') ?? true;
  if (S.lang) document.documentElement.lang = S.lang;
  applyPrefs();
  window.addEventListener('hashchange', () => render());
  render();
}
start().catch(e => { document.body.textContent = 'Could not load the prototype data: ' + e.message + '. Serve this folder over http.'; });
