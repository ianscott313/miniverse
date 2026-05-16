from __future__ import annotations
import logging
import os
import subprocess
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_PIXABAY_API = "https://pixabay.com/api/music/"
_TARGET_LUFS = -14

_MOOD_QUERY_MAP = {
    "uplifting pop": "uplifting energetic",
    "cinematic tension": "cinematic dramatic",
    "romantic lifestyle": "romantic soft",
    "epic adventure": "epic powerful",
    "chill luxury": "ambient relaxing",
}


def fetch(mood: str, output_dir: Path) -> Path:
    """Download and normalize royalty-free music for the given mood."""
    track = _search_pixabay(mood)
    if track is None:
        raise RuntimeError(f"No music found for mood: '{mood}'")
    raw_path = _download_track(track["audio"], output_dir)
    return _normalize_audio(raw_path, output_dir)


def _search_pixabay(mood: str) -> dict | None:
    """Search Pixabay Music API. Returns first hit or None."""
    query = _MOOD_QUERY_MAP.get(mood, mood)
    params: dict = {"q": query, "per_page": 5}
    api_key = os.environ.get("PIXABAY_API_KEY", "")
    if api_key:
        params["key"] = api_key

    response = requests.get(_PIXABAY_API, params=params, timeout=15)
    response.raise_for_status()
    hits = response.json().get("hits", [])
    return hits[0] if hits else None


def _download_track(url: str, output_dir: Path) -> Path:
    """Download audio track from URL."""
    logger.info("Downloading music track")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    raw = output_dir / "music_raw.mp3"
    raw.write_bytes(response.content)
    return raw


def _normalize_audio(raw_path: Path, output_dir: Path) -> Path:
    """Normalize audio to target LUFS using ffmpeg loudnorm filter."""
    out = output_dir / "music.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(raw_path),
            "-af", f"loudnorm=I={_TARGET_LUFS}:TP=-1.5:LRA=11",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out
