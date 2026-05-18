"""Filesystem layout helpers.

Each job lives under <DOWNLOAD_DIR>/<job_id>/ with:
  video.* | transcript.txt | chapters.json | summary_short.html |
  email_readable.html | blog_long.html | job.json
"""
from __future__ import annotations

from pathlib import Path

from .. import config


def job_dir(job_id: str) -> Path:
    path = config.get_download_dir() / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_path(job_id: str, filename: str) -> Path:
    return job_dir(job_id) / filename
