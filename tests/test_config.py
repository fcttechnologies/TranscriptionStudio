"""Tests for the env-var-driven configuration loader."""

import importlib
import os
import sys
from pathlib import Path


def _reload_config(monkeypatch, **env):
    """Reload backend.app.config with a fresh environment for each test."""
    for key in (
        "TRANSCRIBINGAPP_TEMP_DIR",
        "WHISPER_MODEL_NAME",
        "WHISPER_DEVICE",
        "WHISPER_COMPUTE_TYPE",
        "FFMPEG_LOCATION",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("backend.app.config", None)
    return importlib.import_module("backend.app.config")


def test_defaults_use_system_temp(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch)

    assert config.WHISPER_MODEL_NAME == "base.en"
    assert config.WHISPER_DEVICE == "cpu"
    assert config.WHISPER_COMPUTE_TYPE == "int8"
    assert config.TEMP_DIR.name == "transcribingapp"


def test_temp_dir_override_creates_directory(monkeypatch, tmp_path):
    override = tmp_path / "custom-temp"
    config = _reload_config(monkeypatch, TRANSCRIBINGAPP_TEMP_DIR=str(override))

    assert config.TEMP_DIR == override
    assert override.exists() and override.is_dir()


def test_whisper_overrides(monkeypatch):
    config = _reload_config(
        monkeypatch,
        WHISPER_MODEL_NAME="small.en",
        WHISPER_DEVICE="cuda",
        WHISPER_COMPUTE_TYPE="float16",
    )

    assert config.WHISPER_MODEL_NAME == "small.en"
    assert config.WHISPER_DEVICE == "cuda"
    assert config.WHISPER_COMPUTE_TYPE == "float16"


def test_ffmpeg_location_explicit_override(monkeypatch, tmp_path):
    override = tmp_path / "ffmpeg-bin"
    override.mkdir()
    config = _reload_config(monkeypatch, FFMPEG_LOCATION=str(override))

    assert config.FFMPEG_LOCATION == str(override)


def test_ffmpeg_location_auto_detects_via_which(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    ffmpeg_path = fake_bin / "ffmpeg"
    ffmpeg_path.write_text("#!/bin/sh\nexit 0\n")
    ffmpeg_path.chmod(0o755)

    monkeypatch.setenv("PATH", str(fake_bin))
    config = _reload_config(monkeypatch)

    assert config.FFMPEG_LOCATION == str(fake_bin)


def test_repo_paths_resolve(monkeypatch):
    config = _reload_config(monkeypatch)

    assert isinstance(config.REPO_ROOT, Path)
    assert config.FRONTEND_DIR == config.REPO_ROOT / "frontend"
    assert config.BACKEND_DIR == config.REPO_ROOT / "backend"
    assert config.INDEX_HTML == config.FRONTEND_DIR / "index.html"
