from __future__ import annotations
from pathlib import Path
from ads.models import AdBrief, Scene, SceneAsset, AdOutput, AuditResult


def test_ad_brief_fields():
    brief = AdBrief(
        product_description="white leather sneakers",
        hero_message="Move without limits",
        narrative_arc="hook: athlete struggling → development: wearing shoes → CTA: buy now",
        visual_style="golden hour lifestyle",
        color_palette=["#FFFFFF", "#FFD700", "#1A1A1A"],
        mood_music="uplifting pop",
        voice_tone="confident male EN",
        dont_include=["busy backgrounds", "text overlays"],
        tagline="Move Without Limits",
    )
    assert brief.product_description == "white leather sneakers"
    assert len(brief.color_palette) == 3
    assert brief.tagline == "Move Without Limits"


def test_scene_defaults():
    scene = Scene(
        index=1,
        visual_prompt="Close-up of sneaker sole on wet pavement",
        narration_line="Every step tells a story.",
        camera_motion="slow zoom in",
        duration_sec=4.0,
    )
    assert scene.index == 1
    assert scene.duration_sec == 4.0


def test_audit_result_pass():
    result = AuditResult(
        visual_consistency=8,
        cinematic_quality=9,
        narrative_coherence=8,
        brand_safety=10,
        rejection_reason=None,
    )
    assert result.passed is True


def test_audit_result_fail_below_threshold():
    result = AuditResult(
        visual_consistency=6,
        cinematic_quality=9,
        narrative_coherence=8,
        brand_safety=10,
        rejection_reason="Product colors inconsistent with reference",
    )
    assert result.passed is False
    assert result.rejection_reason is not None
