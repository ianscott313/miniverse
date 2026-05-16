from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AdBrief:
    product_description: str
    hero_message: str
    narrative_arc: str
    visual_style: str
    color_palette: list[str]
    mood_music: str
    voice_tone: str
    dont_include: list[str]
    tagline: str


@dataclass
class Scene:
    index: int
    visual_prompt: str
    narration_line: str
    camera_motion: str
    duration_sec: float


@dataclass
class SceneAsset:
    scene: Scene
    image_path: Path
    video_path: Path
    audio_path: Path


@dataclass
class AdOutput:
    brief: AdBrief
    assets: list[SceneAsset]
    music_path: Path
    final_video_path: Path
    duration_sec: float


@dataclass
class AuditResult:
    visual_consistency: int
    cinematic_quality: int
    narrative_coherence: int
    brand_safety: int
    rejection_reason: str | None = None

    @property
    def passed(self) -> bool:
        return all(
            score >= 7
            for score in [
                self.visual_consistency,
                self.cinematic_quality,
                self.narrative_coherence,
                self.brand_safety,
            ]
        )
