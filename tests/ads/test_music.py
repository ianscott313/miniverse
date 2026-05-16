from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from ads.music import fetch

FAKE_PIXABAY_HIT = {
    "id": 123,
    "title": "Epic Cinematic",
    "audio": "https://cdn.pixabay.com/audio/123/epic.mp3",
}


def test_fetch_returns_normalized_mp3(tmp_path):
    fake_raw = tmp_path / "music_raw.mp3"
    fake_raw.write_bytes(b"fakemp3")
    normalized = tmp_path / "music.mp3"
    normalized.write_bytes(b"normalizedmp3")

    with patch("ads.music._search_pixabay") as mock_search, \
         patch("ads.music._download_track") as mock_dl, \
         patch("ads.music._normalize_audio") as mock_norm:
        mock_search.return_value = FAKE_PIXABAY_HIT
        mock_dl.return_value = fake_raw
        mock_norm.return_value = normalized

        result = fetch("uplifting pop", tmp_path)

    assert result.suffix == ".mp3"
    assert result == normalized


def test_fetch_raises_if_no_results(tmp_path):
    with patch("ads.music._search_pixabay") as mock_search:
        mock_search.return_value = None
        with pytest.raises(RuntimeError, match="No music found"):
            fetch("uplifting pop", tmp_path)
