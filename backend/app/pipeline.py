import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import (
    TEMP_DIR,
    OUTPUT_DIR,
    WHISPER_MODEL_NAME,
    FFMPEG_LOCATION,
)
from .jobs import JobOptions, jobs, set_job, set_step, step_index, STEPS

import yt_dlp
import whisper
import os

# Ensure ffmpeg is on PATH for whisper
os.environ["PATH"] += os.pathsep + FFMPEG_LOCATION

logger = logging.getLogger(__name__)

WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)

CHUNK_MAX_CHARS = 13000
NOTES_MAX_CHARS = 22000


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


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-\.\(\)&]", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:140] if name else "Untitled"


def dedupe_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    i = 2
    while True:
        candidate = base_path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return ""

    title = re.sub(r"\s+#.*$", "", title).strip()
    title = re.sub(r"(\.\.\.|…)\s*$", "", title).strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title


def resolve_title(custom_title: Optional[str], detected_title: str) -> str:
    chosen_title = (
        (custom_title or "").strip()
        or clean_title(detected_title)
        or "Untitled"
    )
    return clean_title(chosen_title) or "Untitled"


def extract_video_title(url: str) -> str:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cachedir': False,
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return info.get('title', '')
        except Exception as e:
            logger.error(f"Failed to extract title: {e}")
            return ""


def download_audio(job_id: str, url: str) -> tuple[Path, str]:
    set_step(job_id, step_index(job_id, "Downloading audio"), "Downloading audio…", 18)

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
            info = ydl.extract_info(url, download=False)
            yt_title = info.get('title', 'Untitled')
        except Exception as e:
            raise RuntimeError(f"Download failed: {str(e)}") from e

    mp3 = TEMP_DIR / f"{job_id}.mp3"
    if not mp3.exists():
        matches = list(TEMP_DIR.glob(f"{job_id}*.mp3"))
        if matches:
            mp3 = matches[0]
        else:
            raise RuntimeError("Audio download failed: mp3 not found")

    return mp3, yt_title


def transcribe(job_id: str, mp3: Path) -> str:
    set_step(job_id, step_index(job_id, "Transcribing"), "Transcribing…", 45)

    try:
        result = WHISPER_MODEL.transcribe(str(mp3))
        transcript = result.get("text", "").strip()
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}") from e

    if not transcript:
        raise RuntimeError("Transcription produced empty text")
    return transcript


def write_md(
    job_id: str,
    source_label: str,
    custom_title: Optional[str],
    detected_title: str,
    text: str,
) -> tuple[Path, str, str]:
    set_step(job_id, step_index(job_id, "Writing markdown file"), "Writing markdown file…", 90)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chosen_title = resolve_title(custom_title, detected_title)

    safe = sanitize_filename(chosen_title)
    out_path = dedupe_path(OUTPUT_DIR / f"{safe}.md")

    md_lines = [
        f"# {chosen_title}\n",
        f"- **Source:** {source_label}",
        f"- **Saved:** {now}\n",
        "## Original Content",
        text.strip() or "—",
    ]

    out_path.write_text("\n".join(md_lines), encoding="utf-8")
    return out_path, chosen_title, now


def build_clipboard_payload(text: str) -> str:
    return text.strip()


def cleanup(job_id: str):
    steps_for_job = jobs.get(job_id, {}).get("steps", STEPS)
    final_idx = max(len(steps_for_job) - 1, 0)
    set_step(job_id, final_idx, "Cleaning up…", 100)
    for path in TEMP_DIR.glob(f"{job_id}*"):
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            logger.debug("Unable to delete temp file", extra={"path": str(path)})


def process_job(job_id: str, options: JobOptions):
    try:
        mp3, yt_title = download_audio(job_id, options.url)
        transcript = transcribe(job_id, mp3)
        _finalize_job(job_id, options, transcript, yt_title, options.url)
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, state="error", stage_text="Failed", error=str(exc), progress=100)


def _finalize_job(
    job_id: str, 
    options: JobOptions, 
    text: str, 
    title_hint: str, 
    source_label: str,
):
    if options.save_markdown:
        out_path, final_title, saved_ts = write_md(
            job_id, source_label, options.custom_title, title_hint, text
        )
    else:
        out_path = None
        final_title = resolve_title(options.custom_title, title_hint)
        saved_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cleanup(job_id)

    clipboard_payload = build_clipboard_payload(text)
    
    steps = jobs[job_id].get("steps", STEPS)

    set_job(
        job_id,
        state="done",
        stage_text="Done",
        progress=100,
        file_path=str(out_path) if out_path else None,
        file_name=out_path.name if out_path else None,
        clipboard_payload=clipboard_payload,
        active_step_index=len(steps),
    )
