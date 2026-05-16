from __future__ import annotations
import logging
import os
import time
from pathlib import Path

import requests

from ads.models import Scene

logger = logging.getLogger(__name__)

_API_BASE = "https://api.higgsfield.ai/v1"
_MODEL = "seedance_2_0"
_POLL_INTERVAL = 10
_MAX_POLLS = 60

_CAMERA_MOTION_MAP = {
    "slow zoom in": "zoom_in",
    "slow zoom out": "zoom_out",
    "left pan": "pan_left",
    "right pan": "pan_right",
    "dolly forward": "dolly_forward",
    "dolly back": "dolly_back",
    "static": "static",
}


def animate(image_path: Path, scene: Scene, output_dir: Path) -> Path:
    """
    Animate a composited image using Higgsfield Seedance 2.0.
    Returns path to the downloaded .mp4 clip.
    """
    api_key = os.environ["HIGGSFIELD_API_KEY"]
    logger.info("Animating scene %d with Seedance 2.0", scene.index)

    media_id = _upload_image(image_path, api_key)
    job_id = _submit_job(media_id, scene, api_key)
    video_url = _poll_job(job_id, api_key)
    output_path = output_dir / f"scene_{scene.index:02d}.mp4"
    return _download_video(video_url, output_path)


def _upload_image(image_path: Path, api_key: str) -> str:
    """Upload image to Higgsfield and return the media UUID."""
    with open(image_path, "rb") as f:
        response = requests.post(
            f"{_API_BASE}/media/upload",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (image_path.name, f, "image/png")},
            timeout=60,
        )
    if not response.ok:
        raise RuntimeError(f"Upload failed: {response.status_code} {response.text}")
    return response.json()["id"]


def _submit_job(media_id: str, scene: Scene, api_key: str) -> str:
    """Submit animation job and return job ID."""
    camera = _CAMERA_MOTION_MAP.get(scene.camera_motion, "static")
    prompt = f"{scene.visual_prompt}. Camera: {camera}. Cinematic motion, smooth."

    payload = {
        "model": _MODEL,
        "prompt": prompt,
        "duration": int(scene.duration_sec),
        "medias": [{"value": media_id, "role": "start_image"}],
    }
    response = requests.post(
        f"{_API_BASE}/video/generate",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Job submission failed: {response.status_code} {response.text}")
    return response.json()["job_id"]


def _poll_job(job_id: str, api_key: str) -> str:
    """Poll until job completes. Returns video URL."""
    for attempt in range(_MAX_POLLS):
        time.sleep(_POLL_INTERVAL)
        response = requests.get(
            f"{_API_BASE}/jobs/{job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if not response.ok:
            raise RuntimeError(f"Job poll failed: {response.status_code}")
        data = response.json()
        status = data.get("status")
        if status == "completed":
            return data["output_url"]
        if status == "failed":
            raise RuntimeError(f"Higgsfield job failed: {data.get('error', 'unknown')}")
        logger.info("Scene animation: %s (attempt %d/%d)", status, attempt + 1, _MAX_POLLS)
    raise TimeoutError(f"Higgsfield job {job_id} timed out after {_MAX_POLLS * _POLL_INTERVAL}s")


def _download_video(url: str, output_path: Path) -> Path:
    """Download the animated video clip."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    logger.info("Downloaded animated clip: %s", output_path.name)
    return output_path
