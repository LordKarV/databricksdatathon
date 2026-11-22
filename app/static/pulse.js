// "Your area" panel: anonymous district counts from /api/pulse, for coordinators and planners. Loaded lazily on
// #/pulse; the hook is RSPulse.initPulse(container, opts). The server builds the sentences ({en, hi}) and leaves
// out every cell too small to show (community/pulse.py); this file only lays them out. Bars are CSS with the value
// in text.
'use strict';
(function (root) {
  // Hindi strings are drafts until native-speaker review (#10).
  const T = {
    en: {
      title: 'Your area', lang: 'Language', draft: '',
      intro: 'What health workers logged after calls and referrals in one district. No patient data. For coordinators and planners.',
      district: 'District', service: 'Service', all: 'All services', show: 'Show', loading: 'Loading...',
      needDistrict: 'Type a district name.',
      badDistrict: 'We do not know that district. Check the spelling.',
      unavailable: 'Area reports are not available right now: the report store cannot be reached. Searching and calling still work.',
      offline: 'No internet. Area reports need a connection; the rest of the app works offline.',
      sim: 'Simulated for the demo: these reports are made up to show this screen. They are not real.',
      win: d => `Last ${d} days`, since: (a, b) => `Counted in whole weeks from ${a} to ${b}.`,
      services: 'Services with the most reports', facilities: 'Most-used facilities',
      reasons: 'Why the answer was no or the patient was turned away', reports: 'reports', referrals: 'referrals',
      accepted: 'accepted', turnedAway: 'turned away', listing: 'Its listing says', source: 'source',
      band: 'Label in the app today', noBand: 'not listed for this service in our data', card: 'Open its card',
      howTitle: 'How this is counted',
      how: r => [
        'Only reports that health workers logged after a call or a referral count. The app does not record searches.',
        `A number for a service is shown only when at least ${r.min_reporters} different health workers and ${r.min_reports} reports are behind it; a number for one facility or one kind of reason needs ${r.detail_min_reporters} and ${r.detail_min_reports}.`,
        `Dates are rounded to the week (weeks start on ${r.week_starts}). "Last 90 days" means the 13 whole weeks before this week, so the numbers do not change during a week.`,
        'The acceptance range is a 95% Wilson interval. With few reports it is wide, and the true rate could be anywhere in it.',
        'A yes on the phone is what the person who answered said, not a confirmation. These counts do not change the labels the app shows.',
        'The district comes from the nearest PIN to a rounded location. Coordinates are never stored.',
      ],
    },
    hi: {
      title: '\u0906\u092a\u0915\u093e \u0915\u094d\u0937\u0947\u0924\u094d\u0930', lang: '\u092d\u093e\u0937\u093e', draft: '(Hindi draft, not reviewed)',
      intro: '\u090f\u0915 \u091c\u093c\u093f\u0932\u0947 \u092e\u0947\u0902 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0928\u0947 \u092b\u093c\u094b\u0928 \u0914\u0930 \u0930\u0947\u092b\u093c\u0930\u0932 \u0915\u0947 \u092c\u093e\u0926 \u0915\u094d\u092f\u093e \u0926\u0930\u094d\u091c \u0915\u093f\u092f\u093e\u0964 \u092e\u0930\u0940\u091c\u093c \u0915\u0940 \u0915\u094b\u0908 \u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0928\u0939\u0940\u0902\u0964 \u0938\u092e\u0928\u094d\u0935\u092f\u0915\u094b\u0902 \u0914\u0930 \u092f\u094b\u091c\u0928\u093e\u0915\u093e\u0930\u094b\u0902 \u0915\u0947 \u0932\u093f\u090f\u0964',
      district: '\u091c\u093c\u093f\u0932\u093e', service: '\u0938\u0947\u0935\u093e', all: '\u0938\u092d\u0940 \u0938\u0947\u0935\u093e\u090f\u0901', show: '\u0926\u093f\u0916\u093e\u090f\u0901', loading: '\u0932\u094b\u0921 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...',
      needDistrict: '\u091c\u093c\u093f\u0932\u0947 \u0915\u093e \u0928\u093e\u092e \u0932\u093f\u0916\u0947\u0902\u0964',
      badDistrict: '\u092f\u0939 \u091c\u093c\u093f\u0932\u093e \u0939\u092e\u0947\u0902 \u0928\u0939\u0940\u0902 \u092e\u093f\u0932\u093e\u0964 \u0938\u094d\u092a\u0947\u0932\u093f\u0902\u0917 \u091c\u093e\u0901\u091a\u0947\u0902\u0964',
      unavailable: '\u0915\u094d\u0937\u0947\u0924\u094d\u0930 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0905\u092d\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902 \u0939\u0948\u0902: \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u094d\u091f\u094b\u0930 \u0938\u0947 \u091c\u0941\u0921\u093c \u0928\u0939\u0940\u0902 \u092a\u093e\u090f\u0964 \u0916\u094b\u091c \u0914\u0930 \u092b\u093c\u094b\u0928 \u0905\u092c \u092d\u0940 \u0915\u093e\u092e \u0915\u0930\u0924\u0947 \u0939\u0948\u0902\u0964',
      offline: '\u0907\u0902\u091f\u0930\u0928\u0947\u091f \u0928\u0939\u0940\u0902 \u0939\u0948\u0964 \u0915\u094d\u0937\u0947\u0924\u094d\u0930 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0915\u0947 \u0932\u093f\u090f \u0907\u0902\u091f\u0930\u0928\u0947\u091f \u091a\u093e\u0939\u093f\u090f; \u092c\u093e\u0915\u0940 \u0910\u092a \u092c\u093f\u0928\u093e \u0907\u0902\u091f\u0930\u0928\u0947\u091f \u091a\u0932\u0924\u093e \u0939\u0948\u0964',
      sim: '\u0921\u0947\u092e\u094b \u0915\u0947 \u0932\u093f\u090f \u0928\u0915\u0932\u0940 \u0906\u0901\u0915\u0921\u093c\u0947: \u092f\u0947 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u093f\u0930\u094d\u092b\u093c \u092f\u0939 \u0938\u094d\u0915\u094d\u0930\u0940\u0928 \u0926\u093f\u0916\u093e\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u092c\u0928\u093e\u0908 \u0917\u0908 \u0939\u0948\u0902\u0964 \u092f\u0947 \u0905\u0938\u0932\u0940 \u0928\u0939\u0940\u0902 \u0939\u0948\u0902\u0964',
      win: d => `\u092a\u093f\u091b\u0932\u0947 ${d} \u0926\u093f\u0928`, since: (a, b) => `${a} \u0938\u0947 ${b} \u0924\u0915 \u092a\u0942\u0930\u0947 \u0939\u092b\u093c\u094d\u0924\u094b\u0902 \u092e\u0947\u0902 \u0917\u093f\u0928\u093e \u0917\u092f\u093e\u0964`,
      services: '\u0938\u092c\u0938\u0947 \u091c\u093c\u094d\u092f\u093e\u0926\u093e \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0935\u093e\u0932\u0940 \u0938\u0947\u0935\u093e\u090f\u0901', facilities: '\u0938\u092c\u0938\u0947 \u091c\u093c\u094d\u092f\u093e\u0926\u093e \u0907\u0938\u094d\u0924\u0947\u092e\u093e\u0932 \u0939\u0941\u090f \u0905\u0938\u094d\u092a\u0924\u093e\u0932',
      reasons: '\u0928\u093e \u0915\u0939\u0928\u0947 \u092f\u093e \u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u094c\u091f\u093e\u0928\u0947 \u0915\u0940 \u0935\u091c\u0939', reports: '\u0930\u093f\u092a\u094b\u0930\u094d\u091f', referrals: '\u0930\u0947\u092b\u093c\u0930\u0932',
      accepted: '\u0932\u093f\u092f\u093e \u0917\u092f\u093e', turnedAway: '\u0932\u094c\u091f\u093e\u092f\u093e \u0917\u092f\u093e', listing: '\u0907\u0938\u0915\u0940 \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0932\u093f\u0916\u093e \u0939\u0948', source: '\u0938\u094d\u0930\u094b\u0924',
      band: '\u0906\u091c \u0910\u092a \u092e\u0947\u0902 \u0932\u0947\u092c\u0932', noBand: '\u0939\u092e\u093e\u0930\u0947 \u0921\u0947\u091f\u093e \u092e\u0947\u0902 \u0907\u0938 \u0938\u0947\u0935\u093e \u0915\u0947 \u0932\u093f\u090f \u0926\u0930\u094d\u091c \u0928\u0939\u0940\u0902', card: '\u0907\u0938\u0915\u093e \u0915\u093e\u0930\u094d\u0921 \u0916\u094b\u0932\u0947\u0902',
      howTitle: '\u092f\u0939 \u0915\u0948\u0938\u0947 \u0917\u093f\u0928\u093e \u091c\u093e\u0924\u093e \u0939\u0948',
      how: r => [
        '\u0938\u093f\u0930\u094d\u092b\u093c \u0935\u0939\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0917\u093f\u0928\u0940 \u091c\u093e\u0924\u0940 \u0939\u0948\u0902 \u091c\u094b \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0928\u0947 \u092b\u093c\u094b\u0928 \u092f\u093e \u0930\u0947\u092b\u093c\u0930\u0932 \u0915\u0947 \u092c\u093e\u0926 \u0926\u0930\u094d\u091c \u0915\u0940\u0902\u0964 \u0910\u092a \u0916\u094b\u091c \u0926\u0930\u094d\u091c \u0928\u0939\u0940\u0902 \u0915\u0930\u0924\u093e\u0964',
        `\u0915\u093f\u0938\u0940 \u0938\u0947\u0935\u093e \u0915\u0940 \u0938\u0902\u0916\u094d\u092f\u093e \u0924\u092d\u0940 \u0926\u093f\u0916\u0924\u0940 \u0939\u0948 \u091c\u092c \u0909\u0938\u0915\u0947 \u092a\u0940\u091b\u0947 \u0915\u092e \u0938\u0947 \u0915\u092e ${r.min_reporters} \u0905\u0932\u0917 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e \u0914\u0930 ${r.min_reports} \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0939\u094b\u0902; \u0915\u093f\u0938\u0940 \u090f\u0915 \u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u092f\u093e \u090f\u0915 \u0924\u0930\u0939 \u0915\u0940 \u0935\u091c\u0939 \u0915\u0940 \u0938\u0902\u0916\u094d\u092f\u093e \u0915\u0947 \u0932\u093f\u090f ${r.detail_min_reporters} \u0914\u0930 ${r.detail_min_reports} \u091a\u093e\u0939\u093f\u090f\u0964`,
        '\u0924\u093e\u0930\u0940\u0916\u0947\u0902 \u0939\u092b\u093c\u094d\u0924\u0947 \u0924\u0915 \u0917\u094b\u0932 \u0915\u0940 \u091c\u093e\u0924\u0940 \u0939\u0948\u0902 (\u0939\u092b\u093c\u094d\u0924\u093e \u0938\u094b\u092e\u0935\u093e\u0930 \u0938\u0947)\u0964 "\u092a\u093f\u091b\u0932\u0947 90 \u0926\u093f\u0928" \u0915\u093e \u092e\u0924\u0932\u092c \u0907\u0938 \u0939\u092b\u093c\u094d\u0924\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u0915\u0947 13 \u092a\u0942\u0930\u0947 \u0939\u092b\u093c\u094d\u0924\u0947 \u0939\u0948\u0902, \u0907\u0938\u0932\u093f\u090f \u0939\u092b\u093c\u094d\u0924\u0947 \u092d\u0930 \u0938\u0902\u0916\u094d\u092f\u093e\u090f\u0901 \u0928\u0939\u0940\u0902 \u092c\u0926\u0932\u0924\u0940\u0902\u0964',
        '\u0938\u094d\u0935\u0940\u0915\u093e\u0930 \u0939\u094b\u0928\u0947 \u0915\u093e \u0926\u093e\u092f\u0930\u093e 95% Wilson \u0926\u093e\u092f\u0930\u093e \u0939\u0948\u0964 \u0915\u092e \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0939\u094b\u0902 \u0924\u094b \u092f\u0939 \u091a\u094c\u0921\u093c\u093e \u0939\u094b\u0924\u093e \u0939\u0948, \u0914\u0930 \u0905\u0938\u0932\u0940 \u0926\u0930 \u0907\u0938\u092e\u0947\u0902 \u0915\u0939\u0940\u0902 \u092d\u0940 \u0939\u094b \u0938\u0915\u0924\u0940 \u0939\u0948\u0964',
        '\u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0901 \u0938\u093f\u0930\u094d\u092b\u093c \u091c\u0935\u093e\u092c \u0926\u0947\u0928\u0947 \u0935\u093e\u0932\u0947 \u0915\u0940 \u092c\u093e\u0924 \u0939\u0948, \u092a\u0915\u094d\u0915\u0940 \u092a\u0941\u0937\u094d\u091f\u093f \u0928\u0939\u0940\u0902\u0964 \u0907\u0928 \u0938\u0902\u0916\u094d\u092f\u093e\u0913\u0902 \u0938\u0947 \u0910\u092a \u0915\u0947 \u0932\u0947\u092c\u0932 \u0928\u0939\u0940\u0902 \u092c\u0926\u0932\u0924\u0947\u0964',
        '\u091c\u093c\u093f\u0932\u093e \u0917\u094b\u0932 \u0915\u0940 \u0917\u0908 \u091c\u0917\u0939 \u0915\u0947 \u0938\u092c\u0938\u0947 \u0928\u091c\u093c\u0926\u0940\u0915\u0940 PIN \u0938\u0947 \u0932\u093f\u092f\u093e \u091c\u093e\u0924\u093e \u0939\u0948\u0964 \u0928\u093f\u0930\u094d\u0926\u0947\u0936\u093e\u0902\u0915 \u0915\u092d\u0940 \u0938\u0947\u0935 \u0928\u0939\u0940\u0902 \u0939\u094b\u0924\u0947\u0964',
      ],
    },
  };
  const BAND = {
    en: {likely: 'Likely', not_verified: 'Not verified', unlikely: 'Unlikely'},
    hi: {likely: '\u0938\u0902\u092d\u093e\u0935\u093f\u0924', not_verified: '\u092a\u0941\u0937\u094d\u091f\u093f \u0928\u0939\u0940\u0902', unlikely: '\u0938\u0902\u092d\u093e\u0935\u0928\u093e \u0915\u092e'},
  };
  // The two reason classes of outcomes.REASONS_NOT_OFFERED / REASONS_TEMPORARY; single reasons are never shown.
  const REASON = {
    en: {not_offered: 'does not offer', temporary: 'temporarily unavailable'},
    hi: {not_offered: '\u0938\u0947\u0935\u093e \u0928\u0939\u0940\u0902 \u0926\u0947\u0924\u0947', temporary: '\u0905\u092d\u0940 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902'},
  };
  const CSS = `.pulse-bars{list-style:none;padding:0;margin:6px 0}
.pulse-bars li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 8px;margin:8px 0}
.pulse-track{grid-column:1/-1;height:10px;background:var(--card);border:1px solid var(--line);border-radius:5px}
.pulse-fill{display:block;height:100%;background:var(--accent);border-radius:4px}
.pulse-val{font-variant-numeric:tabular-nums}
.pulse-form{display:grid;gap:8px}.pulse-form input{font:inherit;width:100%;min-height:48px;padding:8px 10px;
border:2px solid var(--muted);border-radius:8px;background:var(--bg);color:var(--fg)}`;

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
  function getLang() {
    try { const l = localStorage.getItem('rs.pulseLang'); if (l === 'en' || l === 'hi') return l; } catch { /* private mode */ }
    return (navigator.language || '').startsWith('hi') ? 'hi' : 'en';
  }
  function setLang(l) { try { localStorage.setItem('rs.pulseLang', l); } catch { /* private mode */ } }
  function svcName(opts, id, lang) {
    const s = (opts.services || []).find(x => x.key === id);
    return s ? (s[lang] || s.en) : id.replace(/_/g, ' ');
  }
  function bars(items) {
    const max = Math.max(1, ...items.map(i => i.n));
    return `<ul class="pulse-bars">${items.map(i => `<li><span>${esc(i.label)}</span>
      <span class="pulse-val">${esc(i.value)}</span>
      <span class="pulse-track" aria-hidden="true"><span class="pulse-fill" style="width:${Math.round(100 * i.n / max)}%"></span></span></li>`).join('')}</ul>`;
  }
  function facility(f, t, lang, opts) {
    const card = (opts.cards || {})[f.facility_id];
    const ev = f.evidence;
    return `<li><strong>${esc(f.name || f.facility_id)}</strong>
      <p>${f.reports} ${esc(t.reports)}: ${f.accepted} ${esc(t.accepted)}, ${f.turned_away} ${esc(t.turnedAway)}.
        ${esc(t.band)}: ${esc(f.band ? BAND[lang][f.band] : t.noBand)}.</p>
      ${ev ? `<p class="small">${esc(t.listing)}: "<span lang="und">${esc(ev.quote)}</span>"
        ${ev.source_url ? `(<a href="${esc(ev.source_url)}" rel="noopener noreferrer">${esc(t.source)}</a>)` : ''}</p>` : ''}
      ${card ? `<a class="btn" href="${esc(card)}">${esc(t.card)}</a>` : ''}</li>`;
  }
  function windowHtml(w, t, lang, opts, note) {
    const svc = w.services.map(s => ({label: svcName(opts, s.service_id, lang), n: s.reports,
      value: `${s.reports} ${t.reports}`}));
    const rsn = w.reasons.map(r => ({label: `${svcName(opts, r.service_id, lang)}: ${REASON[lang][r.class]}`,
      n: r.n, value: `${r.n} ${t.reports}`}));
    return `<section aria-labelledby="pw-${w.days}"><h2 id="pw-${w.days}">${esc(t.win(w.days))}</h2>
      <p class="small muted">${esc(t.since(w.since_week, w.through))}</p>
      ${w.empty ? `<p>${esc(w.empty[lang])}</p>` : ''}
      ${w.services.map(s => `<p>${esc(s.text[lang])}</p>`).join('')}
      ${svc.length ? `<h3>${esc(t.services)}</h3>${bars(svc)}` : ''}
      ${w.facilities.length ? `<h3>${esc(t.facilities)}</h3>
        <ul>${w.facilities.map(f => facility(f, t, lang, opts)).join('')}</ul>` : ''}
      ${rsn.length ? `<h3>${esc(t.reasons)}</h3>${bars(rsn)}` : ''}
      <p class="small muted">${esc(note[lang])}</p></section>`;
  }
  function resultHtml(d, lang, opts) {
    const t = T[lang];
    return `${d.simulated ? `<p class="card"><strong>${esc(t.sim)}</strong></p>` : ''}
      ${windowHtml(d.window, t, lang, opts, d.hidden_note)}
      <details><summary>${esc(t.howTitle)}</summary><ul>${t.how(d.rule).map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>`;
  }

  function initPulse(container, opts = {}) {
    if (!document.getElementById('pulse-css')) {
      const st = document.createElement('style');
      st.id = 'pulse-css';
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    let lang = getLang();
    let last = null;  // {data} or {error}
    const loc = opts.loc;
    let query = {district: opts.district || '', service: opts.service && opts.service !== 'other' ? opts.service : ''};

    function resHtml() {
      if (last == null) return '';
      return last.error ? `<p class="card" role="alert">${esc(T[lang][last.error])}</p>` : resultHtml(last.data, lang, opts);
    }
    // Only the results region changes after a search, so focus stays on the Show button.
    function drawRes() {
      const res = container.querySelector('#pulse-res');
      res.removeAttribute('aria-busy');
      res.innerHTML = resHtml();
      container.querySelector('#pulse-d').value = query.district;
    }
    function draw() {
      const t = T[lang];
      container.innerHTML = `<h1 tabindex="-1">${esc(t.title)}</h1>
        <div class="row" role="group" aria-label="${esc(t.lang)}">
          <button type="button" data-pl="en" aria-pressed="${lang === 'en'}">English</button>
          <button type="button" data-pl="hi" aria-pressed="${lang === 'hi'}"><span lang="hi">\u0939\u093f\u0928\u094d\u0926\u0940</span></button></div>
        <div lang="${lang}"><p>${esc(t.intro)}</p>${t.draft ? `<p class="small" lang="en">${esc(t.draft)}</p>` : ''}
        <form class="pulse-form" novalidate>
          <label for="pulse-d">${esc(t.district)}</label>
          <input id="pulse-d" name="district" autocomplete="off" maxlength="60" value="${esc(query.district)}">
          <label for="pulse-s">${esc(t.service)}</label>
          <select id="pulse-s" name="service"><option value="">${esc(t.all)}</option>
            ${(opts.services || []).map(s => `<option value="${esc(s.key)}"${s.key === query.service ? ' selected' : ''}>${esc(s[lang] || s.en)}</option>`).join('')}</select>
          <button type="submit" class="btn btn-primary">${esc(t.show)}</button></form>
        <div id="pulse-res" aria-live="polite">${resHtml()}</div></div>`;
      container.querySelectorAll('[data-pl]').forEach(b => b.addEventListener('click', () => {
        lang = b.dataset.pl;
        setLang(lang);
        draw();
        container.querySelector(`[data-pl="${lang}"]`).focus();
      }));
      container.querySelector('form').addEventListener('submit', e => {
        e.preventDefault();
        query = {district: container.querySelector('#pulse-d').value.trim(), service: container.querySelector('#pulse-s').value};
        if (!query.district) { last = {error: 'needDistrict'}; drawRes(); return; }
        load({district: query.district});
      });
    }

    async function load(where) {
      const res = container.querySelector('#pulse-res');
      res.setAttribute('aria-busy', 'true');
      res.innerHTML = `<p>${esc(T[lang].loading)}</p>`;
      const q = new URLSearchParams(where);
      if (query.service) q.set('service', query.service);
      try {
        const r = await fetch('/api/pulse?' + q, {signal: AbortSignal.timeout(15000)});
        if (r.status === 422) last = {error: 'badDistrict'};
        else if (!r.ok) last = {error: 'unavailable'};
        else {
          last = {data: await r.json()};
          query.district = last.data.district;
        }
      } catch {
        last = {error: navigator.onLine ? 'unavailable' : 'offline'};
      }
      drawRes();
    }

    draw();
    container.querySelector('h1').focus();
    if (query.district) load({district: query.district});
    // Rounded to 0.01 degree before it leaves the phone, as call outcomes are; the server keeps only the district.
    else if (loc && loc.lat != null) load({lat: loc.lat.toFixed(2), lon: loc.lon.toFixed(2)});
  }

  root.RSPulse = {initPulse};
})(typeof window !== 'undefined' ? window : globalThis);
