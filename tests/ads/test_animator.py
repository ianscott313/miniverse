from __future__ import annotations
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from ads.animator import animate
from ads.models import Scene

SCENE = Scene(
    index=1,
    visual_prompt="Wet pavement, golden light",
    narration_line="Every step tells a story.",
    camera_motion="slow zoom in",
    duration_sec=4.0,
)


def test_animate_returns_mp4_path(tmp_path):
    image_path = tmp_path / "scene_01.png"
    image_path.write_bytes(b"fake_image")

    fake_video = tmp_path / "scene_01.mp4"
    fake_video.write_bytes(b"fake_video")

    with patch.dict(os.environ, {"HIGGSFIELD_API_KEY": "test-key"}), \
         patch("ads.animator._upload_image") as mock_upload, \
         patch("ads.animator._submit_job") as mock_submit, \
         patch("ads.animator._poll_job") as mock_poll, \
         patch("ads.animator._download_video") as mock_download:
        mock_upload.return_value = "media-uuid-123"
        mock_submit.return_value = "job-id-456"
        mock_poll.return_value = "https://cdn.higgsfield.ai/video.mp4"
        mock_download.return_value = fake_video

        result = animate(image_path, SCENE, tmp_path)

    assert result == fake_video
    assert result.suffix == ".mp4"


def test_animate_raises_on_upload_failure(tmp_path):
    image_path = tmp_path / "scene_01.png"
    image_path.write_bytes(b"fake_image")

    with patch.dict(os.environ, {"HIGGSFIELD_API_KEY": "test-key"}), \
         patch("ads.animator._upload_image") as mock_upload:
        mock_upload.side_effect = RuntimeError("Upload failed: 401 Unauthorized")
        with pytest.raises(RuntimeError, match="Upload failed"):
            animate(image_path, SCENE, tmp_path)
