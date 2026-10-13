/* MCJ Sahan Fleet PWA service worker.
   Caches the shell only. Never caches /m or /auth so fleet data always
   comes fresh from the server and signing out really signs out. */
const CACHE = 'mcj-sahan-shell-v1';
const SHELL = [
  '/static/css/mobile.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/m') || url.pathname.startsWith('/auth') ||
      url.pathname.startsWith('/app') || url.pathname.startsWith('/static/icons')) {
    return;
  }

  event.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match('/static/icons/icon-192.png')))
  );
});