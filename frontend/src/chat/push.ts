// 답변 완료 웹 푸시: 화면을 떠난 사이 답변이 끝나면 이 기기로 알림을 받는다.
// 서비스 워커(sw.js)가 있어야 하므로 배포 빌드에서만 동작한다 (npm run dev에는 서비스 워커가 없다).

export type PushState = "unsupported" | "off" | "on" | "blocked";

/** 이 브라우저가 웹 푸시를 지원하는가. iPhone은 홈 화면에 설치한 앱에서만 PushManager가 있다 */
export function pushSupported(): boolean {
  return import.meta.env.PROD && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushSupported()) return null;
  try { return await navigator.serviceWorker.ready; } catch { return null; }
}

/** 서버가 알림을 지원하면 공개키, 아니면 null */
export async function fetchPushKey(): Promise<string | null> {
  try {
    const r = await fetch("/api/push");
    if (!r.ok) return null;
    const d = await r.json();
    return d.available && typeof d.public_key === "string" ? d.public_key : null;
  } catch { return null; }
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  const reg = await registration();
  const sub = await reg?.pushManager.getSubscription().catch(() => null);
  return sub && Notification.permission === "granted" ? "on" : "off";
}

/** 이 기기의 구독 주소 (질문할 때 함께 보내 이 기기로만 알림을 받는다) */
export async function currentEndpoint(): Promise<string | null> {
  if (!pushSupported() || Notification.permission !== "granted") return null;
  const reg = await registration();
  const sub = await reg?.pushManager.getSubscription().catch(() => null);
  return sub?.endpoint ?? null;
}

function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const b64 = (b64url + "=".repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** 알림 켜기. 반드시 사용자의 클릭 안에서 불러야 한다 (권한 요청) */
export async function enablePush(publicKey: string): Promise<PushState> {
  const permission = await Notification.requestPermission();
  if (permission === "denied") return "blocked";
  if (permission !== "granted") return "off";
  const reg = await registration();
  if (!reg) return "unsupported";
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
  }
  const json = sub.toJSON();
  const r = await fetch("/api/push", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
  });
  if (!r.ok) {
    await sub.unsubscribe().catch(() => false);
    throw new Error("알림을 켜지 못했어요. 잠시 후 다시 시도해 주세요.");
  }
  return "on";
}

/** 이미 켜져 있으면 서버에 구독을 다시 알린다 (서버가 만료로 지웠거나 다른 계정으로 옮겨 간 경우 대비) */
export async function syncPush(): Promise<void> {
  const reg = await registration();
  const sub = await reg?.pushManager.getSubscription().catch(() => null);
  if (!sub || Notification.permission !== "granted") return;
  const json = sub.toJSON();
  await fetch("/api/push", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
  }).catch(() => undefined);
}

export async function disablePush(): Promise<PushState> {
  const reg = await registration();
  const sub = await reg?.pushManager.getSubscription().catch(() => null);
  if (sub) {
    await fetch("/api/push", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    }).catch(() => undefined);
    await sub.unsubscribe().catch(() => false);
  }
  return "off";
}

/** 답변 중 화면을 떠났는지/돌아왔는지 서버에 알린다. 페이지가 멈춰도 전송되도록 keepalive */
export function reportVisibility(runId: string, hidden: boolean): void {
  void fetch("/api/chat/visibility", {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, hidden }),
  }).catch(() => undefined);
}
