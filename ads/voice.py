from __future__ import annotations
import logging
import os
from pathlib import Path

import requests

from ads.models import AdBrief, Scene

logger = logging.getLogger(__name__)

_API_BASE = "https://api.elevenlabs.io/v1"

_VOICE_MAP = {
    "confident male EN": "pNInz6obpgDQGcFmaJgB",   # Adam
    "warm female EN": "EXAVITQu4vr4xnSDxMaL",       # Bella
    "confident male ES": "VR6AewLTigWG4xSOukaG",    # Arnold
    "warm female ES": "ThT5KcBeYPX3keUQqHPh",       # Dorothy
}
_DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"


def synthesize_scene(scene: Scene, brief: AdBrief, output_dir: Path) -> Path:
    """Synthesize narration for a single scene. Returns .mp3 path."""
    voice_id = _get_voice_id(brief.voice_tone)
    logger.info("Synthesizing voice for scene %d: '%s'", scene.index, scene.narration_line)
    audio = _elevenlabs_tts(scene.narration_line, voice_id)
    out = output_dir / f"scene_{scene.index:02d}_voice.mp3"
    out.write_bytes(audio)
    return out


def synthesize_tagline(brief: AdBrief, output_dir: Path) -> Path:
    """Synthesize the final tagline voiceover. Returns .mp3 path."""
    voice_id = _get_voice_id(brief.voice_tone)
    logger.info("Synthesizing tagline: '%s'", brief.tagline)
    audio = _elevenlabs_tts(brief.tagline, voice_id)
    out = output_dir / "tagline_voice.mp3"
    out.write_bytes(audio)
    return out


def _get_voice_id(voice_tone: str) -> str:
    return _VOICE_MAP.get(voice_tone, _DEFAULT_VOICE_ID)


def _elevenlabs_tts(text: str, voice_id: str) -> bytes:
    api_key = os.environ["ELEVENLABS_API_KEY"]
    response = requests.post(
        f"{_API_BASE}/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"ElevenLabs TTS failed: {response.status_code} {response.text}")
    return response.content
