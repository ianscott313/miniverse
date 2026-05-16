from __future__ import annotations
import base64
import json
import logging
import os
from pathlib import Path

from openai import OpenAI

from ads.models import AdBrief

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

_ANALYZE_PROMPT = """You are a creative director analyzing a product photo.
Return ONLY valid JSON with these keys:
- product: short product name
- dominant_colors: list of 3-5 color names
- style: visual style descriptor (e.g. "minimalist athletic")
- probable_audience: demographic description
- suggested_mood: mood/energy descriptor
No markdown, no explanation, just the JSON object."""

_BRIEF_PROMPT = """You are a world-class creative director writing a cinematic ad brief.
Given the product analysis and user answers, return ONLY valid JSON with:
- product_description (string)
- hero_message (string)
- narrative_arc (string describing 3 acts: hook → development → CTA)
- visual_style (string, e.g. "neon noir", "golden hour lifestyle")
- color_palette (list of 3-5 hex codes matching the product)
- mood_music (string, e.g. "cinematic tension", "uplifting pop")
- voice_tone (string, e.g. "confident male EN", "warm female ES")
- dont_include (list of strings)
- tagline (string, memorable final phrase)
No markdown, no explanation, just the JSON object."""


def analyze(image_path: Path) -> dict:
    """Send product image to GPT-4o Vision and extract product characteristics."""
    image_data = base64.b64encode(image_path.read_bytes()).decode()
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix

    logger.info("Analyzing product image: %s", image_path.name)
    response = _openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _ANALYZE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_data}"}},
            ],
        }],
        max_tokens=500,
    )
    return json.loads(response.choices[0].message.content)


def run_wizard(analysis: dict) -> dict:
    """Interactive CLI wizard — asks 5 creative direction questions."""
    print("\n" + "="*60)
    print("CREATIVE DIRECTOR — Brief Wizard")
    print("="*60)
    print(f"\nProduct detected: {analysis['product']}")
    print(f"Style: {analysis['style']}")
    print(f"Suggested mood: {analysis['suggested_mood']}\n")

    questions = [
        ("hero_message", "What is the ONE message that must stay in the viewer's mind?"),
        ("references", "Any visual references? (brand, film, other ad) — press Enter to skip:"),
        ("dont_include", "What should NEVER appear? (styles, elements, colors to avoid):"),
        ("audience", "Who is the target audience? (age, gender, context):"),
        ("emotion", "What emotion should the ad provoke? (desire, trust, urgency, inspiration):"),
    ]

    answers = {}
    for key, question in questions:
        print(f"\n→ {question}")
        answers[key] = input("  > ").strip()

    return answers


def generate_brief(analysis: dict, wizard_answers: dict) -> AdBrief:
    """Generate the full AdBrief from analysis + wizard answers using GPT-4o."""
    context = (
        f"Product analysis: {json.dumps(analysis)}\n"
        f"User answers: {json.dumps(wizard_answers)}"
    )
    logger.info("Generating AdBrief with GPT-4o")
    response = _openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _BRIEF_PROMPT},
            {"role": "user", "content": context},
        ],
        max_tokens=800,
    )
    data = json.loads(response.choices[0].message.content)
    return AdBrief(**data)


def present_and_confirm_brief(brief: AdBrief) -> AdBrief:
    """Show the brief to the user and allow field-by-field editing."""
    import dataclasses

    print("\n" + "="*60)
    print("GENERATED BRIEF — review and edit (press Enter to keep)")
    print("="*60)

    updates = {}
    for f in dataclasses.fields(brief):
        current = getattr(brief, f.name)
        print(f"\n{f.name}: {current}")
        new_val = input("  Edit (or Enter to keep): ").strip()
        if new_val:
            if isinstance(current, list):
                updates[f.name] = [v.strip() for v in new_val.split(",")]
            else:
                updates[f.name] = new_val

    if updates:
        return dataclasses.replace(brief, **updates)
    return brief
