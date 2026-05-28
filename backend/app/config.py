"""Central configuration for filesystem paths and Whisper settings.

All values can be overridden with environment variables of the same name,
making the app portable across macOS, Linux, and Windows without code edits.
"""

import os
import shutil
import tempfile
from pathlib import Path

# Resolve the repository root from this file's location so relative paths
# remain stable no matter where the server is launched.
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

# App-specific paths are derived from the repo root for consistency.
APP_DIR = Path(__file__).resolve().parent
INDEX_HTML = FRONTEND_DIR / "index.html"

# Temporary files used during download/transcription are stored here.
# Override with TRANSCRIBINGAPP_TEMP_DIR if you need a different location.
TEMP_DIR = Path(
    os.environ.get("TRANSCRIBINGAPP_TEMP_DIR", str(Path(tempfile.gettempdir()) / "transcribingapp"))
)

# Default Faster-Whisper model to load; tune size for quality vs speed/RAM.
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL_NAME", "base.en")

# Faster-Whisper runtime settings.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

# Standard Python logging level. Accepts DEBUG, INFO, WARNING, ERROR, CRITICAL.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Location of the ffmpeg binary used by yt-dlp/audio processing.
# Auto-detect via PATH; fall back to common system locations; allow override.
def _detect_ffmpeg_location() -> str:
    override = os.environ.get("FFMPEG_LOCATION")
    if override:
        return override
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    for candidate in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if Path(candidate, "ffmpeg").exists():
            return candidate
    return ""  # Empty string lets yt-dlp fall back to PATH-only resolution.


FFMPEG_LOCATION = _detect_ffmpeg_location()

# Ensure the temp directory exists before any job runs.
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Exported names for other modules to import.
__all__ = [
    "REPO_ROOT",
    "BACKEND_DIR",
    "FRONTEND_DIR",
    "APP_DIR",
    "INDEX_HTML",
    "TEMP_DIR",
    "WHISPER_MODEL_NAME",
    "WHISPER_DEVICE",
    "WHISPER_COMPUTE_TYPE",
    "FFMPEG_LOCATION",
    "LOG_LEVEL",
]
