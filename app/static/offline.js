// Offline answer (spec S9, section 3.2.3; issue #23). Plain script, attaches window.RSOffline.
// Packs live in IndexedDB, kept by the service worker (sw.js). Loaded lazily by app.js (never on the critical path); the service worker precaches it with pack.js.
// Answers only from the state pack saved on this phone; shows no number the pack does not contain.
'use strict';
(function (root) {
  const KEY = 'rs.pack';  // {slug, state, built, saved_at}
  const DAY = 86400000;
  const FRESH_FIX_MS = 6 * 3600000;  // spec 3.2.3 step 1: older fixes need "Patient is here"
  const ACCEPT_M = 1000;  // step 2: accept a satellite fix of 1,000 m or better

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function meta() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } }
  function setMeta(m) { try { localStorage.setItem(KEY, JSON.stringify(m)); } catch { /* private mode */ } }
  function daysAgo(t) { return Math.max(0, Math.floor((Date.now() - t) / DAY)); }
  function dateStr(t) { return new Date(t).toLocaleDateString([], {day: 'numeric', month: 'short'}); }

  // Indian numbers in the pack are 10 digits (mobile or STD code + number); anything else gets no tel: link.
  function telHref(raw) {
    const d = String(raw || '').replace(/[\s\-().]/g, '');
    if (/^[1-9]\d{9}$/.test(d)) return 'tel:+91' + d;
    if (/^0[1-9]\d{9}$/.test(d)) return 'tel:+91' + d.slice(1);
    if (/^\+91[1-9]\d{9}$/.test(d)) return 'tel:' + d;
    return null;
  }

  // ---------- saving the pack (online, in the background) ----------
  async function savePack(lat, lon) {
    if (!('serviceWorker' in navigator)) return {status: 'no-service-worker'};
    const r = await fetch('/api/pack/locate', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lat: +lat.toFixed(2), lon: +lon.toFixed(2)}), redirect: 'manual'});
    if (!r.ok) return {status: 'no-pack'};
    const loc = await r.json();
    const reg = await navigator.serviceWorker.ready;
    const res = await new Promise(resolve => {
      const ch = new MessageChannel();
      ch.port1.onmessage = e => resolve(e.data);
      reg.active.postMessage({type: 'cache-pack', slug: loc.slug}, [ch.port2]);
      setTimeout(() => resolve({status: 'timeout'}), 60000);
    });
    if (res.status === 'saved' || res.status === 'unchanged') {
      const old = meta();
      const fresh = res.status === 'saved' || !old || old.slug !== loc.slug;
      // Ask once that the browser not evict the pack under storage pressure (#32). Chrome grants it silently
      // for installed or engaged sites; Firefox may prompt. A refusal changes nothing else.
      const persisted = old && old.persisted ? true : await persist();
      setMeta({slug: loc.slug, state: loc.state, sha256: res.sha256, persisted,
        saved_at: fresh ? Date.now() : old.saved_at, built: old && !fresh ? old.built : null});
    }
    return res;
  }

  async function persist() {
    try {
      const sm = navigator.storage;
      if (!sm || !sm.persist) return false;
      return (await sm.persisted()) || (await sm.persist());
    } catch { return false; }
  }

  async function loadPack() {
    const m = meta();
    if (!m) return null;
    const r = await fetch('/api/pack/' + m.slug).catch(() => null);
    if (!r || !r.ok) return null;
    const pack = root.RSPack.decode(await r.json());
    if (m.built !== pack.built) setMeta(Object.assign(m, {built: pack.built}));
    return pack;
  }

  function titleCase(s) { return String(s || '').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()); }

  // ---------- offline place picker from the pack ----------
  function resolvePin(pack, pin) {
    const i = pack.pins.pin.indexOf(+pin);
    if (i < 0) return null;
    return {lat: pack.pins.lat[i], lon: pack.pins.lon[i], label: `PIN ${pin}, ${titleCase(pack.districts[pack.pins.d[i]])}`};
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
    const res = root.RSPack.query(pack, loc.lat, loc.lon, service);
    return Object.assign(res, {state: pack.state, band_note: pack.band_note});
  }

  function render(o, ctx) {
    // ctx: {serviceLabel, locLine (already escaped HTML), show102, fresh, hasPack, gettingGps, reason}
    const m = meta();
    const age = m ? daysAgo(m.saved_at) : null;
    const ageClass = age == null ? '' : age > 90 ? 'stale-red' : age > 30 ? 'stale-amber' : '';
    const dates = m ? `<p class="${ageClass}">Facility data built ${esc(o && o.built || m.built || '?')}.
      Saved to this phone ${dateStr(m.saved_at)} (${age === 0 ? 'today' : age + (age === 1 ? ' day' : ' days') + ' ago'}).
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
    const cards = o.options.length ? o.options.map((x, i) => card(x, i + 1, ctx.serviceLabel)).join('')
      : `<p class="card">No facility in the saved data lists ${esc(ctx.serviceLabel)} near here.</p>`;
    return head + gps + `<p class="small">${ctx.locLine}. Plan made for PIN ${esc(o.pin)} centre
        (${esc(titleCase(o.district))}), ${esc(o.km_to_pin)} km from you.</p>
      <h2>Call before you go</h2>${prov}${cards}
      <p class="small muted">Needs internet: note scan, map, road times, places outside ${esc(titleCase(o.state))}
        and its border.</p>${choose}`;
  }

  function card(x, n, label) {
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
      <p>${esc(x.km_straight)} km in a straight line (road is longer).${x.loc_low ? ' Map point may be wrong.' : ''}</p>
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
