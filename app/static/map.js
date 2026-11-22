// UI-MAP-1 (#140): a journey map and a stage graph under the answer. A classic script sharing app.js globals (state, F,
// N, E, th, ts, esc, $); app.js loads it with one call after the answer has painted, so it is not part of the
// first-paint bytes (75 KB budget). Inline SVG from fields the plan already carries: no tiles, no package, no network,
// so the offline answer (offline.js) gets the same map from the saved pack.
// Numbers from the payload carry data-f marks (tspan in the SVG) like the rest of the page; fixed drawing labels (ring
// minutes, scale bar) are aria-hidden, and the SVG's text alternative says where each option is.
'use strict';
(function (root) {
  const W = 320, H = 220, PAD = 30, RINGS = [30, 60, 120], SEP = 56;  // SEP: one 48 px target at a 288 px wide map
  const KM_LAT = 110.57, KM_LON = 111.32, R = Math.PI / 180;
  const STEPS = [0.5, 1, 2, 5, 10, 20, 50, 100, 200];
  const CSS = `.mp{margin-top:1rem}.mp-box{position:relative}.mp svg{display:block;width:100%;height:auto;background:var(--raised);border:1px solid var(--line);border-radius:8px}
.mp .lg{stroke:var(--go);stroke-width:2.5}.mp .lg.dbt{stroke:var(--warn);stroke-dasharray:6 5}.mp .rg{fill:none;stroke:var(--line-strong);stroke-width:1;stroke-dasharray:2 4}
.mp text{font:600 12px var(--font);fill:var(--text);paint-order:stroke;stroke:var(--raised);stroke-width:4px;stroke-linejoin:round}.mp .rl{font-size:11px;fill:var(--muted)}
.mp .pin{fill:var(--go);stroke:var(--surface);stroke-width:2.5}.mp .pin.dbt{fill:var(--surface);stroke:var(--warn);stroke-width:3;stroke-dasharray:4 3}
.mp .pn{fill:var(--on-go);stroke:none;font-size:13px}.mp .pn.dbt{fill:var(--text)}.mp .me{fill:var(--text);stroke:var(--surface);stroke-width:3}.mp .ink{fill:var(--text);stroke:none}.mp .bar{stroke:var(--text);stroke-width:2;fill:none}
.mp-hit{position:absolute;width:var(--target);height:var(--target);margin:calc(var(--target)/-2) 0 0 calc(var(--target)/-2);border:0;border-radius:50%;background:transparent;cursor:pointer;padding:0}
.mp-g{list-style:none;padding:0;margin:.5rem 0 0}.mp-g li{margin:0 0 .6rem}.mp-t{display:block;position:relative;height:12px;margin-top:4px;background:var(--surface);border:1px solid var(--line);border-radius:3px;overflow:hidden}
.mp-t i{position:absolute;top:0;bottom:0}.mp-t .d{background:var(--go)}.mp-t .r{background:var(--go-tint);top:3px;bottom:3px}.mp-t .s{background:var(--warn)}`;

  // The map's own words, en and hi, kept here (not in i18n/*.json) so they cost nothing on the critical path.
  const L = {
    en: {"h": "Map", "note": "Straight lines, not roads; times are the road estimates on the cards. Tap a number to go to that option.", "note_off": "Straight lines, not roads, from the data saved on this phone. Tap a number to go to that option.", "leg": "{min} min, {km} km", "leg_km": "{km} km", "you": "You", "n": "N", "dirs": "north,north-east,east,south-east,south,south-west,west,north-west", "alt": "Map, {n} options: {list}.", "alt_one": "{n} is {min} min {dir}", "alt_one_km": "{n} is {km} km {dir}", "alt_doubt": "(map point may be wrong)", "go": "Go to option {n}", "drive": "drive {n}", "graph_h": "Route, stop by stop", "arrive": "arrive {low} to {high} min from the start", "stay": "stay {d}"},
    hi: {"h": "नक्शा", "note": "सीधी रेखाएँ, सड़क नहीं; समय कार्ड पर दिए सड़क के अनुमान हैं। किसी नंबर को छूकर उस विकल्प पर जाएँ।", "note_off": "सीधी रेखाएँ, सड़क नहीं, इस फ़ोन में सेव डेटा से। किसी नंबर को छूकर उस विकल्प पर जाएँ।", "leg": "{min} मिनट, {km} किमी", "leg_km": "{km} किमी", "you": "आप", "n": "उ", "dirs": "उत्तर,उत्तर-पूर्व,पूर्व,दक्षिण-पूर्व,दक्षिण,दक्षिण-पश्चिम,पश्चिम,उत्तर-पश्चिम", "alt": "नक्शा, {n} विकल्प: {list}।", "alt_one": "{n}: {min} मिनट, {dir} में", "alt_one_km": "{n}: {km} किमी, {dir} में", "alt_doubt": "(नक्शे की जगह गलत हो सकती है)", "go": "विकल्प {n} पर जाएँ", "drive": "गाड़ी से {n}", "graph_h": "रास्ता, पड़ाव दर पड़ाव", "arrive": "शुरू से {low} से {high} मिनट में पहुँचें", "stay": "{d} रुकें"},
  };
  const word = k => (L[state.lang === 'hi' ? 'hi' : 'en'][k] ?? L.en[k]);
  const fill = (s, v) => s.replace(/\{(\w+)\}/g, (m, x) => (x in v ? String(v[x]) : m));
  const mt = (k, v = {}) => fill(word(k), v), mh = (k, v = {}) => fill(esc(word(k)), v);
  const tsp = (path, text, kind = 'num') => `<tspan data-f="${path}" data-k="${kind}">${esc(text)}</tspan>`;
  const dur = m => (m < 120 ? ts('dur.min', {n: m}) : m >= 1440 ? ts(Math.round(m / 1440) === 1 ? 'dur.day' : 'dur.days', {n: Math.round(m / 1440)}) : ts('dur.h', {n: Math.round(m / 60)}));
  const ok = x => typeof x === 'number' && isFinite(x);

  // Each option as {n, lat, lon, doubt, min, km, P (payload path, online only), el (its card)}.
  function points(p) {
    if (p.offline) {
      const a = p.answer;
      if (!a || !state.loc) return null;
      return {me: state.loc, opts: a.options.filter(x => ok(x.lat) && ok(x.lon)).map((x, i) => ({n: i + 1, lat: x.lat, lon: x.lon,
        doubt: x.loc_low, km: x.km_straight, el: () => $('#off-' + (i + 1))?.closest('article')}))};
    }
    const rows = [...document.querySelectorAll('#main .rows .next-row')];
    return {me: p.location, opts: p.options.map((o, i) => ({o, i})).filter(({o}) => ok(o.lat) && ok(o.lon)).map(({o, i}) => ({
      n: o.rank, lat: o.lat, lon: o.lon, doubt: !!o.location_doubt, min: o.travel.minutes, km: o.travel.km, P: `options.${i}`, name: o.name,
      el: () => (i ? rows[i - 1] : $('#main article.answer'))}))};
  }

  function dirWord(dx, dy) {
    const k = Math.round(((Math.atan2(dx, dy) / R) + 360) % 360 / 45) % 8;
    return mt('dirs').split(',')[k];
  }

  function mapSvg(p, pts) {
    const {me, opts} = pts, kx = KM_LON * Math.cos(me.lat * R);
    const km = q => [(q.lon - me.lon) * kx, (q.lat - me.lat) * KM_LAT];
    const all = [[0, 0], ...opts.map(km)];
    const xs = all.map(a => a[0]), ys = all.map(a => a[1]);
    const spanX = Math.max(Math.max(...xs) - Math.min(...xs), 1), spanY = Math.max(Math.max(...ys) - Math.min(...ys), 1);
    const s = Math.min((W - 2 * PAD) / spanX, (H - 2 * PAD) / spanY);  // px per km, equal on both axes
    const ox = PAD + ((W - 2 * PAD) - spanX * s) / 2 - Math.min(...xs) * s;
    const oy = PAD + ((H - 2 * PAD) - spanY * s) / 2 + Math.max(...ys) * s;
    const X = k => +(ox + k[0] * s).toFixed(1), Y = k => +(oy - k[1] * s).toFixed(1);
    const mx = X([0, 0]), my = Y([0, 0]);
    // 30, 60, 120 min rings at the first option's speed (straight km = minutes x km/h / road factor), only when the
    // payload has that speed and the ring falls inside the frame.
    const t = !p.offline && p.options[0] && p.options[0].travel;
    const far = Math.max(...[[0, 0], [W, 0], [0, H], [W, H]].map(([a, b]) => Math.hypot(a - mx, b - my)));
    const rings = t && ok(t.kmh) && ok(t.factor) && t.factor > 0 ? RINGS.map(m => [m, m / 60 * t.kmh / t.factor * s])
      .filter(([, r]) => r > 14 && r < far) : [];
    // drawn after the other labels, so a ring's label goes where it covers none of them (or is left out)
    const ringSvg = () => rings.map(([m, r]) => {
      const lab = ts('dur.min', {n: m}), hw = 3.5 * lab.length + 4;
      const spot = [0, 2, 6, 4, 1, 3, 5, 7].map(i => [mx + Math.sin(i * Math.PI / 4) * r, my - Math.cos(i * Math.PI / 4) * r])
        .map(([a, b]) => [a - hw, b - 6, a + hw, b + 6]).find(b => b[0] > 4 && b[2] < W - 4 && b[1] > 2 && b[3] < H - 2 && !cost(b));
      if (spot) taken.push(spot);
      return `<circle class="rg" cx="${mx}" cy="${my}" r="${r.toFixed(1)}"/>${spot ? `<text class="rl" aria-hidden="true" x="${((spot[0] + spot[2]) / 2).toFixed(1)}" y="${(spot[3] - 2).toFixed(1)}" text-anchor="middle">${esc(lab)}</text>` : ''}`;
    }).join('');
    // Labels: tried at 8 points round their anchor, starting away from the user's point, and kept off the frame
    // edges, the pins, the north arrow, the scale bar and each other.
    // the north arrow goes top right, or top left when a point sits under it there
    const pts0 = [[mx, my], ...opts.map(q => { const k = km(q); return [X(k), Y(k)]; })];
    const nx = pts0.some(([a, b]) => a > W - 44 && b < 56) && !pts0.some(([a, b]) => a < 44 && b < 56) ? 18 : W - 18;
    const taken = [[nx - 14, 0, nx + 14, 46], [0, H - 34, W / 2, H]];
    // a box is moved inside the frame first; its cost is how many boxes it overlaps (0 is a free spot)
    const inside = b => { const dx = Math.max(4 - b[0], 0) - Math.max(b[2] - W + 4, 0), dy = Math.max(4 - b[1], 0) - Math.max(b[3] - H + 4, 0);
      return [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]; };
    const lines = [];  // points along each leg: crossing a leg costs less than covering a label or a pin
    const cost = b => taken.filter(t => b[0] < t[2] && b[2] > t[0] && b[1] < t[3] && b[3] > t[1]).length
      + 0.4 * lines.filter(([x, y]) => x > b[0] && x < b[2] && y > b[1] && y < b[3]).length / 4;
    const place = (x, y, dx, dy, text, gap) => {
      // width at 12 px: Devanagari vowel signs and marks take little room, a space about half a letter
      const w = [...text].reduce((n, c) => n + (/[ऀ-ःऺ-ॏ]/.test(c) ? 2 : c === ' ' ? 3.5 : 7), 8), a0 = Math.atan2(dy, dx);
      let best = null, bc = Infinity;
      for (const d of [0, 1, -1, 2, -2, 3, -3, 4]) {
        const a = a0 + d * Math.PI / 4, cx = x + Math.cos(a) * (gap + w / 2 * Math.abs(Math.cos(a))), cy = y + Math.sin(a) * (gap + 8);
        const b = inside([cx - w / 2, cy - 8, cx + w / 2, cy + 7]), c = cost(b);
        if (c < bc) { best = b; bc = c; }
        if (!c) break;
      }
      taken.push(best);
      return [((best[0] + best[2]) / 2).toFixed(1), (best[3] - 3).toFixed(1)];
    };
    // Pins closer than one 48 px tap target would overlap (or hide each other): a later pin is moved sideways, off its leg,
    // by SEP steps until its target is clear. Lines and labels follow the moved pin; the text alternative keeps the true bearing.
    const legs = [];
    opts.forEach(q => {
      const k = km(q);
      let x = X(k), y = Y(k);
      const len = Math.hypot(x - mx, y - my) || 1, px = -(y - my) / len, py = (x - mx) / len;
      for (let i = 1; i < 6 && legs.some(l => Math.hypot(l.x - x, l.y - y) < SEP); i++) {
        const side = i % 2 ? 1 : -1, step = SEP * Math.ceil(i / 2);
        x = Math.min(W - 14, Math.max(14, X(k) + side * step * px));
        y = Math.min(H - 14, Math.max(14, Y(k) + side * step * py));
      }
      legs.push({q, x: +x.toFixed(1), y: +y.toFixed(1)});
    });
    legs.forEach(l => taken.push([l.x - 13, l.y - 13, l.x + 13, l.y + 13]));
    taken.push([mx - 8, my - 8, mx + 8, my + 8]);
    legs.forEach(l => { for (let i = 1; i < 24; i++) lines.push([mx + (l.x - mx) * i / 24, my + (l.y - my) * i / 24]); });
    legs.forEach(l => {
      const {q, x, y} = l, plain = q.P ? mt('leg', {min: q.min, km: Math.round(q.km)}) : mt('leg_km', {km: q.km});
      const [lx, ly] = place(x, y, x - mx || 0.01, y - my, plain, 16);
      const lab = q.P ? mh('leg', {min: tsp(q.P + '.travel.minutes', q.min), km: tsp(q.P + '.travel.km', Math.round(q.km))}) : esc(plain);
      l.line = `<line class="lg${q.doubt ? ' dbt' : ''}" x1="${mx}" y1="${my}" x2="${x}" y2="${y}"/>`;
      l.lab = `<text x="${lx}" y="${ly}" text-anchor="middle">${lab}</text>`;
    });
    const sx = legs.reduce((a, l) => a + l.x - mx, 0), sy = legs.reduce((a, l) => a + l.y - my, 0);
    const [ux, uy] = place(mx, my, -sx || 0.01, -sy, mt('you'), 10);
    const pins = legs.map(({q, x, y}) => `<circle class="pin${q.doubt ? ' dbt' : ''}" cx="${x}" cy="${y}" r="12"/>
      <text class="pn${q.doubt ? ' dbt' : ''}" x="${x}" y="${y + 4.5}" text-anchor="middle">${q.P ? tsp(q.P + '.rank', q.n) : q.n}</text>`).join('');
    // scale bar: a round number of km near a quarter of the width; north arrow top right
    const step = STEPS.reduce((b, v) => (Math.abs(v * s - W / 4) < Math.abs(b * s - W / 4) ? v : b), STEPS[0]);
    const bw = +(step * s).toFixed(1);
    const scale = `<g aria-hidden="true"><path class="bar" d="M10 ${H - 16}v6h${bw}v-6"/><text x="10" y="${H - 20}">${esc(mt('leg_km', {km: step}))}</text></g>`;
    const north = `<g aria-hidden="true"><path class="ink" d="M${nx} 8l7 18-7-5-7 5z"/><text x="${nx}" y="40" text-anchor="middle">${esc(mt('n'))}</text></g>`;
    const alt = mt('alt', {n: opts.length, list: opts.map(q => {
      const [dx, dy] = km(q);
      return mt(q.P ? 'alt_one' : 'alt_one_km', {n: q.n, min: q.min, km: q.km, dir: dirWord(dx, dy)}) + (q.doubt ? ' ' + mt('alt_doubt') : '');
    }).join('; ')});
    const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(alt)}">${ringSvg()}${legs.map(l => l.line).join('')}
      <circle class="me" cx="${mx}" cy="${my}" r="7"/><text x="${ux}" y="${uy}" text-anchor="middle">${esc(mt('you'))}</text>
      ${legs.map(l => l.lab).join('')}${pins}${scale}${north}</svg>`;
    const hits = legs.map(({q, x, y}) => `<button type="button" class="mp-hit" data-mp="${q.n}" style="left:${(100 * x / W).toFixed(2)}%;top:${(100 * y / H).toFixed(2)}%"
      aria-label="${esc(mt('go', {n: q.n}))}"></button>`).join('');
    return `<div class="mp-box">${svg}${hits}</div>`;
  }

  // Stop-by-stop graph of the suggested route: one row per stop, drive and stay as bars on a shared minute scale.
  // The text carries the arrival window (eta_low to eta_high, cumulative from the start) and the stay; the drive is
  // the gap since leaving the stop before (kind 'leg'). No route: nothing.
  function graphHtml(p) {
    const it = p.itinerary, r = it && !it.abstain && it.plans && it.plans[0];
    if (!r || !r.stops || !r.stops.length) return '';
    const P = 'itinerary.plans.0', st = r.stops;
    const leave = k => (k ? st[k - 1].eta_low + (st[k - 1].dwell_minutes || 0) : 0);
    const span = 1.05 * Math.max(...st.map(x => Math.max(x.eta_high, x.eta_low + (x.dwell_minutes || 0))), 1);
    const pc = m => (100 * m / span).toFixed(2) + '%';
    const rows = st.map((x, k) => {
      const S = `${P}.stops.${k}`, a = leave(k), drive = x.eta_low - a;
      const bar = (c, from, to) => (to > from ? `<i class="${c}" style="left:${pc(from)};width:${pc(to - from)}"></i>` : '');
      return `<li><b lang="en">${F(S + '.name', x.name)}</b>: ${E(S + '.purpose_word', x.purpose_word)}${th('punct.stop')}
        ${mh('arrive', {low: N(S + '.eta_low', x.eta_low), high: N(S + '.eta_high', x.eta_high)})}${
        drive > 0 ? ', ' + mh('drive', {n: F(S, dur(drive), 'leg')}) : ''}${
        x.dwell_minutes ? ', ' + mh('stay', {d: F(S + '.dwell_minutes', dur(x.dwell_minutes), 'dur')}) : ''}${th('punct.stop')}
        <span class="mp-t" aria-hidden="true">${bar('r', x.eta_low, x.eta_high)}${bar('d', a, x.eta_low)}${bar('s', x.eta_low, x.eta_low + (x.dwell_minutes || 0))}</span></li>`;
    }).join('');
    return `<h3>${mh('graph_h')}</h3><ol class="mp-g">${rows}</ol>`;
  }

  function go(n, pts) {
    const q = pts.opts.find(x => x.n === n), el = q && q.el();
    if (!el) return;
    el.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
    el.focus({preventScroll: true});
  }

  function draw(p) {
    const main = $('#main');
    if (!main || location.hash !== '#/plan' || state.plan !== p || state.depth === 'compare') return;
    main.querySelector('.mp')?.remove();
    const pts = points(p);
    if (!pts || !pts.me || !ok(pts.me.lat) || !pts.opts.length) return;
    // below card 1's Call (and the next options' rows), above the route
    const at = p.offline ? [...main.querySelectorAll('article.answer')].pop()
      : main.querySelector('[aria-labelledby=h-no]') || main.querySelector('article.answer')?.closest('.section');
    if (!at) return;
    if (!document.getElementById('mp-css')) document.head.appendChild(Object.assign(document.createElement('style'), {id: 'mp-css', textContent: CSS}));
    at.insertAdjacentHTML('afterend', `<section class="section mp" aria-labelledby="h-map"><h2 id="h-map">${mh('h')}</h2>
      ${mapSvg(p, pts)}<p class="note">${mh(p.offline ? 'note_off' : 'note')}</p>${p.offline ? '' : graphHtml(p)}</section>`);
    main.querySelectorAll('.mp-hit').forEach(b => b.addEventListener('click', () => go(+b.dataset.mp, pts)));
  }

  root.RSMap = {draw};
})(window);
