"""웹 푸시: 사용자가 화면을 떠나 있는 동안 답변이 끝나면 질문한 기기로 알림을 보낸다.

키는 환경 변수 하나로 받는다.
  DANBI_VAPID_PRIVATE_KEY   VAPID 비밀키 (P-256, base64url). 공개키는 여기서 계산한다.
                            새로 만들기: python -m danbi.personal.push
  DANBI_VAPID_SUBJECT       푸시 서비스가 문제 있을 때 연락할 곳 (mailto: 또는 https:).
                            없으면 DANBI_PRIVACY_CONTACT(mailto:), 그것도 없으면 DANBI_PUBLIC_URL을 쓴다.
비밀키가 없으면 기능이 꺼지고, 화면에도 알림 토글이 나타나지 않는다.

알림 내용은 브라우저 공개키로 암호화돼(RFC 8291) 푸시 서비스는 읽을 수 없다.
서버가 아무 주소로나 요청을 보내지 않도록 구독 주소는 알려진 브라우저 푸시 서비스로만 받는다.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

log = logging.getLogger(__name__)

# 브라우저 푸시 서비스: Chrome·Edge(새 버전)·삼성 인터넷 = FCM, Firefox = Mozilla, 옛 Edge = WNS, Safari = Apple
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com", "push.apple.com")
MAX_ENDPOINT = 1000
TTL_SECONDS = 60 * 60  # 기기가 꺼져 있으면 푸시 서비스가 이 시간 동안 보관했다가 전달

# (구독 정보, 암호화 전 본문) → HTTP 상태 코드. 테스트는 가짜를 넣는다
Sender = Callable[[dict, str], int]


class PushError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_private_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return _b64(key.private_numbers().private_value.to_bytes(32, "big"))


def public_key_of(private_key: str) -> str:
    """브라우저의 pushManager.subscribe(applicationServerKey)에 넣는 공개키 (비압축 점, base64url)."""
    value = int.from_bytes(_unb64(private_key), "big")
    key = ec.derive_private_key(value, ec.SECP256R1())
    return _b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint))


def is_push_endpoint(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and len(url) <= MAX_ENDPOINT
            and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS))


def subject_from_env() -> str | None:
    if s := (os.environ.get("DANBI_VAPID_SUBJECT") or "").strip():
        return s
    if c := (os.environ.get("DANBI_PRIVACY_CONTACT") or "").strip():
        return f"mailto:{c}"
    if u := (os.environ.get("DANBI_PUBLIC_URL") or "").strip().rstrip("/"):
        return u
    return None


class PushService:
    def __init__(self, store, private_key: str | None, subject: str | None, sender: Sender | None = None):
        self.store = store
        self.private_key = (private_key or "").strip() or None
        self.subject = subject
        self.public_key: str | None = None
        if self.private_key:
            try:
                self.public_key = public_key_of(self.private_key)
            except Exception:  # noqa: BLE001 - 잘못된 키면 기능만 끈다
                log.error("DANBI_VAPID_PRIVATE_KEY를 읽을 수 없어 웹 푸시를 끕니다")
                self.private_key = None
        self.enabled = bool(self.private_key and self.public_key and self.subject)
        self._sender = sender or self._webpush

    @classmethod
    def from_env(cls, store) -> PushService:
        return cls(store, os.environ.get("DANBI_VAPID_PRIVATE_KEY"), subject_from_env())

    def subscribe(self, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
        if not is_push_endpoint(endpoint):
            raise PushError("지원하지 않는 알림 주소예요.")
        try:
            if len(_unb64(p256dh)) != 65 or not 16 <= len(_unb64(auth)) <= 32:
                raise ValueError
        except ValueError:
            raise PushError("알림 구독 정보가 올바르지 않아요.") from None
        self.store.save_push(user_id, endpoint, p256dh, auth)

    def unsubscribe(self, user_id: int, endpoint: str) -> None:
        self.store.delete_push(endpoint, user_id)

    def owns(self, user_id: int, endpoint: str) -> bool:
        row = self.store.get_push(endpoint)
        return row is not None and row["user_id"] == user_id

    def send(self, user_id: int, endpoint: str, payload: dict) -> bool:
        """이 사용자의 구독으로 알림을 보낸다. 실패는 기록만 하고 False (답변을 막지 않는다)."""
        if not self.enabled:
            return False
        row = self.store.get_push(endpoint)
        if row is None or row["user_id"] != user_id:
            return False
        info = {"endpoint": endpoint, "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}}
        try:
            status = self._sender(info, json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            log.warning("웹 푸시 실패 (%s): %s", urlparse(endpoint).hostname, type(e).__name__)
            return False
        if status in (404, 410):  # 구독이 끝남 (사용자가 권한을 거두거나 브라우저 데이터 삭제)
            self.store.delete_push(endpoint)
            return False
        if not 200 <= status < 300:
            log.warning("웹 푸시 거부 (%s): HTTP %s", urlparse(endpoint).hostname, status)
            return False
        self.store.mark_push_ok(endpoint)
        return True

    def _webpush(self, info: dict, data: str) -> int:
        from pywebpush import WebPushException, webpush

        try:
            res = webpush(info, data, vapid_private_key=self.private_key, vapid_claims={"sub": self.subject},
                          ttl=TTL_SECONDS, timeout=10)
        except WebPushException as e:
            return e.response.status_code if e.response is not None else 0
        return res.status_code


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서도 한글이 깨지지 않게
    key = generate_private_key()
    print("Railway 변수에 넣으세요 (비밀값입니다):")
    print(f"DANBI_VAPID_PRIVATE_KEY={key}")
    print(f"\n(참고) 공개키: {public_key_of(key)}")
