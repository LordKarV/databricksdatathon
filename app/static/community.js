// Field reports from the page (community/field.py on the server): the reason step after a phone "no", the
// "How did this referral go?" visit report, and the recent referrals it is about. Loaded lazily on #/why, #/slip
// and #/report. Fixed lists only, never free text; nothing about the patient. Recent referrals live on this phone
// (localStorage 'rs.recent': facility, service, slip time, the point rounded to 0.01 degree like every report).
'use strict';
(function (root) {
  // Hindi strings are drafts until native-speaker review (#10). Devanagari is \u-escaped to keep the file ASCII.
  const T = {
    reasonQ: ['Why did they say no? (optional)', '\u0909\u0928\u094d\u0939\u094b\u0902\u0928\u0947 \u092e\u0928\u093e \u0915\u094d\u092f\u094b\u0902 \u0915\u093f\u092f\u093e? (\u091c\u093c\u0930\u0942\u0930\u0940 \u0928\u0939\u0940\u0902)'],
    notOffered: ['Not offered there', '\u0935\u0939\u093e\u0901 \u092f\u0939 \u0938\u0947\u0935\u093e \u0928\u0939\u0940\u0902'],
    notToday: ['Not available today', '\u0906\u091c \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902'],
    skip: ['Skip', '\u091b\u094b\u0921\u093c\u0947\u0902'],
    home: ['Back to start', '\u0936\u0941\u0930\u0941\u0906\u0924 \u092a\u0930 \u091c\u093e\u090f\u0901'],
    noted: ['Reason noted. It is sent with the answer, with no patient details.',
      '\u0915\u093e\u0930\u0923 \u0926\u0930\u094d\u091c \u0939\u0941\u0906\u0964 \u092f\u0939 \u091c\u0935\u093e\u092c \u0915\u0947 \u0938\u093e\u0925 \u092d\u0947\u091c\u093e \u091c\u093e\u0924\u093e \u0939\u0948; \u092e\u0930\u0940\u091c\u093c \u0915\u0940 \u0915\u094b\u0908 \u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0928\u0939\u0940\u0902 \u092d\u0947\u091c\u0940 \u091c\u093e\u0924\u0940\u0964'],
    skipped: ['Sent without a reason.', '\u092c\u093f\u0928\u093e \u0915\u093e\u0930\u0923 \u092d\u0947\u091c\u093e \u0917\u092f\u093e\u0964'],
    title: ['How did this referral go?', '\u092f\u0939 \u0930\u0947\u092b\u093c\u0930\u0932 \u0915\u0948\u0938\u093e \u0930\u0939\u093e?'],
    none: ['No recent referrals on this phone. A referral is remembered here when you make its slip.',
      '\u0907\u0938 \u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0932 \u0915\u093e \u0915\u094b\u0908 \u0930\u0947\u092b\u093c\u0930\u0932 \u0928\u0939\u0940\u0902 \u0939\u0948\u0964 \u0930\u0947\u092b\u093c\u0930\u0932 \u092a\u0930\u094d\u091a\u0940 \u092c\u0928\u093e\u0928\u0947 \u092a\u0930 \u0930\u0947\u092b\u093c\u0930\u0932 \u092f\u0939\u093e\u0901 \u092f\u093e\u0926 \u0930\u0939\u0924\u093e \u0939\u0948\u0964'],
    which: ['Which referral?', '\u0915\u094c\u0928 \u0938\u093e \u0930\u0947\u092b\u093c\u0930\u0932?'],
    happened: ['What happened at the facility?', '\u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u092e\u0947\u0902 \u0915\u094d\u092f\u093e \u0939\u0941\u0906?'],
    accepted: ['They took the patient', '\u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u0947 \u0932\u093f\u092f\u093e'],
    turned_away: ['Turned away', '\u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u094c\u091f\u093e \u0926\u093f\u092f\u093e'],
    whyAway: ['Why were they turned away? (optional)', '\u0915\u094d\u092f\u094b\u0902 \u0932\u094c\u091f\u093e\u092f\u093e? (\u091c\u093c\u0930\u0942\u0930\u0940 \u0928\u0939\u0940\u0902)'],
    wait: ['How long before the patient was seen? (optional)', '\u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0926\u0947\u0916\u0928\u0947 \u092e\u0947\u0902 \u0915\u093f\u0924\u0928\u093e \u0938\u092e\u092f \u0932\u0917\u093e? (\u091c\u093c\u0930\u0942\u0930\u0940 \u0928\u0939\u0940\u0902)'],
    lt_30m: ['Under 30 min', '30 \u092e\u093f\u0928\u091f \u0938\u0947 \u0915\u092e'],
    '30_120m': ['30 min to 2 hours', '30 \u092e\u093f\u0928\u091f \u0938\u0947 2 \u0918\u0902\u091f\u0947'],
    gt_2h: ['More than 2 hours', '2 \u0918\u0902\u091f\u0947 \u0938\u0947 \u091c\u093c\u094d\u092f\u093e\u0926\u093e'],
    unknown: ['Not known', '\u092a\u0924\u093e \u0928\u0939\u0940\u0902'],
    send: ['Send report', '\u0930\u093f\u092a\u094b\u0930\u094d\u091f \u092d\u0947\u091c\u0947\u0902'],
    pickFirst: ['Choose what happened first.', '\u092a\u0939\u0932\u0947 \u091a\u0941\u0928\u0947\u0902 \u0915\u093f \u0915\u094d\u092f\u093e \u0939\u0941\u0906\u0964'],
    queued: ['Report saved. It is sent now, or when the phone is back online.',
      '\u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u0947\u0935 \u0939\u094b \u0917\u0908\u0964 \u0905\u092d\u0940 \u092d\u0947\u091c\u0940 \u091c\u093e\u090f\u0917\u0940, \u092f\u093e \u0907\u0902\u091f\u0930\u0928\u0947\u091f \u0906\u0928\u0947 \u092a\u0930\u0964'],
    reported: ['Reported', '\u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0939\u094b \u0917\u0908'],
    slipMade: ['slip made', '\u092a\u0930\u094d\u091a\u0940 \u092c\u0928\u0940'],
    privacy: ['Sent: the facility, the service, the district, the answer and the time. No patient details, no names, no typed text.',
      '\u092d\u0947\u091c\u093e \u091c\u093e\u0924\u093e \u0939\u0948: \u0905\u0938\u094d\u092a\u0924\u093e\u0932, \u0938\u0947\u0935\u093e, \u091c\u093c\u093f\u0932\u093e, \u091c\u0935\u093e\u092c \u0914\u0930 \u0938\u092e\u092f\u0964 \u092e\u0930\u0940\u091c\u093c \u0915\u0940 \u0915\u094b\u0908 \u091c\u093e\u0928\u0915\u093e\u0930\u0940, \u0928\u093e\u092e \u092f\u093e \u0932\u093f\u0916\u093e \u0939\u0941\u0906 \u091f\u0947\u0915\u094d\u0938\u094d\u091f \u0928\u0939\u0940\u0902\u0964'],
    weight: ['A report from one health worker does not change a score. Reports from two or more move it a little, and never make a hospital "Unlikely" on their own.',
      '\u090f\u0915 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u0947 \u0938\u094d\u0915\u094b\u0930 \u0928\u0939\u0940\u0902 \u092c\u0926\u0932\u0924\u093e\u0964 \u0926\u094b \u092f\u093e \u091c\u093c\u094d\u092f\u093e\u0926\u093e \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u0947 \u0925\u094b\u0921\u093c\u093e \u092c\u0926\u0932\u0924\u093e \u0939\u0948\u0964 \u0938\u093f\u0930\u094d\u092b\u093c \u0907\u0928 \u0930\u093f\u092a\u094b\u0930\u094d\u091f\u094b\u0902 \u0938\u0947 \u0915\u094b\u0908 \u0905\u0938\u094d\u092a\u0924\u093e\u0932 "Unlikely" (\u0938\u0902\u092d\u093e\u0935\u0928\u093e \u0915\u092e) \u0928\u0939\u0940\u0902 \u092c\u0928\u0924\u093e\u0964'],
    cardShared: ['Family card shared.', '\u092f\u093e\u0924\u094d\u0930\u093e \u0915\u093e\u0930\u094d\u0921 \u092d\u0947\u091c\u093e \u0917\u092f\u093e\u0964'],
    cardSaved: ['Family card saved to Downloads. Send it on WhatsApp as a document.',
      '\u092f\u093e\u0924\u094d\u0930\u093e \u0915\u093e\u0930\u094d\u0921 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u092e\u0947\u0902 \u0938\u0947\u0935 \u0939\u094b \u0917\u092f\u093e\u0964 \u0907\u0938\u0947 WhatsApp \u092a\u0930 \u0921\u0949\u0915\u094d\u092f\u0942\u092e\u0947\u0902\u091f \u0915\u0940 \u0924\u0930\u0939 \u092d\u0947\u091c\u0947\u0902\u0964'],
    cardCancelled: ['Not sent.', '\u0928\u0939\u0940\u0902 \u092d\u0947\u091c\u093e\u0964'],
    cardFailed: ['Could not make the family card. Use the WhatsApp or SMS slip.',
      '\u092f\u093e\u0924\u094d\u0930\u093e \u0915\u093e\u0930\u094d\u0921 \u0928\u0939\u0940\u0902 \u092c\u0928 \u0938\u0915\u093e\u0964 WhatsApp \u092f\u093e SMS \u0938\u0947 \u092a\u0930\u094d\u091a\u0940 \u092d\u0947\u091c\u0947\u0902\u0964'],
    service_not_here: ['Service not here', '\u092f\u0939 \u0938\u0947\u0935\u093e \u092f\u0939\u093e\u0901 \u0928\u0939\u0940\u0902 \u0939\u0948'],
    equipment_absent: ['Equipment not here', '\u0909\u092a\u0915\u0930\u0923 \u092f\u0939\u093e\u0901 \u0928\u0939\u0940\u0902 \u0939\u0948'],
    referred_elsewhere_for_this_service: ['They send this elsewhere', '\u0935\u0947 \u092f\u0939 \u0938\u0947\u0935\u093e \u0915\u0939\u0940\u0902 \u0914\u0930 \u092d\u0947\u091c\u0924\u0947 \u0939\u0948\u0902'],
    no_bed: ['No bed', '\u092c\u0947\u0921 \u0916\u093e\u0932\u0940 \u0928\u0939\u0940\u0902'],
    doctor_absent: ['Doctor not there', '\u0921\u0949\u0915\u094d\u091f\u0930 \u092e\u094c\u091c\u0942\u0926 \u0928\u0939\u0940\u0902'],
    machine_down: ['Machine not working', '\u092e\u0936\u0940\u0928 \u0916\u0930\u093e\u092c'],
    asked_to_pay: ['Asked to pay', '\u092a\u0948\u0938\u0947 \u092e\u093e\u0901\u0917\u0947'],
    closed_now: ['Closed now', '\u0905\u092d\u0940 \u092c\u0902\u0926'],
  };
  // Same lists as outcomes.py (REASONS_NOT_OFFERED, REASONS_TEMPORARY, WAIT_BUCKETS); the server rejects others.
  const NOT_OFFERED = ['service_not_here', 'equipment_absent', 'referred_elsewhere_for_this_service'];
  const TEMPORARY = ['no_bed', 'doctor_absent', 'machine_down', 'asked_to_pay', 'closed_now'];
  const WAITS = ['lt_30m', '30_120m', 'gt_2h'];
  const KEEP_DAYS = 7;  // outcomes.MAX_AGE: a report about an older referral is not useful
  const KEEP_N = 5;

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  /** One language on screen: the app language (state.lang in app.js). */
  const L = () => (typeof state !== 'undefined' && state.lang === 'hi' ? 1 : 0);
  const say = k => T[k][L()];
  const both = k => esc(say(k));

  function load(k) { try { return JSON.parse(localStorage.getItem('rs.' + k)); } catch { return null; } }
  function save(k, v) { try { localStorage.setItem('rs.' + k, JSON.stringify(v)); } catch { /* private mode */ } }

  // ---------- reason step after "Said no" on the phone ----------
  let pending = null;  // send(reason | null) for a "no" that has not been sent yet
  function sendPending() { if (pending) { const s = pending; pending = null; s(null); } }
  function dropPending() { pending = null; }
  function reasonButtons(keys) { return keys.map(k => `<button type="button" data-reason="${k}">${both(k)}</button>`).join(''); }
  /** Shows the optional reason buttons in el; send(reason or null) is called once: on a tap, on Skip, or when the
   *  page changes (sendPending). Replaces an earlier unsent "no". opts.focus false leaves focus where it is. */
  function askReason(el, send, announce, opts = {}) {
    pending = send;
    el.innerHTML = `<fieldset class="card reason-step"><legend>${both('reasonQ')}</legend>
      <p class="small"><strong>${both('notOffered')}</strong></p><div class="row">${reasonButtons(NOT_OFFERED)}</div>
      <p class="small"><strong>${both('notToday')}</strong></p><div class="row">${reasonButtons(TEMPORARY)}</div>
      <div class="row"><button type="button" data-reason="">${both('skip')}</button></div></fieldset>`;
    el.querySelectorAll('[data-reason]').forEach(b => b.addEventListener('click', () => {
      if (pending !== send) return;
      pending = null;
      send(b.dataset.reason || null);
      const k = b.dataset.reason ? 'noted' : 'skipped';
      el.innerHTML = `<p class="small">${both(k)}</p>`;
      announce(say(k));
    }));
    if (opts.focus !== false) el.querySelector('[data-reason]').focus();  // the call loop keeps focus on Call next
  }

  // ---------- call loop on the answer screen (#140 3d) ----------
  // Page helpers (th, F, N, E, bandHtml, telOf, sosHtml, travelHtml, icon, announce, queueOutcome) are app.js
  // globals. state.call: {plan, rank, stage: 'dialing' | 'outcome' | 'next' | 'end' | 'yes'}, tied to its plan.
  // "Said no", "No answer" or "Wrong number" moves to the next option with a number; after the last, 108 (102) and
  // the nearest public hospital. Outcomes go through queueOutcome; a "no" gets the reason step, as on the Why page.
  const CALL_OUTCOMES = ['yes', 'no', 'none', 'wrong'];
  const nameF = (P, o) => `<span lang="en">${F(P + '.name', o.name)}</span>`;
  function nextWithPhone(p, o) { return p.options.slice(p.options.indexOf(o) + 1).find(x => telOf(x)) || null; }
  function callStep(p, o, said) {
    if (said === 'yes') return {plan: p, rank: o.rank, stage: 'yes'};
    const next = nextWithPhone(p, o);
    return next ? {plan: p, rank: next.rank, stage: 'next'} : {plan: p, rank: o.rank, stage: 'end'};
  }
  function callLoopHtml(p) {
    const c = state.call;
    if (!c || c.plan !== p || c.stage === 'dialing') return '';
    const i = p.options.findIndex(x => x.rank === c.rank), o = p.options[i], P = `options.${i}`;
    if (!o) return '';
    if (c.stage === 'outcome') {
      return `<div class="call-loop" role="group" aria-labelledby="call-how"><p id="call-how"><strong>${th('call.how', {name: nameF(P, o)})}</strong></p>
        <div class="outcomes">${CALL_OUTCOMES.map(k => `<button type="button" class="btn" data-call-out="${k}">${th('why.out.' + k)}</button>`).join('')}</div></div>`;
    }
    if (c.stage === 'yes') {
      return `<div class="call-loop"><p><strong>${th('call.yes', {name: nameF(P, o)})}</strong></p>
        <a class="btn btn-block" href="#/slip/${o.rank}">${th('why.slip')}</a></div>`;
    }
    if (c.stage === 'next') {
      return `<div class="call-loop call-next"><p><strong>${th('call.next', {name: nameF(P, o), min: N(P + '.travel.minutes', o.travel.minutes),
        band: bandHtml(o, P)})}</strong></p>
        <div class="pair"><a class="btn btn-go" id="call-next-btn" href="${telOf(o)}">${icon('phone')} ${th('ans.call')}<span class="visually-hidden"> ${F(P + '.name', o.name)}</span></a>
          <a class="btn" href="#/why/${o.rank}">${th('ans.why')}<span class="visually-hidden"> ${F(P + '.name', o.name)}</span></a></div>
        <div id="call-reason"></div></div>`;
    }
    const po = p.public_option;
    return `<div class="call-loop call-end"><p><strong>${th('call.none_left')}</strong></p>
      <div class="sos-inline">${sosHtml(has102(p.query.service))}</div>
      ${po ? `<p>${th('window.public', {name: `<strong lang="en">${F('public_option.name', po.name)}</strong>`, label: E('public_option.label', po.label)})}
        ${travelHtml(po.travel, 'public_option.travel')}.</p>` : ''}
      <div id="call-reason"></div></div>`;
  }
  function showCallLoop() { const el = document.getElementById('call-loop'); if (el) el.innerHTML = callLoopHtml(state.plan); }
  /** The phone is back from the dialler: show the four outcomes for the option just called. */
  function callBack() {
    const c = state.call;
    if (!c || c.stage !== 'dialing' || c.plan !== state.plan) return;
    c.stage = 'outcome';
    showCallLoop();
    const o = state.plan.options.find(x => x.rank === c.rank);
    announce(ts('call.how', {name: o.name}));
    document.querySelector('#call-loop [data-call-out]')?.focus();
  }
  function callOutcome(said) {
    const c = state.call, p = state.plan;
    const o = c && c.plan === p && p.options.find(x => x.rank === c.rank);
    if (!o) return;
    const at = Date.now();
    (state.outcomes ||= {})[o.rank] = {said, at};  // the slip and Compare show it
    dropPending();
    if (said !== 'no') queueOutcome(o, said, at);
    state.call = callStep(p, o, said);
    showCallLoop();
    if (said === 'no') askReason(document.getElementById('call-reason'), r => queueOutcome(o, said, at, r ? {reason: r} : {}), announce, {focus: false});
    const n = p.options.find(x => x.rank === state.call.rank);
    if (state.call.stage === 'next') {
      document.getElementById('call-next-btn').focus();
      announce(ts('call.next', {name: n.name, min: n.travel.minutes, band: ts('band.' + n.band)}));
    } else if (state.call.stage === 'end') {
      document.querySelector('#call-loop .sos-inline a')?.focus();
      announce(ts('call.none_left'));
    } else {
      announce(ts('call.yes', {name: n.name}));
    }
  }
  /** The Why page's outcome buttons: back on the answer screen, the loop continues from that answer. */
  function callAfter(p, o, said) { if (p && o) state.call = callStep(p, o, said); }

  // ---------- recent referrals and the visit report ----------
  function recent(now = Date.now()) {
    return (load('recent') || []).filter(r => r && now - r.at < KEEP_DAYS * 864e5);
  }
  /** Called when a slip is made: one entry per facility and service per day. */
  function remember(plan, o, loc, now = Date.now()) {
    if (!loc) return;
    const svc = plan.query.service, label = plan.query.service_label || {};
    const day = new Date(now).toDateString();
    const rest = recent(now).filter(r => !(r.facility_id === o.facility_id && r.service_id === svc
      && new Date(r.at).toDateString() === day));
    save('recent', [{id: root.crypto.randomUUID(), facility_id: o.facility_id, service_id: svc, name: o.name,
      service_en: label.en || svc, service_hi: label.hi || '', at: now,
      lat: Math.round(loc.lat * 100) / 100, lon: Math.round(loc.lon * 100) / 100}, ...rest].slice(0, KEEP_N));
  }
  function radios(name, keys, label) {
    return keys.map(k => `<label class="check"><input type="radio" name="${name}" value="${esc(k)}">
      ${label(k)}</label>`).join('');
  }
  function day(t) { return new Date(t).toLocaleDateString(L() ? 'hi-IN' : 'en-IN', {day: 'numeric', month: 'short'}); }
  function reportHtml(list) {
    if (!list.length) return `<h1 tabindex="-1">${both('title')}</h1><p class="card">${both('none')}</p>
      <a class="btn btn-block" href="#/">${both('home')}</a>`;
    const which = list.map(r => `<label class="check"><input type="radio" name="ref" value="${esc(r.id)}"
      ${r.reported ? 'disabled' : ''}><span><strong>${esc(r.name)}</strong>, ${esc(L() && r.service_hi ? r.service_hi : r.service_en)}.
      <span class="small">${both('slipMade')} ${esc(day(r.at))}${r.reported ? `. ${both('reported')}` : ''}</span></span></label>`).join('');
    return `<h1 tabindex="-1">${both('title')}</h1>
      <form id="visit-form" novalidate>
        <fieldset><legend>${both('which')}</legend>${which}</fieldset>
        <fieldset><legend>${both('happened')}</legend>${radios('outcome', ['accepted', 'turned_away'], both)}</fieldset>
        <fieldset id="away-why" disabled><legend>${both('whyAway')}</legend>
          ${radios('reason', [...NOT_OFFERED, ...TEMPORARY, ''], k => both(k || 'unknown'))}</fieldset>
        <fieldset><legend>${both('wait')}</legend>${radios('wait', [...WAITS, ''], k => both(k || 'unknown'))}</fieldset>
        <p id="visit-err" role="alert"></p>
        <button type="submit" class="btn btn-primary btn-block">${both('send')}</button>
      </form>
      <p class="small muted">${both('privacy')}</p><p class="small muted">${both('weight')}</p>`;
  }
  /** #/report: queue(item) is the page's outcome queue; announce(text) its live region. */
  function bindReport(el, queue, announce) {
    const list = recent();
    el.innerHTML = reportHtml(list);
    el.querySelector('h1').focus();
    const form = el.querySelector('#visit-form');
    if (!form) return;
    const first = form.querySelector('input[name=ref]:not([disabled])');
    if (first) first.checked = true;
    const val = n => (form.querySelector(`input[name=${n}]:checked`) || {}).value || '';
    form.querySelectorAll('input[name=outcome]').forEach(r => r.addEventListener('change', () => {
      form.querySelector('#away-why').disabled = val('outcome') !== 'turned_away';
    }));
    form.addEventListener('submit', e => {
      e.preventDefault();
      const ref = list.find(r => r.id === val('ref'));
      const outcome = val('outcome');
      if (!ref || !outcome) {
        form.querySelector('#visit-err').innerHTML = both('pickFirst');
        (form.querySelector('input[name=outcome]')).focus();
        return;
      }
      const item = {outcome_id: root.crypto.randomUUID(), facility_id: ref.facility_id, service_id: ref.service_id,
        outcome, said_at_ms: Date.now(), lat: ref.lat, lon: ref.lon, kind: 'visit'};
      if (outcome === 'turned_away' && val('reason')) item.reason = val('reason');
      if (val('wait')) item.wait_bucket = val('wait');
      queue(item);
      save('recent', recent().map(r => (r.id === ref.id ? {...r, reported: true} : r)));
      el.innerHTML = `<h1 tabindex="-1">${both('title')}</h1><p class="card">${both('queued')}</p>
        <a class="btn btn-block" href="#/">${both('home')}</a>`;
      el.querySelector('h1').focus();
      announce(say('queued'));
    });
  }

  root.RSCommunity = {askReason, sendPending, dropPending, remember, recent, bindReport, say, both,
    callLoopHtml, callBack, callOutcome, callAfter,
    lists: {NOT_OFFERED, TEMPORARY, WAITS}};
})(typeof window !== 'undefined' ? window : globalThis);
