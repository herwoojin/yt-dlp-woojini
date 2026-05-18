"""FastAPI entrypoint. Also boots the Telegram bot in a background thread
when TELEGRAM_BOT_TOKEN is configured.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .jobs import registry
from .routes import files, jobs, settings
from .services import telegram_bot

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
    yield


app = FastAPI(title="yt-dlp web app", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(files.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
