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
    CANCELLED = "cancelled"


GeminiQuality = Literal["flash", "pro"]


class JobCreateRequest(BaseModel):
    url: HttpUrl
    quality: GeminiQuality = "flash"
    video_format: str = Field(
        default="best[ext=mp4]/best",
        description="yt-dlp format selector. Default keeps the file local without size cap.",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="사용자 본인의 Gemini API 키. 전달 시 서버 키 대신 사용.",
    )
    outputs: list[str] | None = Field(
        default=None,
        description="생성할 산출물 키 목록(video,transcript,screenshots,chapters,summary,email). "
                    "blog(블로그 long+복사)은 항상 생성. None이면 전부 생성(하위호환).",
    )
    study_lang: str | None = Field(
        default=None,
        description="언어학습 버전에서 배울 목표 언어(예: 일본어/중국어/영어). None이면 자동 판별.",
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
    outputs: list[str] | None = None
    artifacts: list[JobArtifact] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)
    duration_seconds: int | None = None
    naver_mode: bool = False
    deep_research: bool = False
    lang_study: bool = False  # 언어학습 버전(스크립트 원문 보존 학습용)
    # 언어학습에서 "무슨 언어를 배우는가". 영상 음성 언어가 아니라 *학습 목표* 언어다.
    # (한국어 강의로 일본어를 가르치는 영상이 많아 자동 판별은 한국어로 오인한다)
    study_lang: str | None = None


class SettingsResponse(BaseModel):
    download_dir: str
    default_model: str
    pro_model: str
    telegram_enabled: bool


class SettingsUpdateRequest(BaseModel):
    download_dir: str
