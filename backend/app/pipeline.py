"""Processing pipeline for downloading audio and running Whisper."""

import gc
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import yt_dlp
from faster_whisper import WhisperModel

from .config import (
    FFMPEG_LOCATION,
    TEMP_DIR,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_IDLE_TIMEOUT,
    WHISPER_MODEL_NAME,
    WHISPER_PRELOAD,
)
from .jobs import STEPS, jobs, set_job, set_step, step_index

# Ensure ffmpeg is on PATH for audio processing and yt-dlp post-processing.
if FFMPEG_LOCATION:
    os.environ["PATH"] += os.pathsep + FFMPEG_LOCATION

logger = logging.getLogger(__name__)

# Faster-Whisper model lifecycle (see config.py for the three modes). By default
# the model loads on first use and is released after WHISPER_IDLE_TIMEOUT of idle,
# so the app holds it in RAM only while transcription is actually in use.
_model_lock = threading.Lock()
_model = None
_model_last_used = 0.0


def get_model() -> WhisperModel:
    """Return the Whisper model, loading it on first use and caching it across
    jobs. The idle reaper frees it after WHISPER_IDLE_TIMEOUT of no use (unless
    that's 0, meaning keep it warm once loaded)."""
    global _model, _model_last_used
    with _model_lock:
        if _model is None:
            logger.info(
                "Loading Whisper model %s (%s/%s)",
                WHISPER_MODEL_NAME, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
            )
            _model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        _model_last_used = time.monotonic()
        return _model


def _idle_reaper() -> None:
    """Release the model once it's been idle past the timeout, so a rarely-used
    service doesn't hold it resident. An in-flight transcription keeps its own
    reference, so reaping mid-job is safe — the next job reloads."""
    global _model
    while True:
        time.sleep(60)
        with _model_lock:
            if _model is not None and (time.monotonic() - _model_last_used) > WHISPER_IDLE_TIMEOUT:
                logger.info("Releasing idle Whisper model after %.0fs idle", WHISPER_IDLE_TIMEOUT)
                _model = None
                gc.collect()


# Idle release only runs when a positive timeout is set (0 = keep warm once loaded).
if WHISPER_IDLE_TIMEOUT > 0:
    threading.Thread(target=_idle_reaper, name="whisper-idle-reaper", daemon=True).start()

# Eager preload mode: load at startup for the lowest first-request latency.
if WHISPER_PRELOAD:
    get_model()


def run_command(cmd: list[str]) -> str:
    """Run a subprocess command and raise on non-zero exit."""
    logger.debug("Running command", extra={"cmd": cmd})
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error("Command failed", extra={"cmd": cmd, "stderr": stderr})
        raise RuntimeError(stderr or "Command failed")
    return result.stdout


def cleanup_startup_temp() -> None:
    """Clear leftover temp files from previous runs."""
    if TEMP_DIR.exists():
        for item in TEMP_DIR.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to delete temp file",
                    extra={"item": str(item), "error": str(exc)},
                )


def download_audio(job_id: str, url: str) -> Path:
    """Download audio from the provided video URL and return the mp3 path."""
    set_step(job_id, step_index(job_id, "Downloading audio"), "Downloading audio…", 40)

    # Use the job ID to isolate files for concurrent jobs.
    audio_out_template = str(TEMP_DIR / f"{job_id}.%(ext)s")

    ydl_opts = {
        # Prefer a real audio-only stream; else an H.264 stream — TikTok's bytevc1/H.265
        # "best" formats advertise AAC but download video-only, breaking audio extraction;
        # else any best. See reference/upkeep.md — Transcription Studio dependency check.
        "format": "bestaudio/best[vcodec^=h264]/best",
        "outtmpl": audio_out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "ffmpeg_location": FFMPEG_LOCATION,
        "quiet": True,
        "no_warnings": True,
        "cachedir": False,
        "noplaylist": True,
    }

    # Download with yt-dlp and raise a friendly error if it fails.
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except Exception as exc:
            raise RuntimeError(f"Download failed: {str(exc)}") from exc

    mp3 = TEMP_DIR / f"{job_id}.mp3"
    if not mp3.exists():
        matches = list(TEMP_DIR.glob(f"{job_id}*.mp3"))
        if matches:
            mp3 = matches[0]
        else:
            raise RuntimeError("Audio download failed: mp3 not found")

    return mp3


def transcribe(job_id: str, mp3: Path) -> str:
    """Run Whisper transcription and return the text."""
    set_step(job_id, step_index(job_id, "Transcribing"), "Transcribing…", 80)

    try:
        segments, _ = get_model().transcribe(str(mp3))
        transcript = " ".join(
            segment.text.strip() for segment in segments if segment.text and segment.text.strip()
        ).strip()
    except Exception as exc:
        raise RuntimeError(f"Transcription failed: {str(exc)}") from exc

    if not transcript:
        raise RuntimeError("Transcription produced empty text")
    return transcript


def cleanup(job_id: str) -> None:
    """Remove temp files for a completed job."""
    steps_for_job = jobs.get(job_id, {}).get("steps", STEPS)
    final_idx = max(len(steps_for_job) - 1, 0)
    set_step(job_id, final_idx, "Cleaning up…", 100)
    for path in TEMP_DIR.glob(f"{job_id}*"):
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            logger.debug("Unable to delete temp file", extra={"path": str(path)})


def process_job(job_id: str, url: str) -> None:
    """Orchestrate the download/transcribe/cleanup flow for one job."""
    try:
        mp3 = download_audio(job_id, url)
        transcript = transcribe(job_id, mp3)
        _finalize_job(job_id, transcript)
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, state="error", stage_text="Failed", error=str(exc), progress=100)


def _finalize_job(job_id: str, text: str) -> None:
    """Mark a job as complete and store the transcript."""
    cleanup(job_id)

    steps = jobs[job_id].get("steps", STEPS)

    set_job(
        job_id,
        state="done",
        stage_text="Done",
        progress=100,
        transcript=text,
        active_step_index=len(steps),
    )
