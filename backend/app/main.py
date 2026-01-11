"""FastAPI entry point for the transcription service."""

import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML
from .jobs import cleanup_old_jobs, create_job_record, jobs
from .pipeline import cleanup, cleanup_startup_temp, process_job


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
