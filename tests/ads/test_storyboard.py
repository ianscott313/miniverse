from __future__ import annotations
import json
from unittest.mock import patch, MagicMock
from ads.storyboard import generate
from ads.models import AdBrief, Scene

BRIEF = AdBrief(
    product_description="white sneakers",
    hero_message="Move without limits",
    narrative_arc="hook → development → CTA",
    visual_style="golden hour lifestyle",
    color_palette=["#FFFFFF", "#FFD700"],
    mood_music="uplifting pop",
    voice_tone="confident male EN",
    dont_include=["busy backgrounds"],
    tagline="Move Without Limits",
)

FAKE_SCENES_JSON = json.dumps([
    {
        "index": 1,
        "visual_prompt": "Close-up of white sneaker on wet pavement, golden hour light",
        "narration_line": "Every step tells a story.",
        "camera_motion": "slow zoom in",
        "duration_sec": 4.0,
    },
    {
        "index": 2,
        "visual_prompt": "Athlete lacing sneakers in stadium tunnel",
        "narration_line": "Where limits are just the beginning.",
        "camera_motion": "dolly forward",
        "duration_sec": 4.5,
    },
])


def test_generate_returns_scenes():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = FAKE_SCENES_JSON

    with patch("ads.storyboard._openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        scenes = generate(BRIEF, num_scenes=2)

    assert len(scenes) == 2
    assert all(isinstance(s, Scene) for s in scenes)
    assert scenes[0].index == 1
    assert scenes[1].camera_motion == "dolly forward"


def test_generate_respects_dont_include():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = FAKE_SCENES_JSON

    with patch("ads.storyboard._openai_client") as mock_client:
        call_args = {}
        def capture(*args, **kwargs):
            call_args["messages"] = kwargs.get("messages", [])
            return mock_response
        mock_client.chat.completions.create.side_effect = capture
        generate(BRIEF, num_scenes=2)

    prompt_text = str(call_args["messages"])
    assert "busy backgrounds" in prompt_text
