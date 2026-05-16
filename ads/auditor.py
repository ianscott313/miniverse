from __future__ import annotations
import base64
import json
import logging
import os
import subprocess
from pathlib import Path

from openai import OpenAI

from ads.models import AdBrief, AuditResult, Scene

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

_AUDIT_SYSTEM = """You are a cinematic ad quality auditor. Score the provided image/frame on 4 dimensions (0-10 each):
- visual_consistency: product colors/proportions match the reference brief
- cinematic_quality: composition, lighting, premium feel
- narrative_coherence: scene fits its place in the narrative arc
- brand_safety: no artifacts, distorted text, product deformations

Return ONLY valid JSON with keys: visual_consistency, cinematic_quality, narrative_coherence, brand_safety (all ints), rejection_reason (string or null).
Threshold for pass: all scores >= 7. If any < 7, rejection_reason must explain which dimension failed and why."""


def audit_image(image_path: Path, scene: Scene, brief: AdBrief) -> AuditResult:
    """Audit a composited scene image. Returns AuditResult."""
    logger.info("Auditing image for scene %d", scene.index)
    return _audit(image_path, scene, brief)


def audit_video(video_path: Path, scene: Scene, brief: AdBrief) -> AuditResult:
    """Audit an animated scene clip by sampling its first frame."""
    logger.info("Auditing video for scene %d", scene.index)
    frame_path = _extract_first_frame(video_path)
    return _audit(frame_path, scene, brief)


def _audit(image_path: Path, scene: Scene, brief: AdBrief) -> AuditResult:
    image_data = base64.b64encode(image_path.read_bytes()).decode()
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in ("jpg", "jpeg") else "png"

    context = (
        f"Brief — visual style: {brief.visual_style}, "
        f"product: {brief.product_description}, "
        f"dont_include: {', '.join(brief.dont_include)}.\n"
        f"Scene {scene.index} — narration: {scene.narration_line}"
    )

    response = _openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _AUDIT_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": context},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_data}"}},
            ]},
        ],
        max_tokens=300,
    )
    data = json.loads(response.choices[0].message.content)
    return AuditResult(**data)


def _extract_first_frame(video_path: Path) -> Path:
    """Extract first frame from video using ffmpeg."""
    frame_path = video_path.with_suffix(".png")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vframes", "1", str(frame_path)],
        check=True, capture_output=True,
    )
    return frame_path
