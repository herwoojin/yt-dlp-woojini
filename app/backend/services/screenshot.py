"""Video frame capture using ffmpeg.

Provides two capture modes:
1. Blog images: JPG frames at specific timestamps for embedding in blog HTML.
2. Key scene screenshots: ~20 WebP frames distributed across chapters for ZIP download.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

_HMS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def _hms_to_seconds(ts: str) -> int:
    """Convert HH:MM:SS or H:MM:SS to total seconds."""
    m = _HMS.match(ts)
    if not m:
        return 0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def _seconds_to_hms(sec: int) -> str:
    """Convert total seconds to HH:MM:SS."""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _can_encode_webp() -> bool:
    """Check if ffmpeg can encode WebP (libwebp)."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        return "libwebp" in r.stdout
    except Exception:
        return False


# Cache the check at module load
_WEBP_OK: bool | None = None


def _webp_supported() -> bool:
    global _WEBP_OK
    if _WEBP_OK is None:
        _WEBP_OK = _can_encode_webp()
    return _WEBP_OK


def _scene_ext() -> str:
    """Return the best available image extension for scene captures."""
    return ".webp" if _webp_supported() else ".jpg"


def capture_frame(
    video_path: Path,
    timestamp: str,
    output_path: Path,
    quality: int = 85,
) -> bool:
    """Capture a single frame from *video_path* at *timestamp* (HH:MM:SS).

    The output format is inferred from *output_path* suffix (.jpg or .webp).
    Returns True on success, False on failure (non-fatal).
    """
    if not _ffmpeg_available():
        log.warning("ffmpeg not found – skipping frame capture")
        return False

    if not video_path.exists():
        log.warning("video file not found: %s", video_path)
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()

    cmd = [
        "ffmpeg", "-y",
        "-ss", timestamp,
        "-i", str(video_path),
        "-frames:v", "1",
        "-update", "1",
    ]

    if suffix == ".webp" and _webp_supported():
        cmd += ["-c:v", "libwebp", "-quality", str(quality)]
    elif suffix == ".webp" and not _webp_supported():
        # Fallback: capture as JPG instead
        output_path = output_path.with_suffix(".jpg")
        cmd += ["-q:v", "2"]
        cmd.append(str(output_path))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                log.warning("ffmpeg failed for %s at %s: %s", video_path.name, timestamp, result.stderr[:300])
                return False
            # Rename .jpg back to .webp for consistent file naming
            final_path = output_path.with_suffix(".webp")
            output_path.rename(final_path)
            return final_path.exists() and final_path.stat().st_size > 0
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg timed out for %s at %s", video_path.name, timestamp)
            return False
        except Exception as exc:
            log.warning("ffmpeg error: %s", exc)
            return False
    elif suffix in (".jpg", ".jpeg"):
        cmd += ["-q:v", "2"]  # high quality JPG
    # else: let ffmpeg decide from extension

    cmd.append(str(output_path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("ffmpeg failed for %s at %s: %s", video_path.name, timestamp, result.stderr[:300])
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg timed out for %s at %s", video_path.name, timestamp)
        return False
    except Exception as exc:
        log.warning("ffmpeg error: %s", exc)
        return False


def capture_blog_images(
    video_path: Path,
    timestamps: list[dict],
    output_dir: Path,
) -> list[dict]:
    """Capture blog images at the given timestamps.

    *timestamps* is a list of dicts: [{"index": 1, "timestamp": "00:05:30", "alt": "..."}, ...]
    Returns list of successfully captured images with their paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for item in timestamps:
        idx = item.get("index", 0)
        ts = item.get("timestamp", "00:00:10")
        alt = item.get("alt", "")
        filename = f"blog_img_{idx}.jpg"
        out_path = output_dir / filename

        # Offset +3 seconds from chapter start to get a more meaningful frame
        sec = _hms_to_seconds(ts) + 3
        adjusted_ts = _seconds_to_hms(sec)

        if capture_frame(video_path, adjusted_ts, out_path):
            results.append({
                "index": idx,
                "filename": filename,
                "timestamp": ts,
                "alt": alt,
            })
            log.info("captured blog image %s at %s", filename, adjusted_ts)
        else:
            log.warning("failed to capture blog image %d at %s", idx, adjusted_ts)

    return results


def _compute_scene_timestamps(
    chapters: list[dict],
    duration_seconds: int | None,
    target_count: int = 20,
) -> list[dict]:
    """Compute ~target_count evenly-distributed timestamps based on chapters.

    Strategy:
    - Each chapter gets at least one capture (chapter start + 5s).
    - Remaining slots are filled at midpoints between chapters.
    - If chapters are insufficient, fill with duration-based even intervals.
    """
    if not duration_seconds or duration_seconds <= 0:
        duration_seconds = 3600  # fallback 1hr

    # Auto-adjust count for short videos
    if duration_seconds < 300:  # < 5 min
        target_count = min(target_count, 10)
    elif duration_seconds < 120:  # < 2 min
        target_count = min(target_count, 5)

    timestamps: list[dict] = []

    if chapters:
        chapter_seconds = [_hms_to_seconds(c.get("time", "00:00:00")) for c in chapters]

        # 1) Each chapter start + 5s
        for i, ch in enumerate(chapters):
            sec = chapter_seconds[i] + 5
            if sec >= duration_seconds:
                sec = max(0, duration_seconds - 5)
            timestamps.append({
                "seconds": sec,
                "label": ch.get("title", f"Scene {i+1}"),
            })

        # 2) Fill remaining slots with midpoints
        remaining = target_count - len(timestamps)
        if remaining > 0 and len(chapter_seconds) > 1:
            # Add midpoints between adjacent chapters
            midpoints = []
            for i in range(len(chapter_seconds) - 1):
                mid = (chapter_seconds[i] + chapter_seconds[i + 1]) // 2
                midpoints.append({
                    "seconds": mid,
                    "label": f"Between: {chapters[i].get('title', '')} ~ {chapters[i+1].get('title', '')}",
                })
            # Take evenly spaced midpoints
            if len(midpoints) > remaining:
                step = len(midpoints) / remaining
                selected = [midpoints[int(i * step)] for i in range(remaining)]
                timestamps.extend(selected)
            else:
                timestamps.extend(midpoints)
    else:
        # No chapters: distribute evenly across duration
        interval = duration_seconds / (target_count + 1)
        for i in range(1, target_count + 1):
            sec = int(interval * i)
            timestamps.append({
                "seconds": sec,
                "label": f"Scene {i}",
            })

    # Sort by time, deduplicate nearby timestamps (within 5 seconds)
    timestamps.sort(key=lambda x: x["seconds"])
    deduped: list[dict] = []
    for ts in timestamps:
        if deduped and abs(ts["seconds"] - deduped[-1]["seconds"]) < 5:
            continue
        deduped.append(ts)

    # Trim to target_count
    if len(deduped) > target_count:
        step = len(deduped) / target_count
        deduped = [deduped[int(i * step)] for i in range(target_count)]

    return deduped


def capture_key_scenes(
    video_path: Path,
    chapters: list[dict],
    duration_seconds: int | None,
    output_dir: Path,
    target_count: int = 20,
) -> list[dict]:
    """Capture ~target_count key scene screenshots as WebP files.

    Returns list of dicts with filename, timestamp, and label for each capture.
    """
    scenes_dir = output_dir / "screenshots"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    scene_timestamps = _compute_scene_timestamps(chapters, duration_seconds, target_count)
    results: list[dict] = []

    ext = _scene_ext()
    for i, ts_info in enumerate(scene_timestamps, start=1):
        sec = ts_info["seconds"]
        label = ts_info.get("label", f"Scene {i}")
        hms = _seconds_to_hms(sec)
        filename = f"scene_{i:02d}_{hms.replace(':', '')}{ext}"
        out_path = scenes_dir / filename

        if capture_frame(video_path, hms, out_path, quality=80):
            # Check actual file (might have been renamed during fallback)
            actual = out_path if out_path.exists() else out_path.with_suffix('.jpg')
            if not actual.exists():
                actual = out_path
            results.append({
                "index": i,
                "filename": actual.name,
                "timestamp": hms,
                "label": label,
                "size_bytes": actual.stat().st_size if actual.exists() else 0,
            })
            log.info("captured scene %02d at %s: %s", i, hms, label)
        else:
            log.warning("failed to capture scene %02d at %s", i, hms)

    return results


def create_screenshots_zip(job_dir: Path) -> Path | None:
    """Bundle all scene image files in job_dir/screenshots/ into screenshots.zip.

    Returns the zip path on success, None if no files to bundle.
    """
    scenes_dir = job_dir / "screenshots"
    if not scenes_dir.exists():
        return None

    # Collect both webp and jpg files
    image_files = sorted(
        [f for f in scenes_dir.iterdir() if f.suffix.lower() in (".webp", ".jpg", ".jpeg")]
    )
    if not image_files:
        return None

    zip_path = job_dir / "screenshots.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in image_files:
                zf.write(f, arcname=f.name)
        log.info("created screenshots.zip with %d files (%d bytes)", len(image_files), zip_path.stat().st_size)
        return zip_path
    except Exception as exc:
        log.warning("failed to create screenshots.zip: %s", exc)
        return None
