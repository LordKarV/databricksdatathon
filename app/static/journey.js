// Family journey card: one self-contained HTML file the health worker sends to the patient's family (Web Share
// with files, else a download). It opens on any phone without a login and makes no network requests (CSP
// default-src 'none'). Built only from plan fields. Safety 13: no patient name, condition, age, origin point or
// confidence numbers; bands become plain words. Needs slip.js (window.RSSlip) loaded first; slip.js loads this.
'use strict';
(function (root) {
  const SL = root.RSSlip;
  const {esc, stamp, routeModel} = SL.util;
  // Hindi strings are drafts until native-speaker review (#10). Devanagari is \u-escaped to keep the file ASCII.
  const T = {
    en: {
      title: 'Journey card', sos: 'Emergency numbers', call108: 'Call 108', call102: 'Call 102',
      go: 'Where to go', stops: 'Go to these places, in this order', for: 'For', address: 'Address',
      geo: 'Open in map app', osm: 'Map (OpenStreetMap)', listed: 'Listed for this service', check: 'Call first to check',
      bring: 'What to bring', items: ['Any referral note from the health worker or doctor', 'Aadhaar card',
        'Ayushman / PMJAY or JSSK card', 'Previous reports', 'Medicines being taken now'],
      callTitle: 'Call before you go', ask: 'Ask', askDefault: 'Can you see a patient for this today?',
      notMedical: 'This is not a medical opinion; information may be out of date.',
      old: 'If this card is more than a day old, call before going.',
      read: 'Read aloud', big: 'Large print', print: 'Print', tools: 'Card tools',
      noSpeech: 'This phone cannot read aloud.', noHi: 'No Hindi voice on this phone, reading in English.',
      say108: 'In an emergency, call 1 0 8. The ambulance is free.', say102: 'Pregnancy or baby: call 1 0 2.',
      sayStop: 'Place', sayPhone: 'Phone', sayBring: 'Bring', sayAsk: 'Call before you go and ask',
    },
    hi: {
      title: '\u092f\u093e\u0924\u094d\u0930\u093e \u0915\u093e\u0930\u094d\u0921', sos: '\u0907\u092e\u0930\u091c\u0947\u0902\u0938\u0940 \u0928\u0902\u092c\u0930', call108: '108 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902', call102: '102 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902',
      go: '\u0915\u0939\u093e\u0901 \u091c\u093e\u090f\u0901', stops: '\u0907\u0928 \u091c\u0917\u0939\u094b\u0902 \u092a\u0930, \u0907\u0938\u0940 \u0915\u094d\u0930\u092e \u092e\u0947\u0902 \u091c\u093e\u090f\u0901', for: '\u0915\u093f\u0938\u0932\u093f\u090f', address: '\u092a\u0924\u093e',
      geo: '\u0928\u0915\u094d\u0936\u093e \u0910\u092a \u092e\u0947\u0902 \u0916\u094b\u0932\u0947\u0902', osm: '\u0928\u0915\u094d\u0936\u093e (OpenStreetMap)', listed: '\u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u092f\u0939 \u0938\u0947\u0935\u093e \u0932\u093f\u0916\u0940 \u0939\u0948',
      check: '\u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0915\u0947 \u092a\u0942\u091b\u0947\u0902',
      bring: '\u0938\u093e\u0925 \u0915\u094d\u092f\u093e \u0932\u0947 \u091c\u093e\u090f\u0901', items: ['\u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e \u092f\u093e \u0921\u0949\u0915\u094d\u091f\u0930 \u0915\u0940 \u0930\u0947\u092b\u093c\u0930\u0932 \u092a\u0930\u094d\u091a\u0940 (\u0905\u0917\u0930 \u0939\u0948)', '\u0906\u0927\u093e\u0930 \u0915\u093e\u0930\u094d\u0921',
        '\u0906\u092f\u0941\u0937\u094d\u092e\u093e\u0928 \u0915\u093e\u0930\u094d\u0921 \u092f\u093e \u091c\u091a\u094d\u091a\u093e-\u092c\u091a\u094d\u091a\u093e (MCP) \u0915\u093e\u0930\u094d\u0921', '\u092a\u0941\u0930\u093e\u0928\u0940 \u091c\u093e\u0901\u091a \u0930\u093f\u092a\u094b\u0930\u094d\u091f', '\u0905\u092d\u0940 \u091a\u0932 \u0930\u0939\u0940 \u0926\u0935\u093e\u0907\u092f\u093e\u0901'],
      callTitle: '\u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902', ask: '\u092a\u0942\u091b\u0947\u0902', askDefault: '\u0915\u094d\u092f\u093e \u0906\u091c \u0907\u0938\u0915\u0947 \u0932\u093f\u090f \u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0926\u0947\u0916 \u0938\u0915\u0924\u0947 \u0939\u0948\u0902?',
      notMedical: '\u092f\u0939 \u0921\u0949\u0915\u094d\u091f\u0930 \u0915\u0940 \u0938\u0932\u093e\u0939 \u0928\u0939\u0940\u0902 \u0939\u0948; \u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u092a\u0941\u0930\u093e\u0928\u0940 \u0939\u094b \u0938\u0915\u0924\u0940 \u0939\u0948\u0964',
      old: '\u092f\u0939 \u0915\u093e\u0930\u094d\u0921 \u090f\u0915 \u0926\u093f\u0928 \u0938\u0947 \u092a\u0941\u0930\u093e\u0928\u093e \u0939\u094b \u0924\u094b \u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      read: '\u092a\u0922\u093c\u0915\u0930 \u0938\u0941\u0928\u093e\u090f\u0901', big: '\u092c\u0921\u093c\u0947 \u0905\u0915\u094d\u0937\u0930', print: '\u092a\u094d\u0930\u093f\u0902\u091f \u0915\u0930\u0947\u0902', tools: '\u0915\u093e\u0930\u094d\u0921 \u0915\u0947 \u092c\u091f\u0928',
      noSpeech: '\u092f\u0939 \u092b\u093c\u094b\u0928 \u092a\u0922\u093c\u0915\u0930 \u0928\u0939\u0940\u0902 \u0938\u0941\u0928\u093e \u0938\u0915\u0924\u093e\u0964', noHi: '\u0907\u0938 \u092b\u093c\u094b\u0928 \u092e\u0947\u0902 \u0939\u093f\u0928\u094d\u0926\u0940 \u0906\u0935\u093e\u091c\u093c \u0928\u0939\u0940\u0902 \u0939\u0948, \u0905\u0902\u0917\u094d\u0930\u0947\u091c\u093c\u0940 \u092e\u0947\u0902 \u092a\u0922\u093c \u0930\u0939\u0947 \u0939\u0948\u0902\u0964',
      say108: '\u0907\u092e\u0930\u091c\u0947\u0902\u0938\u0940 \u092e\u0947\u0902 1 0 8 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964 \u090f\u092e\u094d\u092c\u0941\u0932\u0947\u0902\u0938 \u092e\u0941\u092b\u093c\u094d\u0924 \u0939\u0948\u0964',
      say102: '\u0917\u0930\u094d\u092d\u0935\u0924\u0940 \u092e\u0939\u093f\u0932\u093e \u092f\u093e \u0936\u093f\u0936\u0941 \u0915\u0947 \u0932\u093f\u090f 1 0 2 \u092a\u0930 \u092b\u093c\u094b\u0928 \u0915\u0930\u0947\u0902\u0964',
      sayStop: '\u091c\u0917\u0939', sayPhone: '\u092b\u093c\u094b\u0928', sayBring: '\u0938\u093e\u0925 \u0932\u0947 \u091c\u093e\u090f\u0901', sayAsk: '\u091c\u093e\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0915\u0947 \u092a\u0942\u091b\u0947\u0902',
    },
  };
  const get = (o, path) => path.split('.').reduce((v, k) => (v == null ? v : v[k]), o);
  const val = (text, path, lang) => (text == null || text === '' ? null : {text: String(text), path, lang});

  function phoneOf(ph, base) {
    if (!ph || !ph.e164) return null;
    const key = ph.display ? 'display' : 'e164';
    return {text: ph[key], path: `${base}.phone.${key}`, tel: ph.e164};
  }
  function pointOf(plan, i) {
    const o = plan.options[i];
    return o && Number.isFinite(o.lat) && Number.isFinite(o.lon) ? {lat: o.lat, lon: o.lon, path: `options.${i}`} : null;
  }
  function uniqText(xs) {
    return xs.filter((x, k) => x && xs.findIndex(y => y && y.text === x.text) === k);
  }

  // "Listed for this service" only for a Likely option that no health-worker reports disagree with.
  const listed = o => !!o && o.band === 'likely' && !(o.field && o.field.disagree);

  // A multi-stop route (#47) when it visits more than one hospital and the worker is on the first option;
  // otherwise the one option the slip is for.
  function stopsOf(plan, rank, lang) {
    const route = routeModel(plan);
    if (route && route.length > 1 && rank === 1) {
      return route.map(g => {
        const i = plan.options.findIndex(o => o.facility_id === g.id);
        const o = plan.options[i];
        return {
          name: val(g.name, g.path + '.name'),
          address: o && o.address ? val(o.address, `options.${i}.address`) : val(get(plan, g.path + '.place'), g.path + '.place'),
          phone: phoneOf(get(plan, g.path + '.phone'), g.path),
          purposes: g.stages.map(x => val(x.purpose, x.path + '.purpose_word', 'en')).filter(Boolean),
          listed: listed(o),
          point: i >= 0 ? pointOf(plan, i) : null,
          questions: uniqText(g.stages.map(x => val(get(plan, x.path + '.question'), x.path + '.question', 'en'))),
        };
      });
    }
    const i = plan.options.findIndex(o => o.rank === rank);
    if (i < 0) throw new Error(`no option with rank ${rank}`);
    const o = plan.options[i];
    const svc = lang === 'hi' && plan.query.service_label.hi ? 'hi' : 'en';
    return [{
      name: val(o.name, `options.${i}.name`),
      address: o.address ? val(o.address, `options.${i}.address`) : val(o.town, `options.${i}.town`),
      phone: phoneOf(o.phone, `options.${i}`),
      purposes: [val(plan.query.service_label[svc], `query.service_label.${svc}`, svc)],
      listed: listed(o),
      point: pointOf(plan, i),
      questions: uniqText((o.call_ahead || []).map((q, j) => val(q.question, `options.${i}.call_ahead.${j}.question`, 'en'))),
    }];
  }

  function cardModel(plan, lang, opts) {
    const n102 = (plan.emergency_numbers || []).findIndex(n => n.number === '102');
    return {
      lang, made: stamp(new Date(opts.now ?? Date.now())), asOf: val(plan.as_of, 'as_of'),
      has102: n102 >= 0, n102Path: `emergency_numbers.${n102}.number`,
      stub: !!(plan.meta && plan.meta.stub), stops: stopsOf(plan, opts.rank ?? 1, lang),
    };
  }
  function fieldsOf(m) {
    const out = m.asOf ? [m.asOf.path] : [];
    if (m.has102) out.push(m.n102Path);
    m.stops.forEach(s => {
      [s.name, s.address, s.phone, ...s.purposes, ...s.questions].forEach(v => v && out.push(v.path));
      if (s.point) out.push(s.point.path + '.lat', s.point.path + '.lon');
    });
    return [...new Set(out)];
  }

  // Map links carry the facility point only; never the patient's location.
  const geoUrl = p => `geo:${p.lat},${p.lon}?q=${p.lat},${p.lon}`;
  const osmUrl = p => `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=16/${p.lat}/${p.lon}`;
  const digits = s => s.replace(/\D/g, '').split('').join(' ');  // read a phone number digit by digit

  function F(v, card) {
    const l = v.lang && v.lang !== card ? ` lang="${v.lang}"` : '';
    return `<span data-f="${v.path}"${l}>${esc(v.text)}</span>`;
  }
  function stopHtml(s, m, t, ts) {
    const tel = s.phone ? `<a class="btn" href="tel:${esc(s.phone.tel)}">${F(s.phone, m.lang)}</a>` : esc(ts.noPhone);
    return `<li><h3>${F(s.name, m.lang)}</h3>
<p>${esc(t.for)}: ${s.purposes.map(v => F(v, m.lang)).join(', ')}</p>
<p class="band">${esc(s.listed ? t.listed : t.check)}</p>
${s.address ? `<p>${esc(t.address)}: ${F(s.address, m.lang)}</p>` : ''}
<p>${esc(ts.phone)}: ${tel}</p>
${s.point ? `<p class="noprint"><a class="btn" href="${esc(geoUrl(s.point))}">${esc(t.geo)}</a>
<a class="btn" href="${esc(osmUrl(s.point))}" rel="noopener noreferrer">${esc(t.osm)}</a></p>` : ''}</li>`;
  }
  function askHtml(s, m, t) {
    const qs = s.questions.length ? s.questions.map(q => `<li>${F(q, m.lang)}</li>`).join('') : `<li>${esc(t.askDefault)}</li>`;
    return `<p><strong>${F(s.name, m.lang)}</strong>. ${esc(t.ask)}:</p><ul>${qs}</ul>`;
  }

  // No decimals in the CSS: the tests reject anything that reads like a confidence number (0.x).
  const CSS = `*{box-sizing:border-box}body{margin:0;background:#fff;color:#111;font:18px/1.5 system-ui,sans-serif}
main{max-width:40rem;margin:0 auto;padding:16px}h1{font-size:1.6em;margin:0 0 8px}
h2{font-size:1.25em;margin:24px 0 8px;border-top:2px solid #111;padding-top:12px}h3{font-size:1.2em;margin:0}
.sos{border:3px solid #b00020;border-radius:8px;padding:12px}
.call{display:block;min-height:56px;margin:0 0 8px;padding:10px;border-radius:8px;background:#b00020;color:#fff;
font-size:1.6em;font-weight:700;text-align:center;text-decoration:none}
.btn,button{display:inline-flex;align-items:center;min-height:44px;min-width:44px;margin:4px 8px 4px 0;padding:8px 14px;
border:2px solid #0b3d91;border-radius:8px;background:#fff;color:#0b3d91;font:inherit;text-decoration:none}
button[aria-pressed=true]{background:#0b3d91;color:#fff}a:focus-visible,button:focus-visible{outline:3px solid #111;outline-offset:3px}
.stops>li{margin:0 0 16px}.band{font-weight:700}.small{font-size:1em;color:#333}body.big{font-size:28px}
@media print{.noprint{display:none!important}body,body.big{font-size:12pt}.call{background:#fff;color:#111;border:2px solid #111}
.btn{border:0;padding:0;min-height:0;color:#111}li{break-inside:avoid}h2{break-after:avoid}}`;
  // Runs inside the card. It reads only the card's own speech lines (#say); no network, no storage.
  const JS = `(function(){var d=document,S=JSON.parse(d.getElementById('say').textContent),n=d.getElementById('note'),
r=d.getElementById('read'),ss=window.speechSynthesis;
d.getElementById('big').onclick=function(){this.setAttribute('aria-pressed',d.body.classList.toggle('big'))};
d.getElementById('print').onclick=function(){window.print()};
if(!ss||!window.SpeechSynthesisUtterance){r.hidden=true;n.textContent=S.noSpeech;return}
r.onclick=function(){if(ss.speaking){ss.cancel();r.setAttribute('aria-pressed','false');return}
var v=ss.getVoices(),hi=S.lang==='hi'&&(!v.length||v.some(function(x){return /^hi/i.test(x.lang)})),L=hi?S.hi:S.en;
n.textContent=S.lang==='hi'&&!hi?S.noHi:'';r.setAttribute('aria-pressed','true');
L.forEach(function(t,i){var u=new SpeechSynthesisUtterance(t);u.lang=hi?'hi-IN':'en-IN';
if(i===L.length-1)u.onend=function(){r.setAttribute('aria-pressed','false')};ss.speak(u)})}})();`;

  /** Fixed spoken templates, filled only from the card model. */
  function speech(m, lang) {
    const t = T[lang];
    const out = [`${t.title}.`, t.say108];
    if (m.has102) out.push(t.say102);
    m.stops.forEach((s, k) => {
      out.push(`${t.sayStop} ${k + 1}: ${s.name.text}. ${t.for}: ${s.purposes.map(v => v.text).join(', ')}. ` +
        `${s.listed ? t.listed : t.check}.`);
      if (s.address) out.push(`${t.address}: ${s.address.text}.`);
      if (s.phone) out.push(`${t.sayPhone}: ${digits(s.phone.text)}.`);
    });
    out.push(`${t.sayBring}: ${t.items.join(', ')}.`);
    m.stops.forEach(s => out.push(`${t.sayAsk}, ${s.name.text}: ` +
      (s.questions.length ? s.questions.map(q => q.text).join(' ') : t.askDefault)));
    out.push(t.notMedical, t.old);
    return out;
  }

  function toHtml(m) {
    const t = T[m.lang], ts = SL.strings[m.lang];
    const say = {lang: m.lang, en: speech(m, 'en'), noSpeech: t.noSpeech, noHi: t.noHi};
    if (m.lang === 'hi') say.hi = speech(m, 'hi');
    const sayJson = JSON.stringify(say).replace(/</g, '\\u003c');
    return `<!doctype html><html lang="${m.lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>${esc(t.title)}</title><style>${CSS}</style></head><body><main>
<h1>${esc(t.title)}</h1>
${ts.draft ? `<p class="small" lang="en">${esc(ts.draft)}</p>` : ''}
${m.stub ? '<p lang="en"><strong>SAMPLE DATA, not a real referral.</strong></p>' : ''}
<div class="noprint" role="group" aria-label="${esc(t.tools)}"><button type="button" id="read" aria-pressed="false">${esc(t.read)}</button>
<button type="button" id="big" aria-pressed="false">${esc(t.big)}</button><button type="button" id="print">${esc(t.print)}</button></div>
<p id="note" class="small" role="status" aria-live="polite"></p>
<section class="sos" aria-label="${esc(t.sos)}"><a class="call" href="tel:108">${esc(t.call108)}</a>
${m.has102 ? `<a class="call" href="tel:102">${esc(t.call102)}</a>` : ''}
<p><strong>${esc(ts.numbers)}</strong>${m.has102 ? ' ' + esc(ts.n102) : ''}</p><p>${esc(ts.worse)}</p></section>
<h2>${esc(m.stops.length > 1 ? t.stops : t.go)}</h2>
<ol class="stops">${m.stops.map(s => stopHtml(s, m, t, ts)).join('')}</ol>
<h2>${esc(t.bring)}</h2><ul>${t.items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>
<h2>${esc(t.callTitle)}</h2>${m.stops.map(s => askHtml(s, m, t)).join('')}
<h2>${esc(t.notMedical)}</h2>
<p class="small"><span data-device>${esc(ts.made)}: ${esc(m.made)}.</span>
${m.asOf ? `${esc(ts.asOf)}: ${F(m.asOf, m.lang)}.` : ''} ${esc(t.old)}</p>
</main><script type="application/json" id="say">${sayJson}</script><script>${JS}</script></body></html>`;
  }

  function toText(m) {
    const t = T[m.lang], ts = SL.strings[m.lang];
    const out = [`${t.title.toUpperCase()}  ${m.made}`];
    if (ts.draft) out.push(ts.draft);
    if (m.stub) out.push('SAMPLE DATA, not a real referral.');
    out.push(ts.numbers + (m.has102 ? ' ' + ts.n102 : ''), '', `${m.stops.length > 1 ? t.stops : t.go}:`);
    m.stops.forEach((s, k) => {
      out.push(`${k + 1}. ${s.name.text} (${t.for}: ${s.purposes.map(v => v.text).join(', ')}). ${s.listed ? t.listed : t.check}.`);
      if (s.address) out.push(`   ${t.address}: ${s.address.text}`);
      out.push(`   ${ts.phone}: ${s.phone ? s.phone.text : ts.noPhone}`);
      if (s.point) out.push(`   ${ts.map}: ${osmUrl(s.point)}`);
    });
    out.push('', `${t.bring}: ${t.items.join('; ')}.`, '', `${t.callTitle}:`);
    m.stops.forEach(s => out.push(`${s.name.text}. ${t.ask}: ` + (s.questions.length ? s.questions.map(q => q.text).join(' ') : t.askDefault)));
    out.push('', t.notMedical, `${ts.made}: ${m.made}.` + (m.asOf ? ` ${ts.asOf}: ${m.asOf.text}.` : ''), t.old);
    return out.join('\n');
  }

  /** {html, text, fields}: the card file, the same card as plain text, and the payload paths it shows.
   *  opts: {rank = 1, now = Date.now()}. Throws when the plan has no option with that rank (abstention). */
  function buildJourney(plan, lang, opts = {}) {
    const m = cardModel(plan, lang === 'hi' ? 'hi' : 'en', opts);
    return {html: toHtml(m), text: toText(m), fields: fieldsOf(m)};
  }

  /** Shares the card file where the phone supports it (WhatsApp on Android), else downloads it. */
  async function shareJourney(plan, lang, opts = {}) {
    const card = buildJourney(plan, lang, opts);
    const d = new Date(opts.now ?? Date.now());
    const name = `journey-card-${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}.html`;
    const file = new File([card.html], name, {type: 'text/html'});
    const nav = root.navigator;
    if (nav && nav.canShare && nav.canShare({files: [file]})) {
      try {
        await nav.share({files: [file], title: T[lang === 'hi' ? 'hi' : 'en'].title});
        return 'shared';
      } catch (e) {
        if (e && e.name === 'AbortError') return 'cancelled';
        // Any other share error (NotAllowedError, unsupported target): fall through to the download.
      }
    }
    const a = root.document.createElement('a');
    a.href = URL.createObjectURL(file);
    a.download = name;
    root.document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    return 'downloaded';
  }

  root.RSJourney = {buildJourney, shareJourney, strings: T};
})(typeof window !== 'undefined' ? window : globalThis);
