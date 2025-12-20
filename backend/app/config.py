from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

APP_DIR = Path(__file__).resolve().parent
INDEX_HTML = FRONTEND_DIR / "index.html"

OUTPUT_DIR = Path.home() / "Documents" / "TranscribedFiles"
TEMP_DIR = Path("/tmp") / "transcribingapp"
WHISPER_MODEL_NAME = "small.en"

FFMPEG_LOCATION = "/opt/homebrew/bin"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

__all__ = [
    "REPO_ROOT",
    "BACKEND_DIR",
    "FRONTEND_DIR",
    "APP_DIR",
    "INDEX_HTML",
    "OUTPUT_DIR",
    "TEMP_DIR",
    "WHISPER_MODEL_NAME",
    "FFMPEG_LOCATION",
]
