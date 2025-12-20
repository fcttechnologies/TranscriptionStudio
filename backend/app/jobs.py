from dataclasses import dataclass
import time
from typing import Callable, Optional

STEPS = [
    "Downloading audio",
    "Transcribing",
    "Summarizing",
    "Writing markdown file",
    "Cleaning up temp files",
]

PDF_STEPS = [
    "Extracting text",
    "Cleaning text",
    "Summarizing",
    "Writing markdown file",
    "Cleaning up temp files",
]


def build_steps(*, mode: str, transcript_only: bool, save_markdown: bool) -> list[str]:
    if mode == "pdf":
        steps = ["Extracting text", "Cleaning text"]
    else:
        steps = ["Downloading audio", "Transcribing"]

    if not transcript_only:
        steps.append("Summarizing")
    if save_markdown:
        steps.append("Writing markdown file")
    steps.append("Cleaning up temp files")
    return steps


jobs: dict[str, dict] = {}


@dataclass
class JobOptions:
    url: Optional[str]
    file_path: Optional[str]
    custom_title: Optional[str]
    transcript_only: bool
    save_markdown: bool
    mode: str = "video"  # "video" or "pdf"


def create_job_record(
    job_id: str, *, mode: str, transcript_only: bool, save_markdown: bool
) -> dict:
    steps_for_job = build_steps(
        mode=mode, transcript_only=transcript_only, save_markdown=save_markdown
    )
    return {
        "job_id": job_id,
        "state": "running",
        "stage_text": "Queued…",
        "progress": 2,
        "error": None,
        "file_path": None,
        "clipboard_payload": None,
        "steps": steps_for_job,
        "active_step_index": 0,
        "created_at": time.time(),
        "transcript_only": transcript_only,
        "save_markdown": save_markdown,
        "mode": mode,
    }


def set_job(job_id: str, **updates):
    if job_id not in jobs:
        return
    jobs[job_id].update(updates)


def set_step(job_id: str, idx: int, text: str, progress: int):
    if job_id not in jobs:
        return
    step_list = jobs.get(job_id, {}).get("steps", STEPS)
    set_job(job_id, active_step_index=idx, stage_text=text, progress=progress, steps=step_list)


def step_index(job_id: str, label: str) -> int:
    steps = jobs.get(job_id, {}).get("steps", STEPS)
    try:
        return steps.index(label)
    except ValueError:
        return max(len(steps) - 1, 0)


def cleanup_old_jobs(cleanup_fn: Callable[[str], None], *, retention_seconds: int = 86400):
    now = time.time()
    for jid in list(jobs.keys()):
        job = jobs[jid]
        created_at = job.get("created_at", 0)
        state = job.get("state", "running")
        if (now - created_at > retention_seconds) and (state in ["done", "error"]):
            cleanup_fn(jid)
            del jobs[jid]


def build_job_options(
    *,
    url: Optional[str] = None,
    file_path: Optional[str] = None,
    custom_title: Optional[str],
    transcript_only: bool,
    save_markdown: bool,
    mode: str = "video",
) -> JobOptions:
    return JobOptions(
        url=(url or "").strip() if url else None,
        file_path=file_path,
        custom_title=(custom_title or None),
        transcript_only=bool(transcript_only),
        save_markdown=bool(save_markdown),
        mode=mode,
    )
