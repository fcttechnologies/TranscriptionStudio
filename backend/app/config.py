from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

APP_DIR = Path(__file__).resolve().parent
INDEX_HTML = FRONTEND_DIR / "index.html"

OUTPUT_DIR = Path.home() / "Documents" / "SummarizedVideos"
TEMP_DIR = Path("/tmp") / "summarizevideosapp"
WHISPER_MODEL_NAME = "small.en"
OLLAMA_MODEL = "gemma3:12b"

OLLAMA = "/usr/local/bin/ollama"
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
    "OLLAMA_MODEL",
    "OLLAMA",
    "FFMPEG_LOCATION",
]
