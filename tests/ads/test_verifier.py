from __future__ import annotations
import os
import subprocess
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from ads.verifier import pre_flight, post_validate


def test_pre_flight_fails_without_openai_key(tmp_path, monkeypatch):
    img = tmp_path / "product.jpg"
    img.write_bytes(b"fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        pre_flight(img)


def test_pre_flight_fails_without_elevenlabs_key(tmp_path, monkeypatch):
    img = tmp_path / "product.jpg"
    img.write_bytes(b"fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="ELEVENLABS_API_KEY"):
        pre_flight(img)


def test_pre_flight_fails_if_image_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-el-test")
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "hf-test")
    with patch("ads.verifier._check_ffmpeg"):
        with pytest.raises(FileNotFoundError, match="product.jpg"):
            pre_flight(tmp_path / "product.jpg")


def test_post_validate_fails_if_video_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="ad_final.mp4"):
        post_validate(tmp_path)


def test_post_validate_fails_if_brief_json_missing(tmp_path):
    (tmp_path / "ad_final.mp4").write_bytes(b"fake")
    with pytest.raises(FileNotFoundError, match="brief.json"):
        post_validate(tmp_path)
