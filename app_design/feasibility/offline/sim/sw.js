// Offline shell for the referral app. Navigations: network first, cached shell when the network
// fails (offline). Pack and picker JSON: cache first (the page also copies them into IndexedDB).
// ponytail: one cache name; bump CACHE when the shell changes.
const CACHE = 'shell-v1';
const SHELL = ['/', '/picker.json', '/pack_norm.json'];
self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.mode === 'navigate') {
    // A stopped app (auto-stop after 24 h) answers with a proxy error page, not a network error:
    // fall back to the cached shell on 5xx too. Redirects pass through so an expired session re-logs in.
    e.respondWith(fetch(r).then(res => res.status >= 500 ? caches.match('/') : res).catch(() => caches.match('/')));
  } else if (SHELL.includes(new URL(r.url).pathname)) {
    e.respondWith(caches.match(r).then(hit => hit || fetch(r)));
  }
});
