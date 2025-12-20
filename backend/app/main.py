import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML, TEMP_DIR
from .jobs import (
    cleanup_old_jobs,
    create_job_record,
    jobs,
)
from .pipeline import cleanup, cleanup_startup_temp, process_job


class JobRequest(BaseModel):
    url: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_startup_temp()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    if not INDEX_HTML.exists():
        return HTMLResponse("Missing index.html", status_code=500)
    return FileResponse(INDEX_HTML)


@app.post("/api/jobs/start")
def create_job(req: JobRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)

    url = (req.url or "").strip() if req.url else None

    jobs[job_id] = create_job_record(job_id)
    background.add_task(process_job, job_id, url)

    return {
        "job_id": job_id,
        "message": "Job started",
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return jobs.get(job_id, {"state": "error", "error": "Job not found"})