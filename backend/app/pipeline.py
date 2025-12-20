import logging
import shutil
import subprocess
from pathlib import Path

from .config import (
    TEMP_DIR,
    WHISPER_MODEL_NAME,
    FFMPEG_LOCATION,
)
from .jobs import jobs, set_job, set_step, step_index, STEPS

import yt_dlp
import whisper
import os

# Ensure ffmpeg is on PATH for whisper
os.environ["PATH"] += os.pathsep + FFMPEG_LOCATION

logger = logging.getLogger(__name__)

WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)


def run_command(cmd: list[str]) -> str:
    logger.debug("Running command", extra={"cmd": cmd})
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error("Command failed", extra={"cmd": cmd, "stderr": stderr})
        raise RuntimeError(stderr or "Command failed")
    return result.stdout


def cleanup_startup_temp():
    if TEMP_DIR.exists():
        for item in TEMP_DIR.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete temp file", extra={"item": str(item), "error": str(exc)})


def download_audio(job_id: str, url: str) -> Path:
    set_step(job_id, step_index(job_id, "Downloading audio"), "Downloading audio…", 40)

    audio_out_template = str(TEMP_DIR / f"{job_id}.%(ext)s")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': audio_out_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'ffmpeg_location': FFMPEG_LOCATION,
        'quiet': True,
        'no_warnings': True,
        'cachedir': False,
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except Exception as e:
            raise RuntimeError(f"Download failed: {str(e)}") from e

    mp3 = TEMP_DIR / f"{job_id}.mp3"
    if not mp3.exists():
        matches = list(TEMP_DIR.glob(f"{job_id}*.mp3"))
        if matches:
            mp3 = matches[0]
        else:
            raise RuntimeError("Audio download failed: mp3 not found")

    return mp3


def transcribe(job_id: str, mp3: Path) -> str:
    set_step(job_id, step_index(job_id, "Transcribing"), "Transcribing…", 80)

    try:
        result = WHISPER_MODEL.transcribe(str(mp3))
        transcript = result.get("text", "").strip()
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}") from e

    if not transcript:
        raise RuntimeError("Transcription produced empty text")
    return transcript



def cleanup(job_id: str):
    steps_for_job = jobs.get(job_id, {}).get("steps", STEPS)
    final_idx = max(len(steps_for_job) - 1, 0)
    set_step(job_id, final_idx, "Cleaning up…", 100)
    for path in TEMP_DIR.glob(f"{job_id}*"):
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            logger.debug("Unable to delete temp file", extra={"path": str(path)})


def process_job(job_id: str, url: str):
    try:
        mp3 = download_audio(job_id, url)
        transcript = transcribe(job_id, mp3)
        _finalize_job(job_id, transcript)
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, state="error", stage_text="Failed", error=str(exc), progress=100)


def _finalize_job(job_id: str, text: str):
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

