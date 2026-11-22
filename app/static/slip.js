// Referral slip (spec S8, issue #24). Pure functions on window.RSSlip; loaded lazily on #/slip/<rank>.
// Safety 20: no patient name or location, no confidence decimals, made time plus "call before going if more
// than a day old", "ask the patient before sending"; no recipient number is asked for or stored.
'use strict';
(function (root) {
  // Hindi strings are drafts until native-speaker review (#10). Devanagari is \u-escaped to keep the file ASCII.
  const T = {
    en: {
      title: 'Referral slip', service: 'Service', go: 'Go to', phone: 'Phone', noPhone: 'no number in our data',
      travel: 'Travel', about: 'about', min: 'min', km: 'km', map: 'Map', why: 'Why', ifNot: 'If not',
      call: 'Phone check', noCall: 'Not checked by phone yet. Call before going.',
      said: {yes: 'Said yes on the phone', no: 'Said no on the phone', none: 'No answer on the phone',
        wrong: 'Wrong number'},
      at: 'at', numbers: 'Emergency 108 (ambulance, free).', n102: 'Pregnancy or baby: 102 (free). No answer? Call 108.',
      worse: 'If the patient gets worse, go to the nearest 24x7 emergency.',
      note: "Carry the doctor's note.", name: 'Patient name (write by hand): ____________',
      made: 'Made', asOf: 'Facility data as of', old: 'Call before going if this slip is more than a day old.',
      ask: 'Ask the patient before sending.', draft: '',
      listing: 'its listing says', source: 'source', route: 'Suggested route', stay: 'stay',
    },
    hi: {
      title: '\u0930\u0947\u092b\u093c\u0930\u0932 \u092a\u0930\u094d\u091a\u0940',
      service: '\u0938\u0947\u0935\u093e',
      go: '\u092f\u0939\u093e\u0901 \u091c\u093e\u090f\u0901',
      phone: '\u092b\u093c\u094b\u0928',
      noPhone: '\u0939\u092e\u093e\u0930\u0947 \u0921\u0947\u091f\u093e \u092e\u0947\u0902 \u0928\u0902\u092c\u0930 \u0928\u0939\u0940\u0902',
      travel: '\u092f\u093e\u0924\u094d\u0930\u093e',
      about: '\u0932\u0917\u092d\u0917',
      min: '\u092e\u093f\u0928\u091f',
      km: '\u0915\u093f\u0932\u094b\u092e\u0940\u091f\u0930',
      map: '\u0928\u0915\u094d\u0936\u093e',
      why: '\u0915\u094d\u092f\u094b\u0902',
      ifNot: '\u0935\u0939\u093e\u0901 \u0928 \u0939\u094b \u0938\u0915\u0947 \u0924\u094b',
      call: '\u092b\u093c\u094b\u0928 \u092a\u0930 \u092a\u0942\u091b\u0924\u093e\u091b',
      noCall: '\u0905\u092d\u0940 \u092b\u093c\u094b\u0928 \u092a\u0930 \u0928\u0939\u0940\u0902 \u092a\u0942\u091b\u093e\u0964 \u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      said: {
        yes: '\u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0901 \u0915\u0939\u093e',
        no: '\u092b\u093c\u094b\u0928 \u092a\u0930 \u0928\u093e \u0915\u0939\u093e',
        none: '\u092b\u093c\u094b\u0928 \u0928\u0939\u0940\u0902 \u0909\u0920\u093e',
        wrong: '\u0917\u0932\u0924 \u0928\u0902\u092c\u0930',
      },
      at: '',
      numbers: '\u0907\u092e\u0930\u091c\u0947\u0902\u0938\u0940: 108 (\u090f\u092e\u094d\u092c\u0941\u0932\u0947\u0902\u0938, \u092e\u0941\u092b\u093c\u094d\u0924)\u0964',
      n102: '\u0917\u0930\u094d\u092d\u0935\u0924\u0940 \u092e\u0939\u093f\u0932\u093e \u092f\u093e \u0936\u093f\u0936\u0941: 102 (\u092e\u0941\u092b\u093c\u094d\u0924)\u0964 \u091c\u0935\u093e\u092c \u0928 \u092e\u093f\u0932\u0947 \u0924\u094b 108 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      worse: '\u092e\u0930\u0940\u091c\u093c \u0915\u0940 \u0939\u093e\u0932\u0924 \u092c\u093f\u0917\u0921\u093c\u0947 \u0924\u094b \u0938\u092c\u0938\u0947 \u092a\u093e\u0938 \u0915\u0940 24 \u0918\u0902\u091f\u0947 \u0916\u0941\u0932\u0940 \u0907\u092e\u0930\u091c\u0947\u0902\u0938\u0940 \u092e\u0947\u0902 \u091c\u093e\u090f\u0901\u0964',
      note: '\u0921\u0949\u0915\u094d\u091f\u0930 \u0915\u0940 \u092a\u0930\u094d\u091a\u0940 \u0938\u093e\u0925 \u0930\u0916\u0947\u0902\u0964',
      name: '\u092e\u0930\u0940\u091c\u093c \u0915\u093e \u0928\u093e\u092e (\u0939\u093e\u0925 \u0938\u0947 \u0932\u093f\u0916\u0947\u0902): ____________',
      made: '\u092c\u0928\u093e\u0928\u0947 \u0915\u093e \u0938\u092e\u092f',
      asOf: '\u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u0921\u0947\u091f\u093e \u0915\u0940 \u0924\u093e\u0930\u0940\u0916',
      old: '\u092f\u0939 \u092a\u0930\u094d\u091a\u0940 \u090f\u0915 \u0926\u093f\u0928 \u0938\u0947 \u092a\u0941\u0930\u093e\u0928\u0940 \u0939\u094b \u0924\u094b \u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      ask: '\u092d\u0947\u091c\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092e\u0930\u0940\u091c\u093c \u0938\u0947 \u092a\u0942\u091b\u0947\u0902\u0964',
      draft: '',
      listing: '\u0907\u0938\u0915\u0940 \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0932\u093f\u0916\u093e \u0939\u0948',
      source: '\u0938\u094d\u0930\u094b\u0924',
      route: '\u0938\u0941\u091d\u093e\u092f\u093e \u0917\u092f\u093e \u0930\u093e\u0938\u094d\u0924\u093e',
      stay: '\u0930\u0941\u0915\u0947\u0902',
    },
  };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const MONTHS_HI = ['\u091c\u0928\u0935\u0930\u0940', '\u092b\u093c\u0930\u0935\u0930\u0940', '\u092e\u093e\u0930\u094d\u091a',
    '\u0905\u092a\u094d\u0930\u0948\u0932', '\u092e\u0908', '\u091c\u0942\u0928', '\u091c\u0941\u0932\u093e\u0908',
    '\u0905\u0917\u0938\u094d\u0924', '\u0938\u093f\u0924\u0902\u092c\u0930', '\u0905\u0915\u094d\u091f\u0942\u092c\u0930',
    '\u0928\u0935\u0902\u092c\u0930', '\u0926\u093f\u0938\u0902\u092c\u0930'];
  // UI2: on a Hindi slip, the stamp's month and the engine's English words (travel label, route purposes) are Hindi.
  // app.js exposes the reviewed engine table as rsEngHi; without it (node harness) the English stays.
  const madeIn = (made, lang) => (lang === 'hi' ? made.replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/,
    x => MONTHS_HI[MONTHS.indexOf(x)]) : made);
  const engHi = (text, lang) => (lang === 'hi' && root.rsEngHi ? root.rsEngHi(text) : null);
  function E(path, text, lang) {
    const hi = engHi(text, lang);
    return hi != null ? `<span data-f="${path}" data-k="template">${esc(hi)}</span>` : `<span lang="en">${F(path, text)}</span>`;
  }
  const OUTCOME_KEY = {'Said yes': 'yes', 'Said no': 'no', 'No answer': 'none', 'Wrong number': 'wrong'};

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function stamp(d) {
    const p = n => String(n).padStart(2, '0');
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  // Maps link has a destination only; the phone fills in its own origin (no patient location on the slip).
  function mapsUrl(o) {
    return `https://www.google.com/maps/dir/?api=1&destination=${o.lat},${o.lon}`;
  }
  function place(o, path) {
    return {path, addrKey: o.address ? 'address' : 'town',
      phoneKey: o.phone && o.phone.display ? 'display' : 'e164', name: o.name, town: o.town, address: o.address || o.town,
      phone: o.phone && o.phone.e164 ? (o.phone.display || o.phone.e164) : null,
      km: Math.round(o.travel.km), low: Math.round(o.travel.low), high: Math.round(o.travel.high),
      method: o.travel.method, label: o.travel.label, map: mapsUrl(o)};
  }

  /** Everything the slip shows, from stored plan fields only. callOutcome: {said: 'Said yes'|..., at: ms} or null. */
  function slipModel(plan, option, backup, callOutcome, now) {
    const service = plan.query.service_label;
    const nums = (plan.emergency_numbers || []).map(n => n.number);
    return {
      made: stamp(now ? new Date(now) : new Date()),
      asOf: plan.as_of,
      service: {en: service.en, hi: service.hi || service.en},
      has102: nums.includes('102'),
      go: place(option, `options.${plan.options.indexOf(option)}`),
      backup: backup ? place(backup, `options.${plan.options.indexOf(backup)}`) : null,
      quotes: (option.evidence || []).slice(0, 3).map((e, j) => ({text: e.quote, source: e.source_url, claim: e.claim_id,
        path: `options.${plan.options.indexOf(option)}.evidence.${j}`})),
      outcome: callOutcome && OUTCOME_KEY[callOutcome.said]
        ? {key: OUTCOME_KEY[callOutcome.said], at: stamp(new Date(callOutcome.at)).slice(-5)} : null,
      stub: !!(plan.meta && plan.meta.stub),
      route: routeModel(plan),
    };
  }

  /** The best multi-stop route (#47), one entry per hospital, in order; null when the plan has none. */
  function routeModel(plan) {
    const r = plan.itinerary && plan.itinerary.plans && plan.itinerary.plans[0];
    if (!r || !r.stops.length) return null;
    const out = [];
    r.stops.forEach((s, k) => {
      const path = `itinerary.plans.0.stops.${k}`;
      const last = out[out.length - 1];
      const stage = {path, purpose: s.purpose_word, dwell: s.dwell_minutes};
      if (last && last.id === s.facility_id) { last.stages.push(stage); return; }
      out.push({id: s.facility_id, path, name: s.name, low: s.eta_low, high: s.eta_high, stages: [stage],
        phoneKey: s.phone && s.phone.display ? 'display' : 'e164',
        phone: s.phone && s.phone.e164 ? (s.phone.display || s.phone.e164) : null});
    });
    return out;
  }
  function durText(m, lang) {
    const hi = lang === 'hi';
    if (m < 120) return `${m} ${hi ? '\u092e\u093f\u0928\u091f' : 'min'}`;
    const d = Math.round(m / 1440);
    if (m >= 1440) return hi ? `${d} \u0926\u093f\u0928` : `${d} day${d === 1 ? '' : 's'}`;
    return `${Math.round(m / 60)} ${hi ? '\u0918\u0902\u091f\u0947' : 'h'}`;
  }

  function travelText(g, t, lang) {
    return `${g.km} ${t.km}, ${t.about} ${g.low}-${g.high} ${t.min} (${engHi(g.label, lang) ?? g.label})`;
  }
  function outcomeText(m, t) {
    return m.outcome ? `${t.said[m.outcome.key]}${t.at ? ' ' + t.at : ''} ${m.outcome.at}.` : t.noCall;
  }

  /** Plain-text lines shared by the WhatsApp text; same content as the printed slip. */
  function lines(m, lang) {
    const t = T[lang] || T.en;
    const out = [`${t.title.toUpperCase()}  ${madeIn(m.made, lang)}`];
    if (t.draft) out.push(t.draft);
    if (m.stub) out.push('SAMPLE DATA, not a real referral.');
    out.push(`${t.service}: ${m.service[lang] || m.service.en}`);
    out.push(`${t.go}: ${m.go.name}, ${m.go.address}`);
    out.push(`${t.phone}: ${m.go.phone || t.noPhone}`);
    out.push(`${t.travel}: ${travelText(m.go, t, lang)}`);
    out.push(`${t.map}: ${m.go.map}`);
    if (m.quotes.length) {
      out.push(`${t.why}: ${t.listing}:`);
      m.quotes.forEach(q => out.push(`- "${q.text}" (${t.source}: ${q.source})`));
    }
    out.push(`${t.call}: ${outcomeText(m, t)}`);
    if (m.backup) out.push(`${t.ifNot}: ${m.backup.name}, ${m.backup.km} ${t.km}. ${t.phone}: ${m.backup.phone || t.noPhone}`);
    if (m.route) {
      out.push(`${t.route}:`);
      m.route.forEach((g, k) => out.push(`${k + 1}. ${g.name} (${g.stages.map(x => engHi(x.purpose, lang) ?? x.purpose).join(', ')}), ` +
        `${t.about} ${g.low}-${g.high} ${t.min}. ${t.phone}: ${g.phone || t.noPhone}`));
    }
    out.push(t.numbers);
    if (m.has102) out.push(t.n102);
    out.push(t.worse, t.note);
    out.push(`${t.made}: ${madeIn(m.made, lang)}. ${t.asOf}: ${m.asOf}.`, t.old);
    return out;
  }

  function toWhatsApp(m, lang) {
    const text = lines(m, lang).join('\n');
    return {text, url: 'https://wa.me/?text=' + encodeURIComponent(text)};
  }

  /** SMS-length version (<= 300 characters): where to go, phones, backup, 108, date. */
  function toSms(m, lang) {
    const t = T[lang] || T.en;
    const cut = (s, n) => (s.length > n ? s.slice(0, n - 1) + '.' : s);
    const parts = [
      `${t.title}: ${m.service[lang] || m.service.en}.`,
      `${t.go}: ${cut(m.go.name, 50)}, ${cut(m.go.town, 25)}. ${t.phone} ${m.go.phone || '-'}.`,
      m.backup ? `${t.ifNot}: ${cut(m.backup.name, 40)} ${m.backup.phone || ''}.` : '',
      m.has102 ? '108 / 102.' : '108.',
      `${t.made} ${madeIn(m.made, lang)}.`,
    ].filter(Boolean);
    let text = parts.join(' ').replace(/\s+/g, ' ').trim();
    if (text.length > 300) text = text.slice(0, 299) + '.';
    return {text, url: 'sms:?body=' + encodeURIComponent(text)};
  }

  // Faithfulness markers (#30): same data-f / data-k / data-device convention as app.js.
  function F(path, text, kind = 'text') { return `<span data-f="${path}" data-k="${kind}">${esc(text)}</span>`; }
  function phoneHtml(g) {
    return g.phone ? `<a href="tel:${esc(g.phone.replace(/[^+\d]/g, ''))}">${F(g.path + '.phone.' + g.phoneKey, g.phone)}</a>` : null;
  }
  function travelHtml(g, t, lang) {
    return `${F(g.path + '.travel.km', g.km, 'num')} ${esc(t.km)}, ${esc(t.about)} ${F(g.path + '.travel.low', g.low, 'num')}-` +
      `${F(g.path + '.travel.high', g.high, 'num')} ${esc(t.min)} (${lang === 'hi' ? E(g.path + '.travel.label', g.label, lang) : F(g.path + '.travel.label', g.label)})`;
  }

  // Styles for this screen only, injected on first use so they stay off the first-paint CSS (75 KB budget). Screen only:
  // app.css's @media print rules for .slip must win when printing.
  const CSS = `@media screen {
.slip { border: 2px solid var(--text); border-radius: var(--r2); padding: var(--sp3) var(--sp4); margin: var(--sp3) 0; background: var(--surface); }
.slip h2 { font-size: var(--s21); margin-top: 0; }
.slip-table { table-layout: fixed; }
.slip-table th, .slip-table td { padding: var(--sp2) var(--sp1); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.slip-table td { overflow-wrap: anywhere; }
.slip-table th { width: 30%; }
.slip-table ul { margin: 4px 0; padding-left: 18px; }
.slip a { overflow-wrap: anywhere; }
.slip-name { border-top: 1px dashed var(--line-strong); padding-top: var(--sp2); }
body.slip-big .slip { font-size: 200%; }
body.slip-big .top, body.slip-big #bar108, body.slip-big .nav { display: none; }
}`;
  function injectCss() {
    if (typeof document === 'undefined' || document.getElementById('slip-css')) return;
    const st = document.createElement('style');
    st.id = 'slip-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  /** Printable slip markup (one A5/A4 page with the print stylesheet). */
  function toHtml(m, lang) {
    injectCss();
    const t = T[lang] || T.en;
    const row = (k, v) => `<tr><th scope="row">${esc(k)}</th><td>${v}</td></tr>`;
    const go = m.go;
    const svcKey = m.service[lang] && lang === 'hi' ? 'hi' : 'en';
    return `<article class="slip" lang="${lang === 'hi' ? 'hi' : 'en'}" aria-labelledby="slip-title">
      <h2 id="slip-title">${esc(t.title)} <span class="small" data-device>${esc(madeIn(m.made, lang))}</span></h2>
      ${t.draft ? `<p class="small" lang="en">${esc(t.draft)}</p>` : ''}
      ${m.stub ? '<p class="small" lang="en"><strong>Sample data, not a real referral.</strong></p>' : ''}
      <table class="slip-table"><tbody>
        ${row(t.service, F('query.service_label.' + svcKey, m.service[svcKey]))}
        ${row(t.go, `<strong lang="en">${F(go.path + '.name', go.name)}</strong><br><span lang="en">${F(go.path + '.' + go.addrKey, go.address)}</span>`)}
        ${row(t.phone, phoneHtml(go) || esc(t.noPhone))}
        ${row(t.travel, travelHtml(go, t, lang))}
        ${row(t.map, `<a href="${esc(go.map)}" rel="noopener noreferrer" lang="en">${F(go.path, go.map, 'mapsurl')}</a>`)}
        ${m.quotes.length ? row(t.why, `${esc(t.listing)}:<ul>${m.quotes.map(q => `<li>"<span lang="en">${F(q.path + '.quote', q.text)}</span>"
          ${q.source ? `<span class="small">(${esc(t.source)}: <span lang="en">${F(q.path + '.source_url', q.source)}</span>)</span>` : ''}<span hidden>${F(q.path + '.claim_id', q.claim)}</span></li>`).join('')}</ul>`) : ''}
        ${row(t.call, `<span data-device>${esc(outcomeText(m, t))}</span>`)}
        ${m.backup ? row(t.ifNot, `<span lang="en">${F(m.backup.path + '.name', m.backup.name)}</span>, ${F(m.backup.path + '.travel.km', m.backup.km, 'num')} ${esc(t.km)}. ${esc(t.phone)}: ${phoneHtml(m.backup) || esc(t.noPhone)}`) : ''}
        ${m.route ? row(t.route, `<ol>${m.route.map(g => `<li><strong lang="en">${F(g.path + '.name', g.name)}</strong>:
          ${g.stages.map(x => `${lang === 'hi' ? E(x.path + '.purpose_word', x.purpose, lang) : F(x.path + '.purpose_word', x.purpose)}${x.dwell != null
            ? ` (${esc(t.stay)} ${F(x.path + '.dwell_minutes', durText(x.dwell, lang), 'dur')})` : ''}`).join(', ')}.
          ${esc(t.about)} ${F(g.path + '.eta_low', g.low, 'num')}-${F(g.path + '.eta_high', g.high, 'num')} ${esc(t.min)}.
          ${esc(t.phone)}: ${phoneHtml(g) || esc(t.noPhone)}</li>`).join('')}</ol>`) : ''}
      </tbody></table>
      <p><strong>${esc(t.numbers)}</strong>${m.has102 ? ' ' + esc(t.n102) : ''}</p>
      <p>${esc(t.worse)} ${esc(t.note)}</p>
      <p class="slip-name">${esc(t.name)}</p>
      <p class="small"><span data-device>${esc(t.made)}: ${esc(madeIn(m.made, lang))}.</span> ${esc(t.asOf)}: ${F('as_of', m.asOf)}. ${esc(t.old)}</p>
    </article>`;
  }

  /** Family journey card (journey.js, loaded on first use): shares or downloads it; resolves to
   *  'shared' | 'downloaded' | 'cancelled'. The WhatsApp and SMS text slip above stay as the fallback. */
  function shareJourney(plan, lang, opts) {
    const go = () => root.RSJourney.shareJourney(plan, lang, opts);
    if (root.RSJourney) return go();
    return new Promise((ok, fail) => {
      const s = document.createElement('script');
      s.src = '/journey.js';
      s.onload = ok;
      s.onerror = fail;
      document.head.appendChild(s);
    }).then(go);
  }

  root.RSSlip = {slipModel, toHtml, toWhatsApp, toSms, lines, shareJourney, strings: T, util: {esc, stamp, routeModel}};
})(typeof window !== 'undefined' ? window : globalThis);
