from __future__ import annotations
import json
import logging
import os

from openai import OpenAI

from ads.models import AdBrief, Scene

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

_STORYBOARD_PROMPT = """You are a cinematographer writing a shot-by-shot storyboard for a cinematic product ad.
Given the AdBrief, generate exactly {num_scenes} scenes.
Return ONLY a valid JSON array where each element has:
- index (int, 1-based)
- visual_prompt (string: detailed visual description for image generation, include lighting, mood, composition; do NOT include the product itself — it will be composited in)
- narration_line (string: voiceover line for this scene, max 12 words)
- camera_motion (string: one of "slow zoom in", "slow zoom out", "left pan", "right pan", "dolly forward", "dolly back", "static")
- duration_sec (float: 3.0-5.0)
Follow the narrative_arc. The first scene is the hook, the last is the CTA with the tagline.
NEVER include: {dont_include}
No markdown, no explanation, just the JSON array."""


def generate(brief: AdBrief, num_scenes: int = 7) -> list[Scene]:
    """Generate a storyboard of `num_scenes` scenes from the AdBrief."""
    logger.info("Generating storyboard: %d scenes for '%s'", num_scenes, brief.hero_message)
    system = _STORYBOARD_PROMPT.format(
        num_scenes=num_scenes,
        dont_include=", ".join(brief.dont_include) or "nothing specific",
    )
    context = (
        f"Visual style: {brief.visual_style}\n"
        f"Color palette: {', '.join(brief.color_palette)}\n"
        f"Hero message: {brief.hero_message}\n"
        f"Narrative arc: {brief.narrative_arc}\n"
        f"Tagline: {brief.tagline}\n"
        f"Product: {brief.product_description}"
    )
    response = _openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ],
        max_tokens=1500,
    )
    scenes_data = json.loads(response.choices[0].message.content)
    return [Scene(**s) for s in scenes_data]
