"""In-memory job tracking for the transcription pipeline."""

import time
from typing import Callable

# Ordered list of stages displayed in the UI.
STEPS = [
    "Downloading audio",
    "Transcribing",
    "Cleaning up temp files",
]

# Simple in-memory job store. This resets on server restart.
jobs: dict[str, dict] = {}


def create_job_record(job_id: str) -> dict:
    """Create the initial job payload returned to the UI."""
    steps_for_job = STEPS
    return {
        "job_id": job_id,
        "state": "running",
        "stage_text": "Queued…",
        "progress": 2,
        "error": None,
        "transcript": None,
        "steps": steps_for_job,
        "active_step_index": 0,
        "created_at": time.time(),
    }


def set_job(job_id: str, **updates) -> None:
    """Update a job record in place, if it exists."""
    if job_id not in jobs:
        return
    jobs[job_id].update(updates)


def set_step(job_id: str, idx: int, text: str, progress: int) -> None:
    """Move a job to a new stage and update the progress bar."""
    if job_id not in jobs:
        return
    step_list = jobs.get(job_id, {}).get("steps", STEPS)
    set_job(job_id, active_step_index=idx, stage_text=text, progress=progress, steps=step_list)


def step_index(job_id: str, label: str) -> int:
    """Find the index of a step label, falling back to the final step."""
    steps = jobs.get(job_id, {}).get("steps", STEPS)
    try:
        return steps.index(label)
    except ValueError:
        return max(len(steps) - 1, 0)


def cleanup_old_jobs(cleanup_fn: Callable[[str], None], *, retention_seconds: int = 86400) -> None:
    """Remove completed/failed jobs after a retention window."""
    now = time.time()
    for jid in list(jobs.keys()):
        job = jobs[jid]
        created_at = job.get("created_at", 0)
        state = job.get("state", "running")
        if (now - created_at > retention_seconds) and (state in ["done", "error"]):
            cleanup_fn(jid)
            del jobs[jid]
