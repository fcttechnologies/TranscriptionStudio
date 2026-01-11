"""Central configuration for filesystem paths and Whisper settings."""

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
# Adjust this path if you need a different storage location.
TEMP_DIR = Path("/tmp") / "transcribingapp"

# Default Whisper model to load; change if you want a different size/quality.
WHISPER_MODEL_NAME = "small.en"

# Location of the ffmpeg binary used by yt-dlp/Whisper.
FFMPEG_LOCATION = "/opt/homebrew/bin"

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
    "FFMPEG_LOCATION",
]
