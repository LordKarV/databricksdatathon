// Network first for navigations and the shell; cached shell on network error or status >= 500
// (a stopped Databricks App answers with a proxy error page, not a network error). Redirects pass
// through so an expired session can sign in again. API calls are never cached here, except the
// offline state packs, which are stored on request (message 'cache-pack') in their own cache.
const CACHE = 'rs-shell-v3';
const PACKS = 'rs-packs-v1';
const SHELL = ['/', '/app.js', '/app.css', '/pack.js', '/offline.js', '/manifest.webmanifest'];

self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));

self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== PACKS).map(k => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/pack/') && url.pathname !== '/api/pack/version') {
    // Offline: answer from the stored pack. Online: the network, untouched (no write-through).
    e.respondWith(fetch(e.request).catch(() => caches.open(PACKS).then(c => c.match(url.pathname))
      .then(r => r || new Response('{"error":"pack not saved"}', {status: 504, headers: {'Content-Type': 'application/json'}}))));
    return;
  }
  if (url.pathname.startsWith('/api/')) return;
  const key = e.request.mode === 'navigate' ? '/' : url.pathname;
  if (!SHELL.includes(key)) return;
  e.respondWith(fetch(e.request).then(res => {
    if (res.status >= 500) return caches.match(key).then(c => c || res);
    if (res.ok && res.type === 'basic') {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(key, copy));
    }
    return res;
  }).catch(() => caches.match(key)));
});

// Loader stub: the page posts {type: 'cache-pack', slug}; the reply goes back on the message port, or
// to the posting client, as {type: 'pack-status', slug, status, sha256?, error?}.
async function cachePack(slug) {
  const v = await fetch('/api/pack/version', {cache: 'no-store'}).then(r => r.ok ? r.json() : null);
  const meta = v && v.packs && v.packs[slug];
  if (!meta) return {status: 'unknown-slug'};
  const cache = await caches.open(PACKS);
  const key = '/api/pack/' + slug;
  const old = await cache.match(key);
  if (old && old.headers.get('X-Pack-Sha256') === meta.sha256) return {status: 'unchanged', sha256: meta.sha256};
  const res = await fetch(key, {cache: 'no-store'});
  if (!res.ok) return {status: 'error', error: 'HTTP ' + res.status};
  // The body arrives decoded; store it with the sha so the next check can skip the download.
  const body = await res.arrayBuffer();
  await cache.put(key, new Response(body, {headers: {'Content-Type': 'application/json',
    'X-Pack-Sha256': meta.sha256, 'X-Pack-Built': meta.built || ''}}));
  return {status: 'saved', sha256: meta.sha256, bytes: body.byteLength};
}

self.addEventListener('message', e => {
  const m = e.data || {};
  if (m.type !== 'cache-pack' || typeof m.slug !== 'string') return;
  const reply = r => {
    const msg = Object.assign({type: 'pack-status', slug: m.slug}, r);
    if (e.ports && e.ports[0]) e.ports[0].postMessage(msg);
    else if (e.source) e.source.postMessage(msg);
  };
  e.waitUntil(cachePack(m.slug).then(reply, err => reply({status: 'error', error: String(err)})));
});
