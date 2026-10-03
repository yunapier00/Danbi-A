"""python -m danbi.api [--host 127.0.0.1] [--port 8000]

배포 환경(Railway 등)에서는 PORT 환경 변수가 있으면 0.0.0.0:$PORT로 연다.
세션·요청 제한이 메모리에 있고 DB가 SQLite이므로 워커는 1개만 쓴다.
"""

import argparse
import logging
import os

import uvicorn

from .main import build_default_app


def main() -> None:
    ap = argparse.ArgumentParser(description="단비 API 서버 + 웹 채팅")
    ap.add_argument("--host", default=os.environ.get("DANBI_HOST") or ("0.0.0.0" if "PORT" in os.environ else "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--log", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=args.log.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # X-Forwarded-For는 앱이 직접 해석한다 (DANBI_TRUST_PROXY). uvicorn의 proxy_headers는 끈다.
    uvicorn.run(build_default_app(), host=args.host, port=args.port, workers=1, proxy_headers=False)


if __name__ == "__main__":
    main()
