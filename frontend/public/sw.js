// 단비 서비스 워커: 홈 화면 설치용 최소 구성.
// - 화면(index.html)은 늘 서버에서 받는다 → 배포하면 바로 새 화면이 뜬다. 연결이 끊겼을 때만 안내 화면.
// - /assets/* 는 파일 이름에 내용 해시가 붙어 있어 한 번 받으면 바뀌지 않으므로 캐시해서 다시 쓴다.
// - /api/* (채팅·로그인·대화 기록)와 그 밖의 요청은 건드리지 않는다. 개인 데이터는 캐시에 남지 않는다.
// 서비스 워커를 없애야 할 때는 이 파일을 self.registration.unregister()만 하는 내용으로 바꿔 배포하면 된다.
const ASSETS = "danbi-assets-v1";
const MAX_ASSETS = 200; // 글꼴 조각(Pretendard 부분 글꼴)이 많아 넉넉히. 배포가 쌓여도 옛 파일이 끝없이 늘지는 않게

const OFFLINE_HTML = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0f2d64"><title>단비 — 연결 필요</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f6fa; color: #1b2333;
         font-family: Pretendard, -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
  main { text-align: center; padding: 24px; }
  h1 { font-size: 20px; color: #0f2d64; margin: 0 0 8px; }
  p { margin: 0 0 20px; color: #5a6478; line-height: 1.6; }
  a { display: inline-block; padding: 10px 22px; border-radius: 999px; background: #0f2d64; color: #fff; text-decoration: none; font-weight: 700; }
  @media (prefers-color-scheme: dark) { body { background: #0b1222; color: #e6ebf5; } h1 { color: #a9c3f5; } p { color: #9aa6bd; } a { background: #2a5bb8; } }
</style></head>
<body><main><h1>인터넷 연결이 필요해요</h1><p>단비는 질문할 때마다 학교 자료를 찾아 답하기 때문에<br>연결된 뒤에 다시 열어 주세요.</p><a href="/">다시 시도</a></main></body></html>`;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("danbi-") && key !== ASSETS) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => new Response(OFFLINE_HTML, {
      status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    })));
    return;
  }
  if (url.pathname.startsWith("/assets/")) event.respondWith(cacheFirst(req));
});

async function cacheFirst(req) {
  const cache = await caches.open(ASSETS);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok && res.type === "basic") {
    await cache.put(req, res.clone());
    const keys = await cache.keys();
    for (const old of keys.slice(0, Math.max(0, keys.length - MAX_ASSETS))) await cache.delete(old);
  }
  return res;
}
