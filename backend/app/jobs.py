from dataclasses import dataclass
import time
from typing import Callable, Optional

STEPS = [
    "Downloading audio",
    "Transcribing",
    "Writing markdown file",
    "Cleaning up temp files",
]

def build_steps(*, save_markdown: bool) -> list[str]:
    steps = ["Downloading audio", "Transcribing"]

    if save_markdown:
        steps.append("Writing markdown file")
    steps.append("Cleaning up temp files")
    return steps

jobs: dict[str, dict] = {}

@dataclass
class JobOptions:
    url: Optional[str]
    custom_title: Optional[str]
    save_markdown: bool


def create_job_record(
    job_id: str, *, save_markdown: bool
) -> dict:
    steps_for_job = build_steps(
        save_markdown=save_markdown
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
        "save_markdown": save_markdown,
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