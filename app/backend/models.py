"""Pydantic schemas for request / response payloads."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


GeminiQuality = Literal["flash", "pro"]


class JobCreateRequest(BaseModel):
    url: HttpUrl
    quality: GeminiQuality = "flash"
    video_format: str = Field(
        default="best[ext=mp4]/best",
        description="yt-dlp format selector. Default keeps the file local without size cap.",
    )


class JobArtifact(BaseModel):
    kind: str
    filename: str
    size_bytes: int | None = None


class JobInfo(BaseModel):
    id: str
    url: str
    title: str | None = None
    status: JobStatus
    quality: GeminiQuality
    video_format: str = "best[ext=mp4]/best"
    progress: float = 0.0
    message: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    owner_uid: str | None = None
    artifacts: list[JobArtifact] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)
    duration_seconds: int | None = None


class SettingsResponse(BaseModel):
    download_dir: str
    default_model: str
    pro_model: str
    telegram_enabled: bool


class SettingsUpdateRequest(BaseModel):
    download_dir: str
