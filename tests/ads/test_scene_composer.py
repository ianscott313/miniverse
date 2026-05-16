from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from ads.scene_composer import compose
from ads.models import AdBrief, Scene

BRIEF = AdBrief(
    product_description="white sneakers",
    hero_message="Move without limits",
    narrative_arc="hook → CTA",
    visual_style="golden hour lifestyle",
    color_palette=["#FFFFFF", "#FFD700"],
    mood_music="uplifting pop",
    voice_tone="confident male EN",
    dont_include=[],
    tagline="Move Without Limits",
)

SCENE = Scene(
    index=1,
    visual_prompt="Wet pavement reflecting golden light, urban setting",
    narration_line="Every step tells a story.",
    camera_motion="slow zoom in",
    duration_sec=4.0,
)


def test_compose_returns_image_path(tmp_path):
    product_img = tmp_path / "product.png"
    from PIL import Image
    Image.new("RGB", (400, 400), color=(255, 255, 255)).save(product_img)

    fake_bg = tmp_path / "bg.png"
    Image.new("RGB", (1920, 1080), color=(100, 100, 100)).save(fake_bg)

    with patch("ads.scene_composer._generate_background") as mock_gen, \
         patch("ads.scene_composer._remove_background") as mock_rembg:
        mock_gen.return_value = fake_bg
        mock_rembg.return_value = product_img
        result = compose(SCENE, BRIEF, product_img, tmp_path)

    assert result.exists()
    assert result.suffix == ".png"
    assert "scene_01" in result.name
