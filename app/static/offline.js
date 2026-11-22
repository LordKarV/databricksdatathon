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
  function dateStr(t) { return new Date(t).toLocaleDateString([], {day: 'numeric', month: 'short'}); }

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
      if (i >= 0) return {lat: p.pins.lat[i], lon: p.pins.lon[i], label: `PIN ${pin}, ${titleCase(p.districts[p.pins.d[i]])}`};
    }
    return null;
  }
  function districtCentre(pack, d) {
    const di = pack.districts.indexOf(d);
    let n = 0, la = 0, lo = 0;
    pack.pins.d.forEach((x, i) => { if (x === di) { n++; la += pack.pins.lat[i]; lo += pack.pins.lon[i]; } });
    return n ? {lat: la / n, lon: lo / n, label: `${titleCase(d)} district centre`} : null;
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
    const m = meta();
    // The oldest saved pack sets the age warning; build dates are listed per state when they differ.
    const savedAt = m ? Math.min(m.saved_at, ...Object.values(m.packs || {}).map(x => x.saved_at)) : null;
    const age = m ? daysAgo(savedAt) : null;
    const builts = o && o.packs ? [...new Set(o.packs.map(x => x.built))] : [];
    const built = builts.length > 1 ? o.packs.map(x => `${x.built} (${titleCase(x.state)})`).join(', ')
      : o && o.built || m && m.built || '?';
    const ageClass = age == null ? '' : age > 90 ? 'stale-red' : age > 30 ? 'stale-amber' : '';
    const dates = m ? `<p class="${ageClass}">Facility data built ${esc(built)}.
      Saved to this phone ${dateStr(savedAt)} (${age === 0 ? 'today' : age + (age === 1 ? ' day' : ' days') + ' ago'}).
      ${age > 90 ? '<strong>Phone numbers may have changed.</strong>' : ''}</p>` : '';
    const calls = `<div class="row"><a class="btn" href="tel:108"><span aria-hidden="true">&#9742;</span> Call 108</a>
      ${ctx.show102 ? '<a class="btn" href="tel:102"><span aria-hidden="true">&#9742;</span> Call 102</a>' : ''}</div>`;
    const head = `<h1 tabindex="-1">No internet: ${esc(ctx.serviceLabel)}</h1>
      <p>${esc(ctx.reason)}</p>${dates}${calls}`;
    const gps = ctx.gettingGps ? `<p role="status">Getting GPS from satellites. Stand outside. Up to 2 minutes.</p>` : '';
    const choose = '<a class="btn btn-block" href="#/change">Choose place instead</a>';
    if (!m || !ctx.hasPack) {
      return head + `<p class="card">No saved facility data on this phone yet. It saves after one online answer.
        Call 108 in an emergency.</p>${choose}`;
    }
    if (!ctx.fresh || !o) {
      return head + gps + `<p>Using GPS from ${ctx.locLine} (older than 6 hours).</p>
        <button type="button" class="btn btn-primary btn-block" id="patient-here">Patient is here</button>${choose}`;
    }
    const prov = String(o.band_note || '').startsWith('placeholder')
      ? '<p class="small muted">Labels are provisional: the model has not published its scores yet.</p>' : '';
    const cards = o.options.length ? o.options.map((x, i) => card(x, i + 1, ctx.serviceLabel, o.state)).join('')
      : `<p class="card">No facility in the saved data lists ${esc(ctx.serviceLabel)} near here.</p>`;
    return head + gps + `<p class="small">${ctx.locLine}. Plan made for PIN ${esc(o.pin)} centre
        (${esc(titleCase(o.district))}), ${esc(o.km_to_pin)} km from you.</p>
      <h2>Call before you go</h2>${prov}${cards}
      <p class="small muted">Needs internet: note scan, map, road times, places outside
        ${esc([...new Set((o.packs || [o]).map(x => titleCase(x.state)))].join(', '))}.</p>${choose}`;
  }

  function card(x, n, label, userState) {
    const band = x.likely
      ? '<span class="band band-likely"><span aria-hidden="true">&#10004;</span> LIKELY</span>'
      : '<span class="band band-not_verified"><span aria-hidden="true">?</span> NOT VERIFIED: call to confirm</span>';
    const tel = telHref(x.tel);
    const quotes = x.quotes.length ? x.quotes.map(q => `<blockquote>"${esc(q.text)}"
        ${q.claim_id ? `<span class="tag">${esc(q.claim_id)}</span>` : ''}</blockquote>`).join('')
      : `<p class="small">Our data has no own sentence about ${esc(label)} for this listing.</p>`;
    const sms = 'sms:?body=' + encodeURIComponent(`${label}: ${x.name}. ${x.km_straight} km straight line. ` +
      `${tel ? 'Phone ' + tel.slice(4) + '. ' : ''}Call before going. Emergency 108.`);
    return `<article class="card" aria-labelledby="off-${n}"><p>${n}. ${band}</p>
      <h3 id="off-${n}">${esc(x.name)}</h3>
      <p>${x.state && userState && x.state !== userState ? `In ${esc(titleCase(x.state))}, ` : ''}${esc(x.km_straight)} km in a straight line (road is longer).${x.loc_low ? ' Map point may be wrong.' : ''}</p>
      ${x.listings > 1 ? `<p class="small muted">Listed ${esc(x.listings)} times in the data; shown once, with the best evidenced listing's score.</p>` : ''}
      ${quotes}
      ${tel ? `<a class="btn btn-primary btn-block" href="${esc(tel)}"><span aria-hidden="true">&#9742;</span>
        Call ${esc(x.name)}</a>${x.tel_dir ? '<p class="small">May be a directory number, not the hospital.</p>' : ''}`
        : '<p class="small">No dialable number saved for this listing.</p>'}
      <a class="btn btn-block" href="${esc(sms)}">Send by SMS <span class="visually-hidden">${esc(x.name)}</span></a>
    </article>`;
  }

  root.RSOffline = {savePack, loadPack, resolvePin, districtCentre, watchSatellite, fixIsFresh,
    answer, render, telHref, meta};
})(typeof window !== 'undefined' ? window : globalThis);
