from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock
from ads.voice import synthesize_scene, synthesize_tagline
from ads.models import AdBrief, Scene

BRIEF = AdBrief(
    product_description="white sneakers",
    hero_message="Move without limits",
    narrative_arc="hook → CTA",
    visual_style="golden hour lifestyle",
    color_palette=["#FFFFFF"],
    mood_music="uplifting pop",
    voice_tone="confident male EN",
    dont_include=[],
    tagline="Move Without Limits",
)

SCENE = Scene(
    index=1,
    visual_prompt="Wet pavement",
    narration_line="Every step tells a story.",
    camera_motion="slow zoom in",
    duration_sec=4.0,
)


def test_synthesize_scene_returns_audio_path(tmp_path):
    with patch("ads.voice._get_voice_id") as mock_voice_id, \
         patch("ads.voice._elevenlabs_tts") as mock_tts:
        mock_voice_id.return_value = "voice-id-abc"
        mock_tts.return_value = b"fakeaudiobytes"
        result = synthesize_scene(SCENE, BRIEF, tmp_path)

    assert result.exists()
    assert result.suffix == ".mp3"
    assert "scene_01" in result.name


def test_synthesize_tagline_returns_audio_path(tmp_path):
    with patch("ads.voice._get_voice_id") as mock_voice_id, \
         patch("ads.voice._elevenlabs_tts") as mock_tts:
        mock_voice_id.return_value = "voice-id-abc"
        mock_tts.return_value = b"fakeaudiobytes"
        result = synthesize_tagline(BRIEF, tmp_path)

    assert result.exists()
    assert "tagline" in result.name
