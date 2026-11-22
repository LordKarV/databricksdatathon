// Network first for navigations and the shell; cached shell on network error or status >= 500
// (a stopped Databricks App answers with a proxy error page, not a network error). Redirects pass
// through so an expired session can sign in again. API calls are never cached here, except the
// offline state packs, which are stored on request (message 'cache-pack') in IndexedDB (spec, #32).
const CACHE = 'rs-shell-v10';
const OLD_PACKS = 'rs-packs-v1';  // Cache Storage before #32; moved to IndexedDB on activate

// ---------- pack store: IndexedDB 'rs-packs', object store 'packs', {slug, body, sha256, built, saved_at} ----------
function idb() {
  return new Promise((ok, fail) => {
    const r = indexedDB.open('rs-packs', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('packs', {keyPath: 'slug'});
    r.onsuccess = () => ok(r.result);
    r.onerror = () => fail(r.error);
  });
}
async function tx(mode, fn) {
  const db = await idb();
  try {
    return await new Promise((ok, fail) => {
      const t = db.transaction('packs', mode);
      const req = fn(t.objectStore('packs'));
      t.oncomplete = () => ok(req && req.result);
      t.onerror = t.onabort = () => fail(t.error);
    });
  } finally {
    db.close();
  }
}
const getPack = slug => tx('readonly', s => s.get(slug));
const putPack = rec => tx('readwrite', s => s.put(rec));

async function migrateOldPacks() {
  if (!(await caches.has(OLD_PACKS))) return;
  const cache = await caches.open(OLD_PACKS);
  for (const req of await cache.keys()) {
    const res = await cache.match(req);
    const slug = new URL(req.url).pathname.split('/').pop();
    if (!(await getPack(slug))) {
      await putPack({slug, body: await res.arrayBuffer(), sha256: res.headers.get('X-Pack-Sha256'),
        built: res.headers.get('X-Pack-Built') || '', saved_at: Date.now()});
    }
  }
  await caches.delete(OLD_PACKS);
}
function packResponse(rec) {
  return new Response(rec.body, {headers: {'Content-Type': 'application/json', 'X-Pack-Sha256': rec.sha256 || '',
    'X-Pack-Built': rec.built || ''}});
}
const SHELL = ['/', '/app.js', '/app.css', '/pack.js', '/offline.js', '/slip.js', '/how.js', '/stories.js', '/input.js',
  '/lexicon.json', '/manifest.webmanifest'];

self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));

self.addEventListener('activate', e => e.waitUntil(
  migrateOldPacks().catch(() => {})
    .then(() => caches.keys())
    .then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== OLD_PACKS).map(k => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/pack/') && url.pathname !== '/api/pack/version') {
    // Offline: answer from the stored pack. Online: the network, untouched (no write-through).
    const slug = url.pathname.split('/').pop();
    e.respondWith(fetch(e.request).catch(() => getPack(slug).catch(() => null)
      .then(rec => rec ? packResponse(rec)
        : new Response('{"error":"pack not saved"}', {status: 504, headers: {'Content-Type': 'application/json'}}))));
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
  const old = await getPack(slug);
  if (old && old.sha256 === meta.sha256) return {status: 'unchanged', sha256: meta.sha256};
  const res = await fetch('/api/pack/' + slug, {cache: 'no-store'});
  if (!res.ok) return {status: 'error', error: 'HTTP ' + res.status};
  // The body arrives decoded; stored with the sha so the next check can skip the download. Format unchanged.
  const body = await res.arrayBuffer();
  await putPack({slug, body, sha256: meta.sha256, built: meta.built || '', saved_at: Date.now()});
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
