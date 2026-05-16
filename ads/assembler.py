from __future__ import annotations
import dataclasses
import json
import logging
import subprocess
from pathlib import Path

from ads.models import AdBrief, AdOutput, SceneAsset

logger = logging.getLogger(__name__)

_MUSIC_VOLUME_DB = -18


def assemble(
    assets: list[SceneAsset],
    music_path: Path,
    brief: AdBrief,
    output_dir: Path,
) -> AdOutput:
    """Full assembly: merge scenes, concatenate, mix music, add tagline title."""
    scenes_dir = output_dir / "scenes"
    scenes_dir.mkdir(exist_ok=True)

    merged_clips = [_merge_scene_audio_video(asset, scenes_dir) for asset in assets]
    no_music = _concatenate_scenes(merged_clips, output_dir)
    with_music = _mix_music(no_music, music_path, output_dir)
    final = _add_tagline_title(with_music, brief.tagline, output_dir)

    _save_brief_json(brief, output_dir)

    duration = _get_duration(final)
    logger.info("Ad assembled: %s (%.1fs)", final.name, duration)
    return AdOutput(
        brief=brief,
        assets=assets,
        music_path=music_path,
        final_video_path=final,
        duration_sec=duration,
    )


def _merge_scene_audio_video(asset: SceneAsset, output_dir: Path) -> Path:
    """Merge one scene's video clip with its voice audio."""
    out = output_dir / f"scene_{asset.scene.index:02d}_merged.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(asset.video_path),
            "-i", str(asset.audio_path),
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return out


def _concatenate_scenes(clips: list[Path], output_dir: Path) -> Path:
    """Concatenate all scene clips into one video without music."""
    list_file = output_dir / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{c}'" for c in clips))
    out = output_dir / "ad_no_music.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(out)],
        check=True, capture_output=True,
    )
    return out


def _mix_music(video_path: Path, music_path: Path, output_dir: Path) -> Path:
    """Mix background music under the voiceover at reduced volume."""
    out = output_dir / "ad_with_music.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            (
                f"[1:a]volume={_MUSIC_VOLUME_DB}dB,"
                "afade=t=in:d=1,afade=t=out:st=999:d=2[music];"
                "[0:a][music]amix=inputs=2:duration=first[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return out


def _add_tagline_title(video_path: Path, tagline: str, output_dir: Path) -> Path:
    """Burn tagline text in the last 2.5 seconds of the video."""
    duration = _get_duration(video_path)
    title_start = max(0, duration - 2.5)
    out = output_dir / "ad_final.mp4"
    safe_tagline = tagline.replace("'", "\\'")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf",
            (
                f"drawtext=text='{safe_tagline}'"
                f":fontsize=48:fontcolor=white"
                f":x=(w-text_w)/2:y=h*0.8"
                f":enable='gte(t,{title_start:.2f})'"
                ":shadowcolor=black:shadowx=2:shadowy=2"
            ),
            "-c:a", "copy",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return out


def _get_duration(video_path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _save_brief_json(brief: AdBrief, output_dir: Path) -> None:
    """Serialize AdBrief to brief.json in output_dir."""
    data = dataclasses.asdict(brief)
    (output_dir / "brief.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
