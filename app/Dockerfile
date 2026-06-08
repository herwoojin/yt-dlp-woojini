# yt-dlp web app — Fly.io deploy image
# Build context: app/ (Dockerfile lives at app/Dockerfile)
FROM python:3.12-slim

# 시스템 의존성: ffmpeg (yt-dlp 후처리), curl (healthcheck), tini (init), unzip (deno 설치)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# JS 런타임(Deno): yt-dlp가 YouTube n-challenge(JS 서명)를 풀려면 필요.
# 없으면 'No video formats found' / 'n challenge solving failed' 발생.
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && chmod +x /usr/local/bin/deno \
    && /usr/local/bin/deno --version

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
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
