from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from ads.auditor import audit_image, audit_video
from ads.models import AdBrief, Scene, AuditResult

BRIEF = AdBrief(
    product_description="white sneakers",
    hero_message="Move without limits",
    narrative_arc="hook → CTA",
    visual_style="golden hour lifestyle",
    color_palette=["#FFFFFF", "#FFD700"],
    mood_music="uplifting pop",
    voice_tone="confident male EN",
    dont_include=["busy backgrounds"],
    tagline="Move Without Limits",
)

SCENE = Scene(
    index=1,
    visual_prompt="Wet pavement, golden light",
    narration_line="Every step tells a story.",
    camera_motion="slow zoom in",
    duration_sec=4.0,
)

PASS_SCORES = json.dumps({
    "visual_consistency": 9,
    "cinematic_quality": 8,
    "narrative_coherence": 9,
    "brand_safety": 10,
    "rejection_reason": None,
})

FAIL_SCORES = json.dumps({
    "visual_consistency": 5,
    "cinematic_quality": 8,
    "narrative_coherence": 9,
    "brand_safety": 10,
    "rejection_reason": "Product colors inconsistent with reference photo",
})


def test_audit_image_returns_pass(tmp_path):
    img = tmp_path / "scene_01.png"
    img.write_bytes(b"fake")
    mock_response = MagicMock()
    mock_response.choices[0].message.content = PASS_SCORES

    with patch("ads.auditor._openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        result = audit_image(img, SCENE, BRIEF)

    assert isinstance(result, AuditResult)
    assert result.passed is True


def test_audit_image_returns_fail_with_reason(tmp_path):
    img = tmp_path / "scene_01.png"
    img.write_bytes(b"fake")
    mock_response = MagicMock()
    mock_response.choices[0].message.content = FAIL_SCORES

    with patch("ads.auditor._openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        result = audit_image(img, SCENE, BRIEF)

    assert result.passed is False
    assert "inconsistent" in result.rejection_reason
