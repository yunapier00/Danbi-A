# Google 로그인 설정 가이드

웹 채팅은 단국대학교 Google 계정(`@dankook.ac.kr`)으로 로그인해야 쓸 수 있다. 서버 구현은 `danbi/api/auth.py`.
카카오톡 채널은 로그인과 상관없이 카카오 사용자 기준 하루 3회로 그대로 동작한다.

## 동작 요약

- **흐름:** 인가 코드 + PKCE (OpenID Connect).
  1. `/api/auth/login`이 Google로 보낸다.
  2. Google이 `/api/auth/callback`으로 돌려보내면, 서버가 code를 토큰으로 바꾸고 ID 토큰을 검증한다.
  3. 검증을 통과하면 세션 쿠키를 발급한다.
  - 프론트에는 Google 스크립트가 없다. 버튼은 링크라 CSP(`'self'`)를 그대로 쓴다.
- **검증:**
  - ID 토큰 서명·`iss`·`aud`·`exp` (google-auth)
  - `nonce`, `state`(로그인 시작 쿠키와 대조, 한 번만 사용)
  - `email_verified`
  - `hd`와 이메일 도메인이 모두 `auth.allowed_domain`이어야 함
- **세션:** 브라우저에는 무작위 세션 ID만 `__Host-danbi_session` 쿠키(HttpOnly·Secure·SameSite=Lax)로 준다.
  - DB(`auth_sessions`)에는 SHA-256 해시만 둔다.
  - 30일 동안 유지되고, 쓸 때마다 연장된다.
  - Google 토큰은 저장하지 않는다.
- **CSRF:** `/api/*` 쓰기 요청은 `Origin`이 우리 도메인일 때만 받는다(카카오 스킬 제외).
- **저장:**
  - `users`: Google `sub`, 이메일, 이름, 도메인, 처음·마지막 로그인 IP와 시각
  - `auth_sessions`: 로그인 IP
  - 질문마다 `runs.user_key = google:<id>`와 `client_ip`가 남는다.
  - 보관 기간은 정하지 않았다(무기한).
- **하루 제한:** 로그인 사용자당 3회(`limits.per_user_per_day`). 같은 와이파이를 쓰는 사람과 섞이지 않는다.
- **비로그인:** 구현돼 있지만 꺼 둠(`auth.allow_anonymous: false`). 켜면 IP당 하루 3회.
- **차단:** `TraceStore.set_user_blocked(user_id, True)`를 쓰면 세션이 바로 끊기고 다시 로그인할 수 없다.
- **개발자 페이지(`/dev`):**
  - `DANBI_ADMIN_EMAILS`에 있는 계정으로 Google 로그인한다. 로그인한 지 12시간 안에만 들어갈 수 있다.
  - 감사 로그에 `google:<이메일>`로 남는다.
  - 비상용으로 `DANBI_ADMIN_TOKEN`(Bearer)도 그대로 쓸 수 있다. 비워 두면 꺼진다.

## 1. Google Cloud Console

1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 선택(또는 새로 만들기).
2. **API 및 서비스 → OAuth 동의 화면**에서 앱 이름(단비), 지원 이메일을 입력하고 범위는 `openid`, `email`, `profile`만 둔다.
   - 사용자 유형: 학교 Workspace 관리 권한이 없으면 "외부(External)"로 하고, 로그인 제한은 서버가 도메인 검사로 한다.
   - "테스트" 상태에서는 등록한 테스트 사용자만 로그인할 수 있다. 공개하려면 **앱 게시(프로덕션)** 로 바꾼다.
     게시하려면 **개인정보처리방침 URL**이 필요하다 → `https://<배포 도메인>/privacy` (단비 서버가 제공, `danbi/api/privacy.py`).
   - 승인된 도메인: `<배포 도메인>` (예: `danbi-a-production.up.railway.app`). 앱 로고는 올리지 않는다 (올리면 Google 앱 인증 대상이 된다).
3. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**: 유형 "웹 애플리케이션".
   - 승인된 리디렉션 URI:
     - `https://<배포 도메인>/api/auth/callback`
     - `http://localhost:5173/api/auth/callback` (로컬 개발, Vite 프록시 경유)
     - `http://localhost:8000/api/auth/callback` (로컬, 빌드한 화면을 서버로 볼 때)
   - 만들어진 **클라이언트 ID**와 **클라이언트 보안 비밀번호**를 복사한다.

## 2. 서버 환경 변수 (Railway Variables / 로컬 `.env`)

| 이름 | 값 |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 클라이언트 보안 비밀번호 |
| `DANBI_PUBLIC_URL` | `https://<배포 도메인>` (리디렉션 URI를 만들 때 쓴다. 프록시 뒤에서 http로 잘못 만들어지는 것을 막는다) |
| `DANBI_ADMIN_EMAILS` | 개발자 페이지 관리자, 쉼표로 구분 (예: `a@dankook.ac.kr,b@dankook.ac.kr`) |
| `DANBI_ADMIN_TOKEN` | (선택) 비상용 관리자 토큰. 비워 두면 Google 로그인만 |
| `DANBI_OPERATOR` | 개인정보처리방침의 운영자·책임자 이름 |
| `DANBI_PRIVACY_CONTACT` | 개인정보처리방침의 문의 이메일 |

로컬 개발에서 로그인 없이 채팅하려면 `DANBI_ALLOW_ANONYMOUS=1`을 쓴다.

## 3. 확인

1. `/api/me` → `{"user": null, "login_enabled": true, "anonymous_allowed": false, …}`
2. 화면의 "학교 Google 계정으로 로그인" 버튼을 누르고 학교 계정으로 로그인하면, 오른쪽 위에 이름과 로그아웃이 보인다.
3. 개인 Gmail로 로그인하면 "단국대학교 Google 계정(@dankook.ac.kr)으로만 로그인할 수 있어요."가 나와야 한다.
4. `/dev`에서 관리자 계정으로 로그인한다. 관리자가 아닌 계정은 "관리자 계정이 아닙니다"가 나온다.
