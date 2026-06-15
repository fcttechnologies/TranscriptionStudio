"""FastAPI entry point for the transcription service."""

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML, LOG_LEVEL, TEMP_DIR
from .jobs import cleanup_old_jobs, create_job_record, jobs
from .pipeline import cleanup, cleanup_startup_temp, process_job, transcribe

# Configure root logging once at import time so child loggers inherit the level.
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger(__name__)

# Whitelist of audio/video extensions allowed for the direct-upload endpoint.
# Anything else falls back to ".audio" so we never write a hostile suffix.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac",
    ".opus", ".aac", ".webm", ".mov", ".mkv",
}
CONTENT_TYPE_FALLBACKS = {
    "ogg": ".ogg",
    "mp4": ".mp4",
    "m4a": ".m4a",
    "mp3": ".mp3",
    "wav": ".wav",
    "webm": ".webm",
    "flac": ".flac",
}


class JobRequest(BaseModel):
    """Expected payload when a client starts a new transcription job."""

    url: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup housekeeping to clear temp files."""
    cleanup_startup_temp()
    logger.info("Transcription Studio ready", extra={"temp_dir": str(TEMP_DIR)})
    yield


# Initialize the FastAPI app and mount the static frontend.
app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _resolve_upload_extension(filename: str | None, content_type: str | None) -> str:
    """Pick a safe file extension for an uploaded blob."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in ALLOWED_UPLOAD_EXTENSIONS:
            return suffix
    ctype = (content_type or "").lower()
    for hint, ext in CONTENT_TYPE_FALLBACKS.items():
        if hint in ctype:
            return ext
    return ".audio"


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the single-page application."""
    if not INDEX_HTML.exists():
        return HTMLResponse("Missing index.html", status_code=500)
    return FileResponse(INDEX_HTML)


@app.post("/api/jobs/start")
def create_job(req: JobRequest, background: BackgroundTasks) -> dict[str, str]:
    """Start a new transcription job and run it in the background."""
    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)

    # Normalize the URL to avoid empty or whitespace-only submissions.
    url = (req.url or "").strip()

    # Store the job record and kick off the async processing pipeline.
    jobs[job_id] = create_job_record(job_id)
    background.add_task(process_job, job_id, url)
    logger.info("Job queued", extra={"job_id": job_id})

    return {
        "job_id": job_id,
        "message": "Job started",
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Fetch the latest job status for polling clients."""
    return jobs.get(job_id, {"state": "error", "error": "Job not found"})


@app.post("/api/transcribe/file")
async def transcribe_file(file: UploadFile = File(...)):
    """Accept audio file upload and transcribe immediately."""
    job_id = str(uuid.uuid4())
    ext = _resolve_upload_extension(file.filename, file.content_type)
    temp_path = TEMP_DIR / f"{job_id}{ext}"

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        transcript = transcribe(job_id, temp_path)

        return {
            "job_id": job_id,
            "transcript": transcript,
            "filename": file.filename,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("File transcription failed", extra={"job_id": job_id})
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "job_id": job_id},
        )

    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:  # noqa: BLE001
            logger.debug("Unable to delete upload temp file", extra={"path": str(temp_path)})
