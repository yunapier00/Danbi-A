"""사용자 개인 자료 연동 (로그인한 사용자 본인 것만). 지금은 eclass(Canvas) 캘린더 피드."""

from .context import CURRENT_USER, CurrentUser

__all__ = ["CURRENT_USER", "CurrentUser"]
