// Network first for navigations and the shell; cached shell on network error or status >= 500
// (a stopped Databricks App answers with a proxy error page, not a network error). Redirects pass
// through so an expired session can sign in again. API calls are never cached here; offline
// answers come from the state packs (issue #9) via IndexedDB.
const CACHE = 'rs-shell-v1';
const SHELL = ['/', '/app.js', '/app.css', '/manifest.webmanifest'];

self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));

self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
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
