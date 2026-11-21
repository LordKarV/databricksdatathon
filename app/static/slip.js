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
      listing: 'its listing says', source: 'source',
    },
    hi: {
      title: '\u0930\u0947\u092b\u0930\u0932 \u092a\u0930\u094d\u091a\u0940',
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
      ifNot: '\u0905\u0917\u0930 \u0928\u0939\u0940\u0902',
      call: '\u092b\u093c\u094b\u0928 \u0938\u0947 \u092a\u0942\u091b\u093e',
      noCall: '\u0905\u092d\u0940 \u092b\u093c\u094b\u0928 \u0938\u0947 \u092a\u0942\u091b\u093e \u0928\u0939\u0940\u0902\u0964 \u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      said: {
        yes: '\u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0901 \u0915\u0939\u093e',
        no: '\u092b\u093c\u094b\u0928 \u092a\u0930 \u0928\u093e \u0915\u0939\u093e',
        none: '\u092b\u093c\u094b\u0928 \u0928\u0939\u0940\u0902 \u0909\u0920\u093e',
        wrong: '\u0917\u0932\u0924 \u0928\u0902\u092c\u0930',
      },
      at: '',
      numbers: '\u0906\u092a\u093e\u0924 \u0938\u094d\u0925\u093f\u0924\u093f: 108 (\u090f\u092e\u094d\u092c\u0941\u0932\u0947\u0902\u0938, \u092e\u0941\u092b\u093c\u094d\u0924)\u0964',
      n102: '\u0917\u0930\u094d\u092d\u093e\u0935\u0938\u094d\u0925\u093e \u092f\u093e \u0936\u093f\u0936\u0941: 102 (\u092e\u0941\u092b\u093c\u094d\u0924)\u0964 \u091c\u0935\u093e\u092c \u0928\u0939\u0940\u0902? 108 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      worse: '\u092e\u0930\u0940\u091c\u093c \u0915\u0940 \u0939\u093e\u0932\u0924 \u092c\u093f\u0917\u0921\u093c\u0947 \u0924\u094b \u0938\u092c\u0938\u0947 \u0928\u091c\u093c\u0926\u0940\u0915\u0940 24x7 \u0907\u092e\u0930\u091c\u0947\u0902\u0938\u0940 \u092e\u0947\u0902 \u091c\u093e\u090f\u0901\u0964',
      note: '\u0921\u0949\u0915\u094d\u091f\u0930 \u0915\u0940 \u092a\u0930\u094d\u091a\u0940 \u0938\u093e\u0925 \u0930\u0916\u0947\u0902\u0964',
      name: '\u092e\u0930\u0940\u091c\u093c \u0915\u093e \u0928\u093e\u092e (\u0939\u093e\u0925 \u0938\u0947 \u0932\u093f\u0916\u0947\u0902): ____________',
      made: '\u092c\u0928\u093e\u0908 \u0917\u0908',
      asOf: '\u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u0921\u0947\u091f\u093e \u0915\u0940 \u0924\u093e\u0930\u0940\u0916',
      old: '\u092f\u0939 \u092a\u0930\u094d\u091a\u0940 \u090f\u0915 \u0926\u093f\u0928 \u0938\u0947 \u092a\u0941\u0930\u093e\u0928\u0940 \u0939\u094b \u0924\u094b \u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      ask: '\u092d\u0947\u091c\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092e\u0930\u0940\u091c\u093c \u0938\u0947 \u092a\u0942\u091b\u0947\u0902\u0964',
      draft: '(Hindi draft, not reviewed)',
      listing: '\u0907\u0938\u0915\u0940 \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0932\u093f\u0916\u093e \u0939\u0948',
      source: '\u0938\u094d\u0930\u094b\u0924',
    },
  };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
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
  function place(o) {
    return {name: o.name, town: o.town, address: o.address || o.town,
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
      go: place(option),
      backup: backup ? place(backup) : null,
      quotes: (option.evidence || []).slice(0, 3).map(e => ({text: e.quote, source: e.source_url})),
      outcome: callOutcome && OUTCOME_KEY[callOutcome.said]
        ? {key: OUTCOME_KEY[callOutcome.said], at: stamp(new Date(callOutcome.at)).slice(-5)} : null,
      stub: !!(plan.meta && plan.meta.stub),
    };
  }

  function travelText(g, t) {
    return `${g.km} ${t.km}, ${t.about} ${g.low}-${g.high} ${t.min} (${g.label})`;
  }
  function outcomeText(m, t) {
    return m.outcome ? `${t.said[m.outcome.key]}${t.at ? ' ' + t.at : ''} ${m.outcome.at}.` : t.noCall;
  }

  /** Plain-text lines shared by the WhatsApp text; same content as the printed slip. */
  function lines(m, lang) {
    const t = T[lang] || T.en;
    const out = [`${t.title.toUpperCase()}  ${m.made}`];
    if (t.draft) out.push(t.draft);
    if (m.stub) out.push('SAMPLE DATA, not a real referral.');
    out.push(`${t.service}: ${m.service[lang] || m.service.en}`);
    out.push(`${t.go}: ${m.go.name}, ${m.go.address}`);
    out.push(`${t.phone}: ${m.go.phone || t.noPhone}`);
    out.push(`${t.travel}: ${travelText(m.go, t)}`);
    out.push(`${t.map}: ${m.go.map}`);
    if (m.quotes.length) {
      out.push(`${t.why}: ${t.listing}:`);
      m.quotes.forEach(q => out.push(`- "${q.text}" (${t.source}: ${q.source})`));
    }
    out.push(`${t.call}: ${outcomeText(m, t)}`);
    if (m.backup) out.push(`${t.ifNot}: ${m.backup.name}, ${m.backup.km} ${t.km}. ${t.phone}: ${m.backup.phone || t.noPhone}`);
    out.push(t.numbers);
    if (m.has102) out.push(t.n102);
    out.push(t.worse, t.note);
    out.push(`${t.made}: ${m.made}. ${t.asOf}: ${m.asOf}.`, t.old);
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
      `${t.made} ${m.made}.`,
    ].filter(Boolean);
    let text = parts.join(' ').replace(/\s+/g, ' ').trim();
    if (text.length > 300) text = text.slice(0, 299) + '.';
    return {text, url: 'sms:?body=' + encodeURIComponent(text)};
  }

  /** Printable slip markup (one A5/A4 page with the print stylesheet). */
  function toHtml(m, lang) {
    const t = T[lang] || T.en;
    const row = (k, v) => `<tr><th scope="row">${esc(k)}</th><td>${v}</td></tr>`;
    const go = m.go;
    return `<article class="slip" lang="${lang === 'hi' ? 'hi' : 'en'}" aria-labelledby="slip-title">
      <h2 id="slip-title">${esc(t.title)} <span class="small">${esc(m.made)}</span></h2>
      ${t.draft ? `<p class="small" lang="en">${esc(t.draft)}</p>` : ''}
      ${m.stub ? '<p class="small" lang="en"><strong>Sample data, not a real referral.</strong></p>' : ''}
      <table class="slip-table"><tbody>
        ${row(t.service, esc(m.service[lang] || m.service.en))}
        ${row(t.go, `<strong>${esc(go.name)}</strong><br>${esc(go.address)}`)}
        ${row(t.phone, go.phone ? `<a href="tel:${esc(go.phone.replace(/[^+\d]/g, ''))}">${esc(go.phone)}</a>` : esc(t.noPhone))}
        ${row(t.travel, esc(travelText(go, t)))}
        ${row(t.map, `<a href="${esc(go.map)}" rel="noopener noreferrer">${esc(go.map)}</a>`)}
        ${m.quotes.length ? row(t.why, `${esc(t.listing)}:<ul>${m.quotes.map(q => `<li>"<span lang="und">${esc(q.text)}</span>"
          <span class="small">(${esc(t.source)}: ${esc(q.source)})</span></li>`).join('')}</ul>`) : ''}
        ${row(t.call, esc(outcomeText(m, t)))}
        ${m.backup ? row(t.ifNot, `${esc(m.backup.name)}, ${m.backup.km} ${esc(t.km)}. ${esc(t.phone)}: ${esc(m.backup.phone || t.noPhone)}`) : ''}
      </tbody></table>
      <p><strong>${esc(t.numbers)}</strong>${m.has102 ? ' ' + esc(t.n102) : ''}</p>
      <p>${esc(t.worse)} ${esc(t.note)}</p>
      <p class="slip-name">${esc(t.name)}</p>
      <p class="small">${esc(t.made)}: ${esc(m.made)}. ${esc(t.asOf)}: ${esc(m.asOf)}. ${esc(t.old)}</p>
    </article>`;
  }

  root.RSSlip = {slipModel, toHtml, toWhatsApp, toSms, lines, strings: T};
})(typeof window !== 'undefined' ? window : globalThis);
