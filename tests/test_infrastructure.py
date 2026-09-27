from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.application.language_detection import window_offsets
from app.application.ports import LanguageModelError
from app.infrastructure.llm.cloud import OpenAICompatibleModel
from app.infrastructure.llm.http import parse_json_object, validated_base_url
from app.infrastructure.llm.ollama import OllamaModel, context_size_for
from app.infrastructure.separation import mdx
from app.infrastructure.separation.stft import istft, stft


def test_stft_round_trip() -> None:
    rng = np.random.default_rng(0)
    n_fft, frames = 7680, 32
    signal = rng.standard_normal((2, 2, mdx.HOP * (frames - 1))).astype(np.float32)
    spectrum = stft(signal, n_fft, mdx.HOP)
    assert spectrum.shape == (2, 2, n_fft // 2 + 1, frames)
    np.testing.assert_allclose(istft(spectrum, n_fft, mdx.HOP), signal, atol=1e-4)


def test_window_offsets() -> None:
    assert window_offsets(10, 30) == [0]
    assert window_offsets(100, 30, 3) == [0, 35, 70]


def test_context_size_grows_with_the_transcript() -> None:
    assert context_size_for("s" * 1000, "u" * 2000) == 4096
    assert context_size_for("s" * 1000, "u" * 30000) == 32768


def test_remote_apis_must_use_https() -> None:
    with pytest.raises(LanguageModelError):
        OpenAICompatibleModel("m", "key", "http://api.example.com/v1")
    assert OpenAICompatibleModel("m", "key", "http://localhost:8080/v1").base_url.startswith(
        "http://localhost"
    )


def test_invalid_urls_are_rejected() -> None:
    for url in ("ftp://host", "file:///etc/passwd", "not a url"):
        with pytest.raises(LanguageModelError):
            validated_base_url(url, require_tls_for_remote=False)
    assert OllamaModel("m", "http://127.0.0.1:11434/").url == "http://127.0.0.1:11434"


def test_json_parsing_accepts_fenced_objects_only() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("[1, 2]", "not json"):
        with pytest.raises(LanguageModelError):
            parse_json_object(bad)


def test_separation_model_download_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(url: str, target: Path, progress: object) -> None:
        target.write_bytes(b"tampered")

    monkeypatch.setattr(mdx, "_stream_to_file", fake_download)
    with pytest.raises(mdx.ModelDownloadError):
        mdx.download_model("UVR-MDX-NET-Voc_FT", tmp_path)
    assert not any(tmp_path.rglob("*.onnx"))
    assert not any(tmp_path.rglob("*.part"))


def test_unknown_separation_model_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        mdx.model_file("../../evil", tmp_path)


def test_cloud_models_require_a_model_name() -> None:
    from app.infrastructure.llm.cloud import AnthropicModel

    with pytest.raises(LanguageModelError):
        AnthropicModel("", "key")
    with pytest.raises(LanguageModelError):
        OpenAICompatibleModel("  ", "key", "https://api.example.com/v1")


def test_gui_progress_and_time_helpers() -> None:
    from app.presentation.gui.cue_table import short_time
    from app.presentation.gui.job import overall_progress

    assert overall_progress("audio", 0.0) == 0.0
    assert overall_progress("cues", 1.0) == 1.0
    assert overall_progress("translate", 0.5) == (6 + 0.5) / 8
    assert short_time(68.456) == "1:08.46"
