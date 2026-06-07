import asyncio
import tempfile
import urllib.parse
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import edge_tts
from ..config import DOWNLOAD_DIR
from pathlib import Path

router = APIRouter(prefix="/api/tts", tags=["tts"])

# "FEMALE": "ko-KR-SunHiNeural"
# "MALE": "ko-KR-InJoonNeural"
VOICE_MAP = {
    "female": "ko-KR-SunHiNeural",
    "male": "ko-KR-InJoonNeural"
}

class TTSRequest(BaseModel):
    text: str
    voice: str = "female"
    rate: float = 1.0

async def stream_audio(text: str, voice_id: str, rate_str: str):
    communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]

@router.post("/generate")
async def generate_tts_audio(req: TTSRequest):
    voice_id = VOICE_MAP.get(req.voice.lower(), "ko-KR-SunHiNeural")
    
    # edge-tts rate format is e.g. "+50%" or "-20%"
    # 1.0x -> +0%
    # 2.0x -> +100%
    # 3.0x -> +200%
    rate_percent = int((req.rate - 1.0) * 100)
    rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

    return StreamingResponse(
        stream_audio(req.text, voice_id, rate_str),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=\"tts_audio.mp3\"",
            "Accept-Ranges": "bytes"
        }
    )
