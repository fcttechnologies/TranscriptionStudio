import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML
from .jobs import (
    build_job_options,
    cleanup_old_jobs,
    create_job_record,
    jobs,
)
from .pipeline import cleanup, cleanup_startup_temp, process_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


class JobRequest(BaseModel):
    url: str
    custom_title: str | None = None
    transcript_only: bool = False
    save_markdown: bool = False


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


@app.post("/api/start/url")
def create_job(req: JobRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)
    options = build_job_options(
        url=req.url,
        custom_title=req.custom_title,
        transcript_only=req.transcript_only,
        save_markdown=req.save_markdown,
    )
    jobs[job_id] = create_job_record(
        job_id,
        transcript_only=options.transcript_only,
        save_markdown=options.save_markdown,
    )
    background.add_task(process_job, job_id, options)
    return {
        "job_id": job_id,
        "transcript_only": options.transcript_only,
        "save_markdown": options.save_markdown,
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return jobs.get(job_id, {"state": "error", "error": "Job not found"})


@app.post("/api/shortcut/start/url")
def shortcut_start(req: JobRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)
    options = build_job_options(
        url=req.url,
        custom_title=req.custom_title,
        transcript_only=True,
        save_markdown=req.save_markdown,
    )

    jobs[job_id] = create_job_record(
        job_id,
        transcript_only=options.transcript_only,
        save_markdown=options.save_markdown,
    )
    background.add_task(process_job, job_id, options)

    return {
        "job_id": job_id,
        "message": "Job started",
        "transcript_only": options.transcript_only,
        "save_markdown": options.save_markdown,
    }
