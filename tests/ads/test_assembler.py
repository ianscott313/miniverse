from __future__ import annotations
from pathlib import Path
from unittest.mock import patch
from ads.assembler import assemble
from ads.models import AdBrief, Scene, SceneAsset, AdOutput

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


def _make_assets(tmp_path: Path, n: int) -> list[SceneAsset]:
    assets = []
    for i in range(1, n + 1):
        scene = Scene(index=i, visual_prompt="", narration_line="", camera_motion="static", duration_sec=4.0)
        img = tmp_path / f"scene_{i:02d}.png"; img.write_bytes(b"img")
        vid = tmp_path / f"scene_{i:02d}.mp4"; vid.write_bytes(b"vid")
        aud = tmp_path / f"scene_{i:02d}_voice.mp3"; aud.write_bytes(b"aud")
        assets.append(SceneAsset(scene=scene, image_path=img, video_path=vid, audio_path=aud))
    return assets


def test_assemble_returns_ad_output(tmp_path):
    assets = _make_assets(tmp_path, 2)
    music = tmp_path / "music.mp3"; music.write_bytes(b"music")
    final = tmp_path / "ad_final.mp4"; final.write_bytes(b"final")

    with patch("ads.assembler._merge_scene_audio_video") as mock_merge, \
         patch("ads.assembler._concatenate_scenes") as mock_concat, \
         patch("ads.assembler._mix_music") as mock_mix, \
         patch("ads.assembler._add_tagline_title") as mock_title, \
         patch("ads.assembler._get_duration") as mock_dur:
        mock_merge.side_effect = lambda asset, d: d / f"scene_{asset.scene.index:02d}_merged.mp4"
        mock_concat.return_value = tmp_path / "ad_no_music.mp4"
        mock_mix.return_value = tmp_path / "ad_with_music.mp4"
        mock_title.return_value = final
        mock_dur.return_value = 45.0

        result = assemble(assets, music, BRIEF, tmp_path)

    assert isinstance(result, AdOutput)
    assert result.final_video_path == final
    assert result.duration_sec == 45.0
    assert len(result.assets) == 2
    assert (tmp_path / "brief.json").exists()
