from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path

SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_PIXELS = 200
MIN_FREE_DISK_MB = 500


def pre_flight(image_path: Path) -> None:
    """Validate all prerequisites before spending any API credits."""
    _check_env("OPENAI_API_KEY")
    _check_env("ELEVENLABS_API_KEY")
    _check_env("HIGGSFIELD_API_KEY")
    _check_ffmpeg()
    _check_image(image_path)
    _check_disk_space()


def post_validate(output_dir: Path) -> None:
    """Verify the assembled ad output is complete and playable."""
    final = output_dir / "ad_final.mp4"
    if not final.exists():
        raise FileNotFoundError(f"ad_final.mp4 not found in {output_dir}")
    brief = output_dir / "brief.json"
    if not brief.exists():
        raise FileNotFoundError(f"brief.json not found in {output_dir}")
    _check_video_playable(final)
    _check_video_duration(final)


def _check_env(key: str) -> None:
    if not os.environ.get(key):
        raise EnvironmentError(
            f"{key} is not set. Export it before running the ads pipeline."
        )


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise EnvironmentError("ffmpeg not found in PATH. Install it with: winget install ffmpeg")
    if not shutil.which("ffprobe"):
        raise EnvironmentError("ffprobe not found in PATH. Install ffmpeg (includes ffprobe).")


def _check_image(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Product image not found: {path.name}")
    if path.suffix.lower() not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(f"Unsupported image format: {path.suffix}. Use jpg, png, or webp.")
    from PIL import Image
    with Image.open(path) as img:
        w, h = img.size
        if w < MIN_IMAGE_PIXELS or h < MIN_IMAGE_PIXELS:
            raise ValueError(f"Image too small ({w}x{h}). Minimum: {MIN_IMAGE_PIXELS}px per side.")


def _check_disk_space() -> None:
    stat = shutil.disk_usage(".")
    free_mb = stat.free / (1024 * 1024)
    if free_mb < MIN_FREE_DISK_MB:
        raise OSError(f"Insufficient disk space: {free_mb:.0f}MB free, need {MIN_FREE_DISK_MB}MB.")


def _ffprobe_duration(path: Path) -> float:
    """Run ffprobe and return video duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def _check_video_playable(path: Path) -> None:
    try:
        _ffprobe_duration(path)
    except RuntimeError:
        raise RuntimeError(f"ad_final.mp4 is not playable")


def _check_video_duration(path: Path) -> None:
    duration = _ffprobe_duration(path)
    if not (25 <= duration <= 65):
        raise ValueError(f"Ad duration {duration:.1f}s is outside 25-65s range.")
