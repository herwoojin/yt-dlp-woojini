# yt-dlp web app — Fly.io deploy image
# Build context: app/ (Dockerfile lives at app/Dockerfile)
FROM python:3.12-slim

# 시스템 의존성: ffmpeg, curl, tini, unzip(deno), git(bgutil clone)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        tini \
        unzip \
        git \
    && rm -rf /var/lib/apt/lists/*

# Node.js (bgutil PO 토큰 프로바이더 서버용)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# JS 런타임(Deno): yt-dlp가 YouTube n-challenge(JS 서명)·PO 토큰을 푸는 데 필요.
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && chmod +x /usr/local/bin/deno \
    && /usr/local/bin/deno --version

# bgutil PO 토큰 프로바이더 서버 (YouTube "Sign in to confirm you're not a bot" 우회).
# 로컬 127.0.0.1:4416 에서 PO 토큰을 발급 → yt-dlp 플러그인이 자동 사용.
RUN git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && npm install --no-audit --no-fund \
    && npx tsc \
    && ls build/main.js

WORKDIR /app

# 의존성 먼저 (레이어 캐싱)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 앱 코드
COPY backend /app/backend
COPY frontend-html /app/frontend-html

# 다운로드 디렉터리 (fly.io volume이 /data에 마운트됨)
ENV DOWNLOAD_DIR=/data/downloads
RUN mkdir -p /data/downloads

EXPOSE 8000

# tini로 PID 1을 처리하여 signal 전파 정상화
ENTRYPOINT ["/usr/bin/tini", "--"]
# bgutil PO 토큰 서버를 백그라운드로 띄우고 uvicorn 실행 (yt-dlp 플러그인이 4416 포트 자동 사용)
CMD ["sh", "-c", "node /opt/bgutil/server/build/main.js >/tmp/bgutil.log 2>&1 & exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1"]
