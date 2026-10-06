"""개인정보처리방침 페이지 (/privacy). Google OAuth 앱을 '프로덕션'으로 게시하려면 이 URL이 필요하다.

내용은 실제 처리와 맞아야 한다: 저장 항목·보관 기간·위탁 업체를 바꾸면 이 문서도 함께 고친다.
문의처는 환경 변수 DANBI_PRIVACY_CONTACT(이메일), 운영자 이름은 DANBI_OPERATOR로 받는다.
"""

from __future__ import annotations

import html
import os

EFFECTIVE_DATE = "2026년 10월 6일"

_STYLE = """
body{margin:0;background:#f8fafc;color:#0f172a;font:15px/1.7 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:760px;margin:0 auto;padding:40px 20px 64px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:17px;margin:32px 0 8px}
p,li{color:#334155}ul{padding-left:20px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid #e2e8f0;padding:8px 10px;text-align:left;vertical-align:top}th{background:#f1f5f9}
.muted{color:#64748b;font-size:13px}a{color:#1d4ed8}
@media (prefers-color-scheme:dark){body{background:#0b1220;color:#e2e8f0}p,li{color:#cbd5e1}
th,td{border-color:#1e293b}th{background:#111a2e}a{color:#93c5fd}}
"""


def render_privacy() -> str:
    operator = html.escape(os.environ.get("DANBI_OPERATOR") or "단비 운영자")
    contact = os.environ.get("DANBI_PRIVACY_CONTACT") or ""
    contact_html = (f'<a href="mailto:{html.escape(contact)}">{html.escape(contact)}</a>' if contact
                    else "운영자에게 문의")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>개인정보처리방침 — 단비</title><link rel="icon" href="data:,"><style>{_STYLE}</style></head>
<body><main>
<h1>개인정보처리방침</h1>
<p class="muted">단비(단국대학교 비서 AI) · 시행일 {EFFECTIVE_DATE}</p>
<p>{operator}(이하 "운영자")는 단비 서비스(웹 채팅과 카카오톡 채널)를 이용하는 분의 개인정보를 아래와 같이 처리합니다.</p>

<h2>1. 처리하는 개인정보 항목</h2>
<table>
<tr><th>구분</th><th>항목</th></tr>
<tr><td>웹 (학교 Google 계정 로그인)</td><td>이메일 주소, 이름, Google 계정 고유 식별자, 소속 도메인(dankook.ac.kr)</td></tr>
<tr><td>카카오톡 채널</td><td>카카오가 제공하는 사용자 식별값을 되돌릴 수 없게 변환(해시)한 값 (원래 식별값은 저장하지 않음)</td></tr>
<tr><td>이용 과정에서 자동 생성</td><td>접속 IP 주소, 로그인·이용 일시, 질문과 답변 내용, 답변 평가(좋아요·아쉬워요), 로그인 유지용 쿠키</td></tr>
</table>
<p>질문 내용에 개인정보를 적지 않도록 주의해 주세요. 적은 내용도 질문 기록으로 저장됩니다.</p>

<h2>2. 수집 방법</h2>
<ul><li>Google 로그인 시 이용자의 동의에 따라 Google로부터 이메일·이름·계정 식별자를 받습니다 (범위: openid, email, profile).</li>
<li>서비스를 이용하는 과정에서 접속 IP, 이용 일시, 질문·답변이 자동으로 기록됩니다.</li></ul>

<h2>3. 이용 목적</h2>
<ul><li>단국대학교 구성원 여부 확인과 로그인 유지</li>
<li>질문에 대한 답변 제공과 대화 이어 가기</li>
<li>1인당 이용 횟수 제한, 부정 이용 방지</li>
<li>답변 품질 개선, 오류 분석, 서비스 운영 기록(감사) 관리</li></ul>

<h2>4. 보유 및 이용 기간</h2>
<p>개인정보는 서비스를 운영하는 동안 보관합니다. 이용자가 삭제를 요청하거나 서비스를 종료하면 지체 없이 파기합니다.
다만 관련 법령에 따라 보존해야 하는 경우에는 그 기간 동안 보관합니다.</p>

<h2>5. 처리 위탁 및 국외 이전</h2>
<table>
<tr><th>받는 곳</th><th>업무</th><th>이전 국가·방법</th></tr>
<tr><td>Google LLC</td><td>Google 로그인 인증, 질문에 대한 답변 생성(Gemini API)과 문서 검색용 임베딩</td><td>미국 등 · 이용 시마다 네트워크로 전송</td></tr>
<tr><td>Railway Corp.</td><td>서버 운영과 데이터 저장</td><td>미국 · 서비스 운영 기간 동안 저장</td></tr>
<tr><td>(주)카카오</td><td>카카오톡 채널 메시지 송수신</td><td>대한민국 · 카카오톡 이용 시</td></tr>
</table>
<p>위 목적 외에 개인정보를 제3자에게 제공하지 않습니다. 법령에 따른 요청이 있는 경우는 예외입니다.</p>

<h2>6. 개인정보의 파기</h2>
<p>파기 사유가 생기면 저장된 전자 파일을 복구할 수 없는 방법으로 삭제합니다.</p>

<h2>7. 이용자의 권리</h2>
<p>이용자는 자신의 개인정보에 대해 열람, 정정, 삭제, 처리 정지를 요청할 수 있습니다. 아래 문의처로 요청하면 지체 없이 처리합니다.</p>

<h2>8. 안전성 확보 조치</h2>
<ul><li>모든 통신은 HTTPS로 암호화합니다.</li>
<li>로그인 유지 정보는 브라우저 스크립트가 읽을 수 없는 쿠키에 담고, 서버에는 그 값을 되돌릴 수 없게 변환(해시)해 저장합니다. Google의 인증 토큰은 저장하지 않습니다.</li>
<li>운영 기록 열람은 지정된 관리자로 제한하고, 열람 기록을 위·변조를 확인할 수 있는 감사 로그로 남깁니다.</li></ul>

<h2>9. 쿠키</h2>
<p>로그인 상태를 유지하기 위한 쿠키만 사용합니다. 광고나 행태 추적을 위한 쿠키는 사용하지 않습니다.
브라우저에서 쿠키를 거부할 수 있지만, 그 경우 로그인이 필요한 웹 채팅을 이용할 수 없습니다.</p>

<h2>10. 문의처</h2>
<p>개인정보 보호 책임자: {operator} · {contact_html}</p>

<p class="muted">이 방침이 바뀌면 이 페이지에 시행일과 함께 알립니다.</p>
</main></body></html>"""
