"""지금 답하고 있는 질문의 사용자.

개인 자료 도구는 사용자를 인자로 받지 않고 여기서만 읽는다. 모델이 다른 사람의 ID를 넣어 부를 길이 없다.
API가 질문마다 설정하고, 에이전트가 도구를 실행하는 태스크·스레드로 그대로 이어진다
(asyncio.create_task와 asyncio.to_thread는 호출 시점의 컨텍스트를 복사한다).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    user_id: int      # users.id (웹 Google 로그인)
    user_key: str     # google:<id>


CURRENT_USER: ContextVar[CurrentUser | None] = ContextVar("danbi_current_user", default=None)
