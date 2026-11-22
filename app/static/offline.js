// Offline answer (spec S9, section 3.2.3; issue #23). Plain script, attaches window.RSOffline.
// Packs live in IndexedDB, kept by the service worker (sw.js). Loaded lazily by app.js (never on the critical path); the service worker precaches it with pack.js.
// Answers only from the state packs saved on this phone (the home state plus every state with a facility within the
// search radius); shows no number the packs do not contain.
'use strict';
(function (root) {
  const KEY = 'rs.pack';  // home {slug, state, built, saved_at, persisted}, packs: {slug: {state, saved_at, seen}}
  const DAY = 86400000;
  const FRESH_FIX_MS = 6 * 3600000;  // spec 3.2.3 step 1: older fixes need "Patient is here"
  const ACCEPT_M = 1000;  // step 2: accept a satellite fix of 1,000 m or better
  const GRACE_MS = 30 * DAY;  // a neighbour pack no fix has needed for this long is dropped

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function meta() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } }
  function setMeta(m) { try { localStorage.setItem(KEY, JSON.stringify(m)); } catch { /* private mode */ } }
  function daysAgo(t) { return Math.max(0, Math.floor((Date.now() - t) / DAY)); }
  function dateStr(t) {  // the app language (rs.lang), not the phone's
    const hi = typeof state !== 'undefined' && state.lang === 'hi';
    return new Date(t).toLocaleDateString(hi ? 'hi-IN' : 'en-IN', {day: 'numeric', month: 'short'});
  }

  // Indian numbers in the pack are 10 digits (mobile or STD code + number) or toll-free 1800; anything else gets no
  // tel: link.
  function telHref(raw) {
    const d = String(raw || '').replace(/[\s\-().]/g, '');
    if (/^[1-9]\d{9}$/.test(d)) return 'tel:+91' + d;
    if (/^0[1-9]\d{9}$/.test(d)) return 'tel:+91' + d.slice(1);
    if (/^\+91[1-9]\d{9}$/.test(d)) return 'tel:' + d;
    if (/^1800\d{6,8}$/.test(d)) return 'tel:' + d;  // toll-free, dialled as is in India
    return null;
  }

  // ---------- saving the packs (online, in the background) ----------
  function toWorker(reg, msg) {
    return new Promise(resolve => {
      const ch = new MessageChannel();
      ch.port1.onmessage = e => resolve(e.data);
      reg.active.postMessage(msg, [ch.port2]);
      setTimeout(() => resolve({status: 'timeout'}), 60000);
    });
  }

  // Saves the home pack and every pack /api/pack/locate names for this fix; drops packs no fix has needed for
  // GRACE_MS. Returns the home pack's status.
  async function savePack(lat, lon) {
    if (!('serviceWorker' in navigator)) return {status: 'no-service-worker'};
    const r = await fetch('/api/pack/locate', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lat: +lat.toFixed(2), lon: +lon.toFixed(2)}), redirect: 'manual'});
    if (!r.ok) return {status: 'no-pack'};
    const loc = await r.json();
    const want = loc.packs || [{slug: loc.slug, state: loc.state}];
    const reg = await navigator.serviceWorker.ready;
    const old = meta();
    const now = Date.now();
    const packs = Object.assign({}, old && old.packs);
    let home = null;
    for (const w of want) {
      const res = await toWorker(reg, {type: 'cache-pack', slug: w.slug});
      if (w.slug === loc.slug) home = res;
      if (res.status !== 'saved' && res.status !== 'unchanged') continue;
      const prev = packs[w.slug];
      packs[w.slug] = {state: w.state, seen: now, saved_at: res.status === 'saved' || !prev ? now : prev.saved_at};
    }
    for (const slug of Object.keys(packs)) {
      if (slug !== loc.slug && now - packs[slug].seen > GRACE_MS) {
        await toWorker(reg, {type: 'drop-pack', slug});
        delete packs[slug];
      }
    }
    if (home.status === 'saved' || home.status === 'unchanged') {
      const fresh = home.status === 'saved' || !old || old.slug !== loc.slug;
      // Ask once that the browser not evict the packs under storage pressure (#32). Chrome grants it silently
      // for installed or engaged sites; Firefox may prompt. A refusal changes nothing else.
      const persisted = old && old.persisted ? true : await persist();
      setMeta({slug: loc.slug, state: loc.state, sha256: home.sha256, persisted, packs,
        saved_at: fresh ? now : old.saved_at, built: old && !fresh ? old.built : null});
    } else if (old) {
      setMeta(Object.assign({}, old, {packs}));
    }
    return home;
  }

  async function persist() {
    try {
      const sm = navigator.storage;
      if (!sm || !sm.persist) return false;
      return (await sm.persisted()) || (await sm.persist());
    } catch { return false; }
  }

  // The home pack, decoded, with .packs holding every saved pack (home first) for answer() and resolvePin().
  async function loadPack() {
    const m = meta();
    if (!m) return null;
    const get = slug => fetch('/api/pack/' + slug).then(r => r.ok ? r.json() : null).catch(() => null);
    const home = await get(m.slug);
    if (!home) return null;
    const pack = root.RSPack.decode(home);
    if (m.built !== pack.built) setMeta(Object.assign({}, m, {built: pack.built}));
    const others = await Promise.all(Object.keys(m.packs || {}).filter(s => s !== m.slug).map(get));
    return Object.assign({}, pack, {packs: [pack].concat(others.filter(Boolean).map(root.RSPack.decode))});
  }

  function titleCase(s) { return String(s || '').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()); }

  // ---------- offline place picker from the pack ----------
  function resolvePin(pack, pin) {
    for (const p of pack.packs || [pack]) {
      const i = p.pins.pin.indexOf(+pin);
      if (i < 0) continue;
      // A PIN the gazetteer files under no district is stored with district "": name the state, as online does.
      const where = titleCase(p.districts[p.pins.d[i]]) || titleCase(p.state);
      return {lat: p.pins.lat[i], lon: p.pins.lon[i], label: [`PIN ${pin}`, where].filter(Boolean).join(', ')};
    }
    return null;
  }
  // The district's own PIN point nearest the mean of its PIN points. A plain mean can lie nearer another district's
  // PINs, so the area view named that district (Anakapalli gave Visakhapatnam). Same rule as facts/places.py
  // district_centre: integers on the pack's 0.001 degree grid, longitude scaled by cos(lat), lowest PIN on a tie,
  // so the centre is the same PIN online and offline. pins.not_centre, PINs the area view names another district
  // for after the LGD correction (facts/places.py kept_pins), are left out unless that leaves none.
  function districtCentre(pack, d) {
    const di = pack.districts.indexOf(d), P = pack.pins, G = 1000, out = new Set(P.not_centre || []), all = [];
    P.d.forEach((x, i) => { if (x === di) all.push(i); });
    if (!all.length) return null;
    const kept = all.filter(i => !out.has(P.pin[i])), own = kept.length ? kept : all;
    const qa = own.map(i => Math.round(P.lat[i] * G)), qo = own.map(i => Math.round(P.lon[i] * G));
    const n = own.length, sa = qa.reduce((t, v) => t + v, 0), so = qo.reduce((t, v) => t + v, 0);
    const k = Math.cos(sa / n / G * Math.PI / 180);
    const d2 = j => (n * qa[j] - sa) ** 2 + ((n * qo[j] - so) * k) ** 2;
    let b = 0;
    for (let j = 1; j < n; j++) if (d2(j) < d2(b) || (d2(j) === d2(b) && P.pin[own[j]] < P.pin[own[b]])) b = j;
    return {lat: P.lat[own[b]], lon: P.lon[own[b]], label: `${titleCase(d)} district centre`};
  }

  // ---------- satellite fix while offline (spec 3.2.3 step 2) ----------
  function watchSatellite(onFix) {
    if (!('geolocation' in navigator)) return () => {};
    const id = navigator.geolocation.watchPosition(p => {
      if (p.coords.accuracy <= ACCEPT_M) {
        navigator.geolocation.clearWatch(id);
        onFix({lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy),
          source: 'gps', t: Date.now(), label: null});
      }
    }, () => {}, {enableHighAccuracy: true, maximumAge: 0, timeout: 120000});
    return () => navigator.geolocation.clearWatch(id);
  }
  function fixIsFresh(loc) { return !!loc && (loc.source !== 'gps' || Date.now() - loc.t < FRESH_FIX_MS); }

  // ---------- the S9 screen ----------
  function answer(pack, loc, service) {
    const res = root.RSPack.queryAll(pack.packs || [pack], loc.lat, loc.lon, service);
    return Object.assign(res, {state: res.state || pack.state, band_note: pack.band_note});
  }

  function render(o, ctx) {
    // ctx: {serviceLabel, locLine (already escaped HTML), show102, fresh, hasPack, gettingGps, reason}
    const t = (k, v) => root.th(k, v);
    const m = meta();
    // The oldest saved pack sets the age warning; build dates are listed per state when they differ.
    const savedAt = m ? Math.min(m.saved_at, ...Object.values(m.packs || {}).map(x => x.saved_at)) : null;
    const age = m ? daysAgo(savedAt) : null;
    const builts = o && o.packs ? [...new Set(o.packs.map(x => x.built))] : [];
    const built = builts.length > 1 ? o.packs.map(x => `${x.built} (${titleCase(x.state)})`).join(', ')
      : o && o.built || m && m.built || '?';
    const ageClass = age == null ? '' : age > 90 ? 'stale-red' : age > 30 ? 'stale-amber' : '';
    const dates = m ? `<p class="note ${ageClass}">${t('off.built', {built: esc(built), saved: dateStr(savedAt),
      age: age === 0 ? t('off.today') : t(age === 1 ? 'off.day_ago' : 'off.days_ago', {n: age})})}
      ${age > 90 ? `<strong>${t('off.phones_changed')}</strong>` : ''}</p>` : '';
    const head = `<h1 tabindex="-1">${esc(ctx.serviceLabel)}</h1>${dates}`;
    const gps = ctx.gettingGps ? `<p role="status">${t('gps.wait')}</p>` : '';
    const choose = `<a class="btn btn-block section" href="#/change">${t('home.choose_place')}</a>`;
    if (!m || !ctx.hasPack) return head + `<p class="panel">${t('off.no_pack')}</p>${choose}`;
    if (!ctx.fresh || !o) {
      return head + gps + `<p>${t('off.old_fix', {loc: ctx.locLine})}</p>
        <button type="button" class="btn btn-ink btn-block" id="patient-here">${t('off.patient_here')}</button>${choose}`;
    }
    const prov = String(o.band_note || '').startsWith('placeholder') ? `<p class="note">${t('off.provisional')}</p>` : '';
    const cards = o.options.length ? o.options.map((x, i) => card(x, i + 1, ctx.serviceLabel, o.state)).join('')
      : `<p class="panel">${t('off.none_near', {label: esc(ctx.serviceLabel)})}</p>`;
    return head + gps + `<p class="note">${t('off.pin_line', {loc: ctx.locLine, pin: esc(o.pin), district: esc(titleCase(o.district)), km: esc(o.km_to_pin)})}</p>
      <h2 class="section">${t('off.call_before')}</h2>${prov}${cards}
      <p class="note section">${t('off.needs_net', {states: esc([...new Set((o.packs || [o]).map(x => titleCase(x.state)))].join(', '))})}</p>${choose}`;
  }

  function card(x, n, label, userState) {
    const t = (k, v) => root.th(k, v);
    const b = x.likely ? 'likely' : 'not_verified';
    const band = `<span class="band band-${b}">${t('band.' + b)}</span>`;
    const tel = telHref(x.tel);
    const quotes = x.quotes.length ? x.quotes.map(q => `<blockquote${q.claim_id ? ` data-claim="${esc(q.claim_id)}"` : ''}><p lang="en">"${esc(q.text)}"</p></blockquote>`).join('')
      : `<p class="note">${t('why.no_quote', {label: esc(label)})}</p>`;
    const sms = 'sms:?body=' + encodeURIComponent(root.ts('off.sms', {label, name: x.name, km: x.km_straight,
      phone: tel ? root.ts('off.sms_phone', {phone: tel.slice(4)}) : ''}));
    const where = x.state && userState && x.state !== userState ? t('off.in_state', {state: esc(titleCase(x.state))}) + ' ' : '';
    return `<article class="card answer${x.likely ? ' likely' : ''} section" aria-labelledby="off-${n}"><p class="kicker">${n}. ${band}</p>
      <h3 id="off-${n}" class="name" lang="en">${esc(x.name)}</h3>
      <p>${where}${t('off.straight', {km: esc(x.km_straight)})}${x.loc_low ? ' ' + t('off.map_wrong') : ''}</p>
      ${x.listings > 1 ? `<p class="note">${t('off.listed', {n: esc(x.listings)})}</p>` : ''}
      ${quotes}
      ${tel ? `<a class="btn btn-go btn-block btn-big" href="${esc(tel)}">${root.rsIcon('phone')} ${t('ans.call')}
        <span class="visually-hidden"> ${esc(x.name)}</span></a>${x.tel_dir ? `<p class="note">${t('off.directory')}</p>` : ''}`
        : `<p class="note">${t('ans.no_phone')}</p>`}
      <a class="btn btn-block" href="${esc(sms)}">${t('off.send_sms')} <span class="visually-hidden">${esc(x.name)}</span></a>
    </article>`;
  }

  root.RSOffline = {savePack, loadPack, resolvePin, districtCentre, watchSatellite, fixIsFresh,
    answer, render, telHref, meta};
})(typeof window !== 'undefined' ? window : globalThis);
