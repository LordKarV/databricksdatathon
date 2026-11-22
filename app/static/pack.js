// Offline state pack reader (issue #9), format v1 from app/packs/build_packs.py.
// Plain script: attaches window.RSPack (or globalThis.RSPack under node/workers). Not on the critical path:
// the page loads it only when it needs an offline answer.
'use strict';
(function (root) {
  function undelta(a, scale) {
    const out = new Array(a.length);
    let acc = 0;
    for (let i = 0; i < a.length; i++) { acc += a[i]; out[i] = scale ? acc / scale : acc; }
    return out;
  }

  function km(lat1, lon1, lat2, lon2) {
    const r = Math.PI / 180;
    const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
      Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.sqrt(a));
  }

  function decode(pack) {
    if (pack.decoded) return pack;
    if (pack.v !== 1) throw new Error('unsupported pack version ' + pack.v);
    const f = pack.fac;
    return {
      decoded: true, state: pack.state, built: pack.built, services: pack.services,
      band_note: pack.band_note, ranking_note: pack.ranking_note,
      fac: {uid8: f.uid8, name: f.name, tel: f.tel, tel_dir: f.tel_dir, loc_low: f.loc_low, dup: f.dup || [],
        state: (f.st || []).map(i => pack.fac_states[i]),
        lat: undelta(f.lat, pack.scale.fac), lon: undelta(f.lon, pack.scale.fac)},
      ev: Object.assign({}, pack.ev, {f: undelta(pack.ev.f)}),
      q: pack.q, lists: pack.lists, index: pack.index, districts: pack.districts,
      pins: {pin: undelta(pack.pins.pin), lat: undelta(pack.pins.lat, pack.scale.pin),
        lon: undelta(pack.pins.lon, pack.scale.pin), d: pack.pins.d},
    };
  }

  function nearestPin(p, lat, lon) {
    let best = -1, bestKm = Infinity;
    for (let i = 0; i < p.pins.pin.length; i++) {
      const d = km(lat, lon, p.pins.lat[i], p.pins.lon[i]);
      if (d < bestKm) { bestKm = d; best = i; }
    }
    return [best, bestKm];
  }

  // A quote from a merged duplicate listing (#78) carries its own whole claim id after "=".
  const claimId = (uid8, ref) => !ref ? null : ref[0] === '=' ? ref.slice(1) : uid8 + ':' + ref;

  // Rows of the PIN nearest to the point in one pack, with straight-line km from the point.
  function rows(p, lat, lon, service) {
    if (!p.index[service]) throw new Error('service not in pack: ' + service);
    const [i, kmToPin] = nearestPin(p, lat, lon);
    if (i < 0) return {i, kmToPin, options: []};
    const options = p.lists[p.index[service][i]].map(e => {
      const fi = p.ev.f[e];
      const uid8 = p.fac.uid8[fi];
      const quotes = [p.ev.q1[e], p.ev.q2[e]].filter(q => q >= 0).map(q => ({
        text: p.q[q][0], claim_id: claimId(uid8, p.q[q][1])}));
      const flat = p.fac.lat[fi], flon = p.fac.lon[fi];
      return {name: p.fac.name[fi], uid8, tel: p.fac.tel[fi] || null, tel_dir: !!p.fac.tel_dir[fi],
        loc_low: !!p.fac.loc_low[fi], listings: p.fac.dup[fi] || 1, lat: flat, lon: flon, km_straight: Math.round(km(lat, lon, flat, flon) * 10) / 10,
        state: p.fac.state[fi] || null,
        likely: !!p.ev.likely[e], p: p.ev.p[e] / 100, lo: p.ev.lo[e] / 100, hi: p.ev.hi[e] / 100, quotes};
    });
    return {i, kmToPin, options};
  }

  const TOP_K = 3;  // the same rule as build_packs.py: the 3 nearest plus the nearest likely one

  // Answer from every saved pack: each pack gives the list of its PIN nearest to the point; the union is
  // ranked by straight-line km as before. With one pack the answer is exactly that pack's list.
  function queryAll(packs, lat, lon, service) {
    const ps = packs.map(decode);
    const all = ps.map(p => ({state: p.state, built: p.built}));
    const per = ps.map(p => Object.assign({p}, rows(p, lat, lon, service)))
      .filter(r => r.i >= 0).sort((a, b) => a.kmToPin - b.kmToPin);
    if (!per.length) return {pin: null, district: null, km_to_pin: null, options: [], packs: all};
    const seen = new Set();
    let options = per.flatMap(r => r.options).filter(o => !seen.has(o.uid8) && seen.add(o.uid8))
      .sort((a, b) => a.km_straight - b.km_straight);
    if (per.filter(r => r.options.length).length > 1) {
      const likely = options.find(o => o.likely);
      options = options.slice(0, TOP_K).concat(likely && !options.slice(0, TOP_K).includes(likely) ? [likely] : []);
    }
    const {p, i, kmToPin} = per[0];
    return {pin: p.pins.pin[i], district: p.districts[p.pins.d[i]] || null, state: p.state,
      km_to_pin: Math.round(kmToPin * 10) / 10, built: p.built, options, packs: all};
  }

  function query(pack, lat, lon, service) { return queryAll([pack], lat, lon, service); }

  root.RSPack = {decode, query, queryAll, km};
})(typeof window !== 'undefined' ? window : globalThis);
