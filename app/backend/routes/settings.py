"""Settings routes - configure download directory at runtime."""
from __future__ import annotations

from fastapi import APIRouter

from .. import config
from ..auth import UserDep
from ..models import SettingsResponse, SettingsUpdateRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(user=UserDep) -> SettingsResponse:
    return SettingsResponse(
        download_dir=str(config.get_download_dir()),
        default_model=config.DEFAULT_GEMINI_MODEL,
        pro_model=config.PRO_GEMINI_MODEL,
        telegram_enabled=bool(config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(payload: SettingsUpdateRequest, user=UserDep) -> SettingsResponse:
    new_path = config.set_download_dir(payload.download_dir)
    return SettingsResponse(
        download_dir=str(new_path),
        default_model=config.DEFAULT_GEMINI_MODEL,
        pro_model=config.PRO_GEMINI_MODEL,
        telegram_enabled=bool(config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN),
    )
