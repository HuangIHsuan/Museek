// Museek Service Worker — 只為了「離線也打得開外殼」。
//
// 兩條紅線：
//   1. /api/ 一律不碰。推薦是 SSE 長連線，被快取或被 clone 都會斷。
//   2. 只快取自己網域的 GET。YouTube 內嵌、外部 API 都放行。
//
// 區網 http:// 不會註冊這支（見 index.html），所以它只在 HTTPS 部署時生效。

const VERSION = "museek-v1";
const SHELL = [
  "/",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // 開頁：優先走網路，斷線才拿快取的外殼頂著
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(VERSION).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/").then((hit) => hit || Response.error()))
    );
    return;
  }

  // 靜態資源：先給快取，同時在背景更新
  event.respondWith(
    caches.match(request).then((hit) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});
