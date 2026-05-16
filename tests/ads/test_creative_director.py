from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from ads.creative_director import analyze, generate_brief
from ads.models import AdBrief


FAKE_ANALYSIS = {
    "product": "white leather sneakers",
    "dominant_colors": ["white", "cream", "silver"],
    "style": "minimalist athletic",
    "probable_audience": "young adults 18-35, fitness-oriented",
    "suggested_mood": "energetic and aspirational",
}

FAKE_BRIEF_JSON = json.dumps({
    "product_description": "white leather sneakers",
    "hero_message": "Move without limits",
    "narrative_arc": "hook: athlete struggling → development: wearing shoes → CTA: buy now",
    "visual_style": "golden hour lifestyle",
    "color_palette": ["#FFFFFF", "#FFD700", "#1A1A1A"],
    "mood_music": "uplifting pop",
    "voice_tone": "confident male EN",
    "dont_include": ["busy backgrounds"],
    "tagline": "Move Without Limits",
})


def test_analyze_returns_dict(tmp_path):
    img = tmp_path / "product.jpg"
    img.write_bytes(b"fakeimagebytes")

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(FAKE_ANALYSIS)

    with patch("ads.creative_director._openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        result = analyze(img)

    assert result["product"] == "white leather sneakers"
    assert "dominant_colors" in result


def test_generate_brief_returns_ad_brief():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = FAKE_BRIEF_JSON

    wizard_answers = {
        "hero_message": "Move without limits",
        "references": "Nike Just Do It campaign",
        "dont_include": "busy backgrounds",
        "audience": "young adults 18-35",
        "emotion": "inspiration",
    }

    with patch("ads.creative_director._openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        brief = generate_brief(FAKE_ANALYSIS, wizard_answers)

    assert isinstance(brief, AdBrief)
    assert brief.tagline == "Move Without Limits"
    assert len(brief.color_palette) == 3
