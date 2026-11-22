// Voice input: speech to text. A classic script; its only global is initVoice.
// Default: record with MediaRecorder (up to 15 s) and send the clip once to POST /api/transcribe, where
// faster-whisper runs on the app server, so the audio stays inside Databricks and is not stored. Optional, off by
// default: the phone's speech service (Web Speech API), which sends the audio to Google. Offline, with no
// microphone permission or no recording support: a hint to use the keyboard's mic instead.
// The language is the user's choice (Hindi or English, default from the phone's language), never detected.
//
// Hook: initVoice(container, onTranscript) renders into container and calls onTranscript(text, lang) once per
// recording that produced words. Wiring for the describe screen (input.js, bindDescribe):
//   initVoice($('#voice'), text => { $('#desc').value = text; $('#desc-go').click(); });
(() => {
  const CAP_S = 15;
  const KEY = 'rs.voice';  // localStorage: {lang, phone}; a per-phone convenience only
  const HINT = "Use your keyboard's mic to speak.";
  const SPEAK = 'Speak';
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  // Chrome and Android: webm/opus, Firefox: ogg/opus, Safari: mp4. The server accepts exactly these.
  const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm'];

  function prefs() {
    let p = {};
    try { p = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { p = {}; }
    const phoneLang = (navigator.language || '').toLowerCase().startsWith('hi') ? 'hi' : 'en';
    return {lang: p.lang === 'hi' || p.lang === 'en' ? p.lang : phoneLang, phone: !!(p.phone && SR)};
  }
  function save(p) {
    try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private window: the choice is not remembered */ }
  }

  function html(p, id) {
    const radio = (v, label) => `<label class="check"><input type="radio" name="${id}" value="${v}"
      ${p.lang === v ? 'checked' : ''}> ${label}</label>`;
    return `<fieldset style="border:0;padding:0;margin:8px 0"><legend class="small">Speak in</legend>
      <div class="row">${radio('hi', '<span lang="hi">हिन्दी</span>&nbsp;Hindi')}${radio('en', 'English')}</div>
      ${canRecord || SR ? `<button type="button" class="btn btn-primary btn-block" data-mic aria-pressed="false"
        >${SPEAK}</button>` : ''}
      ${SR ? `<label class="check small"><input type="checkbox" data-phone ${p.phone ? 'checked' : ''}>
        Use the phone's speech service (faster, sends audio to Google)</label>` : ''}
      <p class="small" data-status aria-live="polite"></p></fieldset>`;
  }

  function toDataUrl(blob) {
    return new Promise((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(r.result);
      r.onerror = () => bad(r.error);
      r.readAsDataURL(blob);
    });
  }
  async function serverText(blob, lang) {
    const audio = await toDataUrl(blob);
    let res;
    try {
      res = await fetch('/api/transcribe', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({audio, lang}), signal: AbortSignal.timeout(45000)});
    } catch { throw new Error(`Could not reach the server. ${HINT}`); }
    let j = {};
    try { j = await res.json(); } catch { j = {}; }
    if (!res.ok) throw new Error(j.error || 'Could not write down what you said. Try again, or type.');
    return String(j.text || '').trim();
  }

  window.initVoice = function initVoice(container, onTranscript) {
    if (!container) return;
    let p = prefs();
    container.innerHTML = html(p, `voice-lang-${Math.random().toString(36).slice(2, 8)}`);
    const btn = container.querySelector('[data-mic]');
    const status = container.querySelector('[data-status]');
    const say = m => { status.textContent = m; };
    container.querySelectorAll('input[type=radio]').forEach(r => r.addEventListener('change', () => {
      p = {...p, lang: r.value}; save(p);
    }));
    const phone = container.querySelector('[data-phone]');
    if (phone) phone.addEventListener('change', () => { p = {...p, phone: phone.checked}; save(p); });
    if (!btn) { say(HINT); return; }

    let stop = null, timer = null, gone = false;
    function recording(on, stopFn) {
      clearInterval(timer);
      stop = on ? stopFn : null;
      btn.setAttribute('aria-pressed', String(on));
      btn.style.cssText = on ? 'background:var(--danger);color:var(--danger-fg);border-color:var(--danger)' : '';
      if (!on) { btn.textContent = SPEAK; return; }
      let left = CAP_S;
      const tick = () => {
        btn.innerHTML = `Stop recording <span aria-hidden="true">(${left} s)</span>`;
        if (left-- <= 0) stopFn();
      };
      tick();
      timer = setInterval(tick, 1000);
      say('Recording. Speak now, then tap Stop recording.');
    }
    function done(spoken, lang) {
      if (gone || !container.isConnected) return;
      const text = spoken.slice(0, 500);  // the describe box and /api/parse take at most 500 characters
      if (!text) { say('Did not catch any words. Try again, or type.'); return; }
      say(`Heard: ${text}`);
      onTranscript(text, lang);
    }
    // Leaving the screen turns the microphone off and drops the clip.
    window.addEventListener('hashchange', () => { gone = true; if (stop) stop(); }, {once: true});

    async function viaServer(lang) {
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); } catch {
        say(`The microphone is not allowed. ${HINT}`); return;
      }
      const type = TYPES.find(t => MediaRecorder.isTypeSupported(t));
      const rec = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
      const chunks = [];
      rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        recording(false);
        if (gone) return;
        btn.disabled = true;
        say('Writing down what you said...');
        try { done(await serverText(new Blob(chunks, {type: rec.mimeType || type}), lang), lang); }
        catch (e) { say(e.message); }
        finally { btn.disabled = false; }
      };
      rec.start();
      recording(true, () => { if (rec.state !== 'inactive') rec.stop(); });
    }
    function viaPhone(lang) {
      const r = new SR();
      r.lang = lang === 'hi' ? 'hi-IN' : 'en-IN';
      r.interimResults = false;
      r.maxAlternatives = 1;
      let text = '', failed = false;
      r.onresult = e => { text = Array.from(e.results, x => x[0].transcript).join(' ').trim(); };
      r.onerror = e => {
        failed = true;
        say(/not-allowed/.test(e.error) ? `The microphone is not allowed. ${HINT}`
          : `The phone's speech service did not work. Turn it off to use ours, or ${HINT.toLowerCase()}`);
      };
      r.onend = () => { recording(false); if (!failed) done(text, lang); };
      r.start();
      recording(true, () => r.stop());
    }

    btn.addEventListener('click', () => {
      if (stop) { stop(); return; }
      if (!navigator.onLine) { say(`You are offline. ${HINT}`); return; }
      if (p.phone && SR) viaPhone(p.lang);
      else if (canRecord) viaServer(p.lang);
      else say(HINT);  // no recording support; the phone service is used only when switched on
    });
  };
})();
