"""FastAPI entrypoint. Also boots the Telegram bot in a background thread
when TELEGRAM_BOT_TOKEN is configured.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .jobs import registry
from .routes import files, jobs, settings, worker
from .services import remote_worker, telegram_bot

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend-html"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ytdlp-app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await registry.start_worker()
    if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN:
        thread = threading.Thread(target=telegram_bot.run_polling, daemon=True, name="telegram-bot")
        thread.start()
        log.info("telegram bot thread started")
    else:
        log.info("telegram bot disabled (no token or TELEGRAM_ENABLED=false)")
    if config.REMOTE_WORKER_URL and config.WORKER_TOKEN:
        threading.Thread(target=remote_worker.run_polling, daemon=True, name="remote-worker").start()
        log.info("remote worker thread started (pull from %s)", config.REMOTE_WORKER_URL)
    yield


app = FastAPI(title="yt-dlp web app", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=config.ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(files.router)
app.include_router(worker.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root():
    index = FRONTEND_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/blog-studio.html", response_class=HTMLResponse)
def blog_studio():
    page = FRONTEND_DIR / "blog-studio.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

# Catch-all for static files (manifest.webmanifest, icon.svg, sw.js, etc.)
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
