"""Tests for the in-memory job tracking layer."""

import time

import pytest

from backend.app import jobs as jobs_module
from backend.app.jobs import (
    STEPS,
    cleanup_old_jobs,
    create_job_record,
    set_job,
    set_step,
    step_index,
)


@pytest.fixture(autouse=True)
def clear_jobs():
    """Ensure each test starts with an empty job store."""
    jobs_module.jobs.clear()
    yield
    jobs_module.jobs.clear()


def test_create_job_record_initial_shape():
    record = create_job_record("job-1")

    assert record["job_id"] == "job-1"
    assert record["state"] == "running"
    assert record["progress"] == 2
    assert record["error"] is None
    assert record["transcript"] is None
    assert record["steps"] == STEPS
    assert record["active_step_index"] == 0
    assert isinstance(record["created_at"], float)


def test_set_job_updates_existing_record():
    jobs_module.jobs["job-1"] = create_job_record("job-1")

    set_job("job-1", state="done", progress=100, transcript="hello world")

    record = jobs_module.jobs["job-1"]
    assert record["state"] == "done"
    assert record["progress"] == 100
    assert record["transcript"] == "hello world"


def test_set_job_is_a_no_op_for_unknown_id():
    set_job("missing", state="done")
    assert "missing" not in jobs_module.jobs


def test_set_step_updates_active_step_progress_and_text():
    jobs_module.jobs["job-1"] = create_job_record("job-1")

    set_step("job-1", 1, "Transcribing…", 80)

    record = jobs_module.jobs["job-1"]
    assert record["active_step_index"] == 1
    assert record["stage_text"] == "Transcribing…"
    assert record["progress"] == 80
    assert record["steps"] == STEPS


def test_step_index_returns_matching_index():
    jobs_module.jobs["job-1"] = create_job_record("job-1")
    assert step_index("job-1", "Transcribing") == STEPS.index("Transcribing")


def test_step_index_falls_back_to_final_step_for_unknown_label():
    jobs_module.jobs["job-1"] = create_job_record("job-1")
    assert step_index("job-1", "Not a step") == len(STEPS) - 1


def test_cleanup_old_jobs_removes_terminal_jobs_beyond_retention():
    record_done = create_job_record("done")
    record_done["state"] = "done"
    record_done["created_at"] = time.time() - 100_000

    record_error = create_job_record("error")
    record_error["state"] = "error"
    record_error["created_at"] = time.time() - 100_000

    record_running = create_job_record("running")
    record_running["created_at"] = time.time() - 100_000

    record_recent_done = create_job_record("recent")
    record_recent_done["state"] = "done"

    jobs_module.jobs.update(
        {
            "done": record_done,
            "error": record_error,
            "running": record_running,
            "recent": record_recent_done,
        }
    )

    cleaned = []
    cleanup_old_jobs(cleaned.append, retention_seconds=86_400)

    assert "done" not in jobs_module.jobs
    assert "error" not in jobs_module.jobs
    assert "running" in jobs_module.jobs
    assert "recent" in jobs_module.jobs
    assert sorted(cleaned) == ["done", "error"]
