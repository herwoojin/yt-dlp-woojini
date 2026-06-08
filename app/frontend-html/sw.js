// 최소 service worker: PWA install 자격 충족 + 정적 셸 캐시.
// API 응답은 캐시하지 않음 (job 상태가 실시간이라야 함).
const CACHE = 'ytdlp-shell-v19';
const SHELL = ['/', '/index.html', '/blog-studio.html', '/reference-images.html', '/auth-client.js', '/manifest.webmanifest', '/icon.svg', '/icon-192.png', '/icon-512.png', '/screenshot-narrow.png', '/screenshot-wide.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // http(s)가 아닌 요청(chrome-extension:// 등)은 캐시 불가 → 건너뜀
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  // API/터널 호출은 네트워크 우선 (캐시 안 함)
  if (url.pathname.startsWith('/api/') || url.hostname.endsWith('.fly.dev') || url.hostname.endsWith('.trycloudflare.com')) {
    return;
  }
  // tunnel.json은 항상 fresh
  if (url.pathname === '/tunnel.json') return;

  if (e.request.method !== 'GET') return;

  // HTML(셸)은 network-first: 새 배포가 즉시 반영되도록 (stale 셸로 인한 멈춤 방지).
  // 오프라인일 때만 캐시 fallback.
  const isHTML = e.request.mode === 'navigate' ||
    url.pathname === '/' || url.pathname.endsWith('.html');
  if (isHTML) {
    e.respondWith(
      fetch(e.request).then((resp) => {
        if (resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // 그 외 정적 자산은 cache-first
  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached ||
      fetch(e.request).then((resp) => {
        if (resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      }).catch(() => cached)
    )
  );
});
