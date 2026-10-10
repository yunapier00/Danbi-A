# syntax=docker/dockerfile:1
# 단비 배포 이미지 (Railway 등). 2단계: ① React 빌드 ② Python 서버 + 빌드 결과.
#
#   docker build -t danbi .
#   docker run -p 8000:8000 -e PORT=8000 -e GOOGLE_API_KEY=... -e DANBI_ADMIN_TOKEN=... \
#              -e DANBI_DATA_DIR=/data -v danbi-data:/data danbi
#
# 쓰기가 필요한 데이터(추적 DB·크롤링 캐시)는 DANBI_DATA_DIR(볼륨)에 둔다. RAG DB(chroma_db_v2, scripts/build_rag.py로 생성)는 읽기만 하므로 이미지에 넣는다.

# ---------- ① 웹 화면 빌드 ----------
FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite.config.ts의 outDir(../danbi/api/web) → /src/danbi/api/web
RUN npm run build

# ---------- ② 서버 ----------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DANBI_DATA_DIR=/data
WORKDIR /app

# 의존성 먼저 (코드만 바뀌면 이 층은 캐시를 쓴다). 설정 경로가 /app 기준이라 편집 가능 설치를 쓴다.
COPY pyproject.toml ./
RUN mkdir -p danbi && touch danbi/__init__.py && pip install -e . && rm -rf danbi

COPY danbi/ danbi/
COPY config/ config/
COPY chroma_db_v2/ chroma_db_v2/
COPY --from=web /src/danbi/api/web danbi/api/web

# Railway 볼륨은 root 소유로 붙으므로 root로 실행한다 (비루트로 돌리면 /data에 쓰지 못한다).
RUN mkdir -p /data
EXPOSE 8000
CMD ["python", "-m", "danbi.api", "--log", "INFO"]
