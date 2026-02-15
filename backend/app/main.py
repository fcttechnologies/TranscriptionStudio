"""FastAPI entry point for the transcription service."""

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML, TEMP_DIR
from .jobs import cleanup_old_jobs, create_job_record, jobs
from .pipeline import cleanup, cleanup_startup_temp, process_job, transcribe


class JobRequest(BaseModel):
    """Expected payload when a client starts a new transcription job."""

    url: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup housekeeping to clear temp files."""
    cleanup_startup_temp()
    yield


# Initialize the FastAPI app and mount the static frontend.
app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the single-page application."""
    if not INDEX_HTML.exists():
        return HTMLResponse("Missing index.html", status_code=500)
    return FileResponse(INDEX_HTML)


@app.post("/api/jobs/start")
def create_job(req: JobRequest, background: BackgroundTasks):
    """Start a new transcription job and run it in the background."""
    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)

    # Normalize the URL to avoid empty or whitespace-only submissions.
    url = (req.url or "").strip() if req.url else None

    # Store the job record and kick off the async processing pipeline.
    jobs[job_id] = create_job_record(job_id)
    background.add_task(process_job, job_id, url)

    return {
        "job_id": job_id,
        "message": "Job started",
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Fetch the latest job status for polling clients."""
    return jobs.get(job_id, {"state": "error", "error": "Job not found"})


@app.post("/api/transcribe/file")
async def transcribe_file(file: UploadFile = File(...)):
    """Accept audio file upload and transcribe immediately."""
    # Generate unique job_id for temp file tracking
    job_id = str(uuid.uuid4())
    
    # Determine file extension from original filename or content-type
    ext = Path(file.filename).suffix if file.filename else ".audio"
    if not ext or ext == ".audio":
        # Try to infer from content-type
        content_type = file.content_type or ""
        if "ogg" in content_type:
            ext = ".ogg"
        elif "mp4" in content_type:
            ext = ".mp4"
        elif "m4a" in content_type:
            ext = ".m4a"
        elif "mp3" in content_type:
            ext = ".mp3"
        else:
            ext = ".audio"
    
    temp_path = TEMP_DIR / f"{job_id}{ext}"
    
    try:
        # Save uploaded file to temp
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Run transcription directly
        transcript = transcribe(job_id, temp_path)
        
        return {
            "job_id": job_id,
            "transcript": transcript,
            "filename": file.filename,
        }
    
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "job_id": job_id}
        )
    
    finally:
        # Cleanup temp file
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
