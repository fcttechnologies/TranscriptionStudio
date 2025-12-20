import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import FRONTEND_DIR, INDEX_HTML, TEMP_DIR
from .jobs import (
    build_job_options,
    cleanup_old_jobs,
    create_job_record,
    jobs,
)
from .pipeline import cleanup, cleanup_startup_temp, process_job

logging.basicConfig(
    level=logging.CRITICAL,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


class JobRequest(BaseModel):
    url: str
    custom_title: Optional[str] = None
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
        mode="video",
        transcript_only=options.transcript_only,
        save_markdown=options.save_markdown,
    )
    background.add_task(process_job, job_id, options)
    return {
        "job_id": job_id,
        "mode": "video",
        "transcript_only": options.transcript_only,
        "save_markdown": options.save_markdown,
    }


@app.post("/api/start/file")
async def create_job_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    transcript_only: bool = Form(False),
    save_markdown: bool = Form(False),
    custom_title: Optional[str] = Form(None),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)

    # Security: usage of sanitize filename logic or just UUID
    # We use UUID for storage to be safe, but keep original name for labeling
    safe_name = Path(file.filename).name
    temp_path = TEMP_DIR / f"{job_id}.pdf"
    
    # 50MB Limit
    MAX_SIZE = 50 * 1024 * 1024
    size = 0
    
    try:
        with open(temp_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024): # 1MB chunks
                size += len(chunk)
                if size > MAX_SIZE:
                    temp_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File too large (max 50MB)")
                buffer.write(chunk)
    except Exception as e:
        # In case of any error during write (client disconnect etc), cleanup
        temp_path.unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="File upload failed")

    options = build_job_options(
        url=None,
        file_path=str(temp_path),
        custom_title=custom_title,
        transcript_only=transcript_only,
        save_markdown=save_markdown,
        mode="pdf",
    )
    
    real_path = TEMP_DIR / f"{job_id}_{safe_name}"
    temp_path.rename(real_path)
    options.file_path = str(real_path)

    jobs[job_id] = create_job_record(
        job_id,
        mode="pdf",
        transcript_only=options.transcript_only,
        save_markdown=options.save_markdown,
    )
    
    background.add_task(process_job, job_id, options)
    
    return {
        "job_id": job_id,
        "mode": "pdf",
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
        mode="video",
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


@app.post("/api/shortcut/start/file")
async def shortcut_start_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
):
    # Same logic as file start but hardcoded transcript_only=True
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    job_id = str(uuid.uuid4())
    cleanup_old_jobs(cleanup)

    safe_name = Path(file.filename).name
    temp_path = TEMP_DIR / f"{job_id}.pdf"
    MAX_SIZE = 50 * 1024 * 1024
    size = 0
    
    try:
        with open(temp_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024): 
                size += len(chunk)
                if size > MAX_SIZE:
                    temp_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File too large (max 50MB)")
                buffer.write(chunk)
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="File upload failed")
    
    real_path = TEMP_DIR / f"{job_id}_{safe_name}"
    temp_path.rename(real_path)

    options = build_job_options(
        url=None,
        file_path=str(real_path),
        custom_title=None,
        transcript_only=True, # Forced for Shortcut
        save_markdown=False,  # Shortcut typical usage
        mode="pdf",
    )

    jobs[job_id] = create_job_record(
        job_id,
        mode="pdf",
        transcript_only=True,
        save_markdown=False,
    )
    
    background.add_task(process_job, job_id, options)
    
    return {
        "job_id": job_id,
        "message": "Job started",
        "transcript_only": True,
        "save_markdown": False,
    }
