# Railway 배포 가이드

Dockerfile로 빌드합니다(`railway.json`). 이미지 하나에 React 화면과 Python 서버가 함께 들어가고, RAG DB(`chroma_db_dd3/`)도 이미지에 포함됩니다.

## 1. 준비

1. 저장소를 GitHub에 올립니다. `chroma_db_dd3/`(약 51MB, 가장 큰 파일 27MB)는 일반 커밋으로 올라갑니다(LFS 불필요).
2. Railway에서 **New Project → Deploy from GitHub repo**로 저장소를 고릅니다. `railway.json`이 있어서 Dockerfile 빌드가 자동으로 선택됩니다.
3. **리전**: Settings → Region에서 아시아(예: Singapore)를 고릅니다. 학교 사이트와 사용자가 한국에 있어 응답이 빨라집니다.

## 2. 볼륨 (필수)

컨테이너 파일은 재배포 때마다 지워집니다. 추적 DB와 크롤링 캐시를 남기려면:

- 서비스 → **Volumes → New Volume**, Mount path: `/data`

(이미지에 `DANBI_DATA_DIR=/data`가 이미 설정되어 있습니다.)

## 3. 환경 변수 (Variables)

| 이름 | 값 | 설명 |
|---|---|---|
| `GOOGLE_API_KEY` | Gemini API 키 | LLM·임베딩 |
| `GOOGLE_CLIENT_ID` | OAuth 클라이언트 ID | 학교 Google 계정 로그인 (필수) — [GOOGLE_LOGIN.md](GOOGLE_LOGIN.md) |
| `GOOGLE_CLIENT_SECRET` | 클라이언트 보안 비밀번호 | 〃 |
| `DANBI_PUBLIC_URL` | `https://<도메인>` | Google 리디렉션 URI를 만들 때 쓴다 |
| `DANBI_ADMIN_EMAILS` | `a@dankook.ac.kr,…` | 개발자 페이지 `/dev`에 들어갈 수 있는 Google 계정 |
| `DANBI_OPERATOR` | 운영자 이름 | 개인정보처리방침(`/privacy`)의 책임자 |
| `DANBI_PRIVACY_CONTACT` | 문의 이메일 | 개인정보처리방침의 문의처 (Google 앱 게시에 필요한 페이지) |
| `DANBI_ADMIN_TOKEN` | (선택) 긴 무작위 문자열 | 개발자 페이지 비상용 토큰. 비워 두면 Google 로그인만. 예: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DANBI_TRUST_PROXY` | `1` | Railway 프록시 뒤라 필수. 없으면 모든 사용자가 같은 IP로 보여 요청 제한을 함께 나눠 씁니다 |
| `DANBI_PROXY_HOPS` | `1` (기본) | Railway 앞단 프록시 수. IP가 이상하게 찍히면 개발자 페이지에서 확인 후 조정 |
| `DANBI_ENABLE_DOCS` | (비워 둠) | `1`이면 `/api/docs` 공개. 운영에서는 끄세요 |
| `KAKAO_SKILL_SECRET` | 긴 무작위 문자열 | 카카오톡 챗봇 스킬 인증. 없으면 `/api/kakao/skill`이 열리지 않습니다 — [KAKAO_SETUP.md](KAKAO_SETUP.md) |
| `KAKAO_USER_SALT` | (선택) 다른 무작위 문자열 | 카카오 사용자 키 해시용. 한 번 정하면 바꾸지 마세요 |

`PORT`는 Railway가 자동으로 넣습니다. 서버는 `0.0.0.0:$PORT`로 열립니다.

## 4. 배포 후 확인

1. `https://<도메인>/api/health` → `{"ok": true}`
2. `https://<도메인>/` 에서 질문 하나 → 답변·출처 확인
3. `https://<도메인>/dev` 에서 토큰 입력 → 방금 질문이 기록됐는지, **클라이언트 IP가 Railway 내부 주소(10.x 등)가 아닌 실제 IP인지** 확인
4. 감사 로그 탭에서 무결성 확인 표시
5. 카카오를 쓰면 [KAKAO_SETUP.md](KAKAO_SETUP.md)대로 연결한 뒤 실제 카카오톡에서 질문 하나

## 5. 비용·남용 방어 (기본값은 `config/settings.yaml`의 `limits`)

| 항목 | 기본 |
|---|---|
| 1인 하루 | **3회** (웹 = 로그인한 Google 계정, 카카오 = 카카오 사용자). 추적 DB에서 세므로 재시작해도 유지, 한국 시간 자정 초기화 |
| 비로그인 웹 | 막혀 있음 (`auth.allow_anonymous: false`). 켜면 IP당 하루 3회 |
| 1인 분당 | 10회 |
| 서비스 전체(웹+카카오) | 하루 질문 1,000개, 하루 토큰 2,000만 |
| 동시 처리 | 4개 (넘으면 "지금 질문이 많아요") |
| 개발자 토큰 실패 | IP당 10분에 10회 (넘으면 잠금) |

**Google Cloud 콘솔에서도 Gemini API 사용량 한도(quota)와 예산 알림을 꼭 걸어 두세요.** 앱의 상한은 정상 동작을 전제로 한 방어선이고, 키가 유출되면 앱 밖에서 쓰일 수 있습니다.

## 6. 운영 메모

- **레플리카·워커는 1개로 유지**합니다. 세션·요청 제한이 메모리에 있고 DB가 SQLite라 여러 개로 늘리면 상태가 갈라집니다.
- 보관 기간 정리: Railway 서비스 셸에서 `python -m danbi.ops purge` (180일 지난 실행 삭제, 90일 지난 IP 비움, 감사 로그는 유지). 주기적으로 돌리려면 Railway Cron 서비스를 따로 둡니다.
- 감사 로그 무결성 검사: `python -m danbi.ops verify`
- RAG DB를 바꾸면 `chroma_db_dd3/`를 교체해 커밋하고 재배포합니다.
- 이미지 빌드는 로컬에서 `docker build -t danbi .`로 미리 확인할 수 있습니다.

## 7. 개인정보

저장되는 것: 질문 원문, 접속 IP, 로그인한 Google 계정의 이메일·이름(카카오는 사용자 키의 해시). 저장 위치는 Railway(해외 클라우드)의 볼륨입니다.
보관 기간은 정하지 않았습니다(`ops.retention_days`·`ip_retention_days`가 `null` = 무기한). 기간을 정하면 `python -m danbi.ops purge`가 그보다 오래된 기록을 지웁니다.
