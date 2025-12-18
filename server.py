import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ====== CONFIG ======
APP_DIR = Path(__file__).parent
INDEX_HTML = APP_DIR / "index.html"

OUTPUT_DIR = Path(os.environ.get("SVA_OUTPUT_DIR", Path.home() / "Documents" / "SummarizedVideos"))
TEMP_DIR = Path(os.environ.get("SVA_TEMP_DIR", Path("/tmp") / "summarizevideosapp"))
WHISPER_MODEL = Path(os.environ.get("WHISPER_MODEL_PATH", Path.home() / "models" / "ggml-base.en.bin"))


def resolve_command(env_var: str, default: str) -> str:
    """Resolve a binary location from an env var, PATH, or a default path.

    This prevents hardcoding Homebrew-specific paths and surfaces clearer errors
    when prerequisites are missing.
    """

    candidates = [os.environ.get(env_var), default]

    for candidate in candidates:
        if not candidate:
            continue

        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)

        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise RuntimeError(
        f"Could not find required command. Set {env_var} or install '{default}'."
    )


YT_DLP = resolve_command("YT_DLP", "/opt/homebrew/bin/yt-dlp")
WHISPER_CLI = resolve_command("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")
OLLAMA = resolve_command("OLLAMA_BIN", "/usr/local/bin/ollama")

MODEL_PRESETS = {
    "fast": os.environ.get("OLLAMA_MODEL_FAST", "qwen3:8b"),
    "pro": os.environ.get("OLLAMA_MODEL_PRO", "qwen2.5:14b"),
}
DEFAULT_MODEL_KEY = os.environ.get("OLLAMA_MODEL_DEFAULT", "fast")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

STEPS = [
    "Downloading audio",
    "Transcribing",
    "Summarizing",
    "Writing markdown file",
    "Cleaning up temp files",
]

TRANSCRIPT_ONLY_STEPS = [
    "Downloading audio",
    "Transcribing",
    "Writing markdown file",
    "Cleaning up temp files",
]

jobs: dict[str, dict] = {}

app = FastAPI()


class JobRequest(BaseModel):
    url: str
    custom_title: str | None = None
    transcript_only: bool = False
    model: str | None = None


@dataclass(slots=True)
class JobOptions:
    """Preprocessed job settings derived from user requests."""

    url: str
    custom_title: str | None
    transcript_only: bool
    model_key: str


def run(cmd: list[str]) -> str:
    """Run a command, raising on failure and returning stdout.

    Args:
        cmd: Full command with arguments.

    Returns:
        Captured stdout text.
    """

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "Command failed")
    return p.stdout


def resolve_model_choice(model_key: str | None) -> tuple[str, str]:
    """Return the configured model name and key, defaulting when needed.

    Args:
        model_key: Optional key from the client ("fast"/"pro").

    Returns:
        Tuple of (model name, normalized key).
    """

    key = (model_key or DEFAULT_MODEL_KEY).lower()
    if key not in MODEL_PRESETS:
        key = DEFAULT_MODEL_KEY

    model_name = MODEL_PRESETS.get(key) or MODEL_PRESETS[DEFAULT_MODEL_KEY]
    if not model_name:
        raise RuntimeError("No model configured. Set OLLAMA_MODEL_FAST/PRO.")
    return model_name, key


def build_job_options(req: JobRequest, *, force_transcript_only: bool | None = None) -> JobOptions:
    """Normalize incoming payloads into a JobOptions record.

    Args:
        req: User payload from the UI/Shortcut.
        force_transcript_only: Optional override for the transcript-only flag.

    Returns:
        A `JobOptions` instance used throughout the pipeline.
    """

    transcript_only = req.transcript_only if force_transcript_only is None else force_transcript_only
    _, key = resolve_model_choice(req.model)
    return JobOptions(
        url=req.url.strip(),
        custom_title=(req.custom_title or None),
        transcript_only=bool(transcript_only),
        model_key=key,
    )


def create_job_record(job_id: str, *, transcript_only: bool, model_key: str) -> dict:
    """Create the initial job dictionary persisted in memory.

    Args:
        job_id: Unique identifier for this run.
        transcript_only: Whether to skip summarization.
        model_key: Resolved model tier key (e.g., "fast").

    Returns:
        A dictionary stored in the in-memory job registry.
    """

    steps_for_job = TRANSCRIPT_ONLY_STEPS if transcript_only else STEPS
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
        "model_key": model_key,
    }


def set_job(job_id: str, **updates):
    """Update a job entry in place with new state or metadata."""

    jobs[job_id].update(updates)


def set_step(job_id: str, idx: int, text: str, progress: int):
    """Advance a job to a new UI step with progress metadata."""

    step_list = jobs.get(job_id, {}).get("steps", STEPS)
    set_job(job_id, active_step_index=idx, stage_text=text, progress=progress, steps=step_list)


def sanitize_filename(name: str) -> str:
    """Clean user-provided titles for safe filesystem usage."""

    # allow spaces; remove filesystem-hostile chars
    name = re.sub(r"[^\w\s\-\.\(\)&]", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:140] if name else "Untitled"


def dedupe_path(base_path: Path) -> Path:
    """Return a unique path by appending a counter when needed."""

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


def clean_title(t: str) -> str:
    """
    Enforce title cleanup in code (models sometimes ignore prompts):
    - remove hashtags and anything after a hashtag-run
    - remove trailing ellipses
    - collapse whitespace
    """
    t = (t or "").strip()
    if not t:
        return ""

    # Remove hashtags + any trailing hashtag section
    # Example: "Title ... #tag #tag" -> "Title ..."
    t = re.sub(r"\s+#.*$", "", t).strip()

    # Remove trailing "..." or "…"
    t = re.sub(r"(\.\.\.|…)\s*$", "", t).strip()

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    return t


def extract_video_title(url: str) -> str:
    """Fetch the video title without downloading media."""

    title = run([YT_DLP, "--print", "%(title)s", "--no-download", url]).strip()
    return title or ""


def download_audio(job_id: str, url: str) -> tuple[Path, str]:
    """Download an MP3 for the given job and return its path and source title.

    Args:
        job_id: Identifier used to update progress.
        url: Video URL supplied by the user.

    Returns:
        Tuple of (path to MP3 file, video title from YouTube).
    """

    set_step(job_id, 0, "Downloading audio…", 18)

    audio_out = TEMP_DIR / f"{job_id}.%(ext)s"
    cmd = [
        YT_DLP,
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", str(audio_out),
        url,
    ]
    run(cmd)

    mp3 = TEMP_DIR / f"{job_id}.mp3"
    if not mp3.exists():
        matches = list(TEMP_DIR.glob(f"{job_id}*.mp3"))
        if matches:
            mp3 = matches[0]
        else:
            raise RuntimeError("Audio download failed: mp3 not found")

    yt_title = extract_video_title(url)
    return mp3, yt_title


def transcribe(job_id: str, mp3: Path) -> str:
    """Run whisper-cli to produce a transcript for the downloaded audio.

    Args:
        job_id: Identifier used to update progress.
        mp3: Local path to the audio file.

    Returns:
        Transcript text.
    """

    if not WHISPER_MODEL.exists():
        raise RuntimeError(f"Whisper model missing at {WHISPER_MODEL}")

    set_step(job_id, 1, "Transcribing…", 45)

    out_base = TEMP_DIR / f"{job_id}_transcript"
    cmd = [WHISPER_CLI, "-m", str(WHISPER_MODEL), "-f", str(mp3), "-otxt", "-of", str(out_base)]
    run(cmd)

    txt = Path(str(out_base) + ".txt")
    if not txt.exists():
        raise RuntimeError("Transcription failed: transcript file not created")

    t = txt.read_text(encoding="utf-8", errors="ignore").strip()
    if not t:
        raise RuntimeError("Transcription produced empty text")
    return t


def chunk_text(text: str, max_chars: int = 9000) -> list[str]:
    """Split text into chunks that prefer whitespace boundaries."""

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    i = 0

    while i < len(text):
        end = min(i + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(" ", i, end)
            if boundary != -1 and boundary > i + (max_chars * 0.6):
                end = boundary

        chunks.append(text[i:end].strip())
        i = end

    return chunks


def extract_json_object(raw: str) -> dict:
    if not raw:
        raise RuntimeError("Empty LLM output")

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("{")
    if start == -1:
        raise RuntimeError("No '{' found in LLM output")

    depth = 0
    for i in range(start, len(raw)):
        c = raw[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:i + 1]
                return json.loads(candidate)

    raise RuntimeError("Unterminated JSON object in LLM output")


def summarize(job_id: str, title_hint: str, url: str, transcript: str, model_name: str) -> dict:
    """Summarize a transcript via Ollama, handling long inputs with chunking.

    Args:
        job_id: Identifier used to update progress.
        title_hint: Title from YouTube, used to guide the model.
        url: Source URL to include in prompts.
        transcript: Full transcript text to summarize.
        model_name: Concrete Ollama model to run.

    Returns:
        JSON-friendly dict with title, summary, and key_points fields.
    """

    set_step(job_id, 2, "Summarizing…", 78)

    transcript = (transcript or "").strip()
    if not transcript:
        raise RuntimeError("No transcript text to summarize")

    title_hint_clean = clean_title(title_hint)

    # Slightly higher since you’re using 8B and it’s been stable for you
    NO_CHUNK_MAX_CHARS = 16000

    def prompt_json_from_text(text: str) -> str:
        return f"""
Create a clean summary for later reuse.

Hard rules:
- Output MUST be valid JSON only. No markdown. No extra text.
- Do NOT invent facts, names, URLs, organizations, tools, numbers, or dates.
- Do NOT add generic filler (e.g., "consult a professional") unless the speaker says that.
- If the transcript contains numbers/dates, at least 5 key_points MUST include those numbers/dates verbatim.
- Keep brand/site names exactly as spoken (don’t “correct” or rewrite them).
- Title must be clean: remove hashtags and trailing "..." (even if they appear in the hint).

Return ONLY JSON with EXACT keys:
{{
  "title": "clear concise title",
  "summary": "3-6 sentences describing what the video says",
  "key_points": ["10-16 bullets capturing the most useful points"]
}}

TITLE HINT: {title_hint_clean}
URL: {url}

TRANSCRIPT:
\"\"\"{text}\"\"\"
""".strip()

    def call_llm_json(prompt: str) -> dict:
        raw = run([OLLAMA, "run", model_name, prompt]).strip()
        try:
            data = extract_json_object(raw)
        except Exception as e:
            tail = raw[-800:] if raw else ""
            raise RuntimeError(f"LLM did not return valid JSON. Last output chars:\n{tail}") from e

        # Validation
        if not str(data.get("summary", "")).strip():
            raise RuntimeError("LLM JSON missing summary")
        if not isinstance(data.get("key_points"), list) or not data["key_points"]:
            raise RuntimeError("LLM JSON missing key_points list")

        # Enforce title cleanup in code too
        data["title"] = clean_title(str(data.get("title", ""))) or title_hint_clean or "Untitled"
        return data

    # 1) Try single-pass first
    if len(transcript) <= NO_CHUNK_MAX_CHARS:
        set_step(job_id, 2, "Summarizing… (single pass)", 86)
        return call_llm_json(prompt_json_from_text(transcript))

    # 2) Fallback: chunking for long transcripts
    set_step(job_id, 2, "Summarizing… (long transcript fallback)", 86)

    chunks = chunk_text(transcript, max_chars=9000)
    notes_parts = []
    total = len(chunks)

    for idx, ch in enumerate(chunks, start=1):
        prog = 86 + int((idx / total) * 6)  # 86 -> 92
        set_step(job_id, 2, f"Summarizing… (chunk {idx}/{total})", prog)

        prompt_notes = f"""
Extract factual notes from this transcript chunk.

Rules:
- Output ONLY plain text.
- Do NOT add outside facts or examples.
- Keep numbers, names, URLs, and brand/site names EXACT.
- Prefer capturing more facts over fewer (redundancy is fine).

FACTS:
- ...

NUMBERS / DATES:
- ...

TERMS / DEFINITIONS:
- ...

CHUNK:
\"\"\"{ch}\"\"\"
""".strip()

        out = run([OLLAMA, "run", model_name, prompt_notes]).strip()
        notes_parts.append(out)

    notes = "\n".join(notes_parts).strip()

    set_step(job_id, 2, "Summarizing… (finalizing)", 94)

    prompt_final = f"""
Create a clean summary for later reuse from NOTES.

Hard rules:
- Output MUST be valid JSON only. No markdown. No extra text.
- Do NOT invent facts, names, URLs, organizations, tools, numbers, or dates.
- Do NOT add generic filler unless it appears in NOTES.
- If NOTES contain numbers/dates, at least 5 key_points MUST include those numbers/dates verbatim.
- Title must be clean: remove hashtags and trailing "..." (even if they appear in the hint).

Return ONLY JSON with EXACT keys:
{{
  "title": "clear concise title",
  "summary": "3-6 sentences describing what the video says",
  "key_points": ["10-16 bullets capturing the most useful points"]
}}

TITLE HINT: {title_hint_clean}
URL: {url}

NOTES:
\"\"\"{notes}\"\"\"
""".strip()

    return call_llm_json(prompt_final)


def write_md(
    job_id: str,
    url: str,
    custom_title: str | None,
    yt_title: str,
    s: dict,
    transcript: str,
) -> tuple[Path, str, str]:
    """Write the full summary markdown file and return metadata for UI/clipboard.

    Args:
        job_id: Identifier used to update progress.
        url: Source URL of the content.
        custom_title: Optional user-provided title override.
        yt_title: Title fetched from YouTube.
        s: Summary payload from the LLM.
        transcript: Full transcript text.

    Returns:
        Tuple of (markdown path, chosen title, saved timestamp string).
    """

    set_step(job_id, 3, "Writing markdown file…", 92)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chosen_title = (
        (custom_title or "").strip()
        or clean_title(yt_title)
        or clean_title(s.get("title") or "")
        or "Untitled"
    )
    chosen_title = clean_title(chosen_title) or "Untitled"

    safe = sanitize_filename(chosen_title)
    out_path = dedupe_path(OUTPUT_DIR / f"{safe}.md")

    md = []
    md.append(f"# {chosen_title}\n")
    md.append(f"- **URL:** {url}")
    md.append(f"- **Saved:** {now}\n")

    md.append("## Summary")
    md.append((s.get("summary") or "").strip() or "—")
    md.append("")

    md.append("## Key Points")
    for x in (s.get("key_points") or []):
        bullet = str(x).strip()
        if bullet:
            md.append(f"- {bullet}")
    if not (s.get("key_points") or []):
        md.append("—")
    md.append("")

    md.append("## Transcript")
    md.append(transcript.strip() or "—")

    out_path.write_text("\n".join(md), encoding="utf-8")
    return out_path, chosen_title, now


def write_md_transcript_only(
    job_id: str,
    url: str,
    custom_title: str | None,
    yt_title: str,
    transcript: str,
) -> tuple[Path, str, str]:
    """Write a transcript-only markdown file and return metadata for UI/clipboard.

    Args:
        job_id: Identifier used to update progress.
        url: Source URL of the content.
        custom_title: Optional user-provided title override.
        yt_title: Title fetched from YouTube.
        transcript: Full transcript text.

    Returns:
        Tuple of (markdown path, chosen title, saved timestamp string).
    """

    set_step(job_id, 2, "Writing markdown file…", 90)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chosen_title = (
        (custom_title or "").strip()
        or clean_title(yt_title)
        or "Untitled"
    )
    chosen_title = clean_title(chosen_title) or "Untitled"

    safe = sanitize_filename(chosen_title)
    out_path = dedupe_path(OUTPUT_DIR / f"{safe}.md")

    md = []
    md.append(f"# {chosen_title}\n")
    md.append(f"- **URL:** {url}")
    md.append(f"- **Saved:** {now}\n")

    md.append("## Transcript")
    md.append(transcript.strip() or "—")

    out_path.write_text("\n".join(md), encoding="utf-8")
    return out_path, chosen_title, now


def build_clipboard_payload(
    *,
    title: str,
    url: str,
    saved_at: str,
    summary: str,
    key_points: list[str],
    transcript: str,
    transcript_only: bool,
) -> str:
    """Format clipboard text for the UI and iOS Shortcut responses.

    Args:
        title: Final cleaned title written to disk.
        url: Source URL of the content.
        saved_at: Timestamp string shown in the UI.
        summary: Summarized description text.
        key_points: Bullet list from the model.
        transcript: Full transcript text.
        transcript_only: Whether to omit summary/key points.

    Returns:
        Clipboard-friendly block of text.
    """

    if transcript_only:
        return transcript.strip()

    key_points_text = "\n".join([f"- {point}" for point in key_points])
    lines = [
        f"TITLE: {title}",
        f"URL: {url}",
        f"SAVED: {saved_at}",
        "",
        "SUMMARY:",
        summary.strip(),
        "",
        "KEY POINTS:",
        key_points_text,
        "",
        "TRANSCRIPT:",
        transcript.strip(),
    ]
    return "\n".join(lines).strip()


def cleanup(job_id: str):
    """Remove temp files for a job and finalize progress bar state."""

    steps_for_job = jobs.get(job_id, {}).get("steps", STEPS)
    final_idx = max(len(steps_for_job) - 1, 0)
    set_step(job_id, final_idx, "Cleaning up…", 100)
    for p in TEMP_DIR.glob(f"{job_id}*"):
        try:
            p.unlink()
        except Exception:
            pass


def process_job(job_id: str, options: JobOptions):
    """Full pipeline for a job: download -> transcribe -> summarize -> save.

    This is executed in a FastAPI background task so the HTTP response
    returns immediately while work continues.
    """

    try:
        mp3, yt_title = download_audio(job_id, options.url)
        transcript = transcribe(job_id, mp3)

        if options.transcript_only:
            out_path, final_title, saved_ts = write_md_transcript_only(
                job_id, options.url, options.custom_title, yt_title, transcript
            )
            summary_data = {"summary": "", "key_points": []}
        else:
            model_name, _ = resolve_model_choice(options.model_key)
            summary_data = summarize(
                job_id, yt_title, options.url, transcript, model_name
            )
            out_path, final_title, saved_ts = write_md(
                job_id,
                options.url,
                options.custom_title,
                yt_title,
                summary_data,
                transcript,
            )

        cleanup(job_id)

        clipboard_payload = build_clipboard_payload(
            title=final_title,
            url=options.url,
            saved_at=saved_ts,
            summary=(summary_data.get("summary") or ""),
            key_points=summary_data.get("key_points") or [],
            transcript=transcript,
            transcript_only=options.transcript_only,
        )

        set_job(
            job_id,
            state="done",
            stage_text="Done",
            progress=100,
            file_path=str(out_path),
            file_name=out_path.name,
            clipboard_payload=clipboard_payload,
            active_step_index=len(jobs[job_id].get("steps", STEPS)),
        )
    except Exception as e:
        set_job(job_id, state="error", stage_text="Failed", error=str(e), progress=100)


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the single-page UI. Accessed by browsers at `/`."""

    if not INDEX_HTML.exists():
        return HTMLResponse("Missing index.html", status_code=500)
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.post("/api/jobs")
def create_job(req: JobRequest, background: BackgroundTasks):
    """Web UI entrypoint to start a summarize/transcript job.

    Called by: the browser UI fetches POST `/api/jobs`.

    Returns:
        Dict containing `job_id` for polling and the transcript_only flag.
    """

    job_id = str(uuid.uuid4())
    options = build_job_options(req)
    jobs[job_id] = create_job_record(
        job_id, transcript_only=options.transcript_only, model_key=options.model_key
    )
    background.add_task(process_job, job_id, options)
    return {"job_id": job_id, "transcript_only": options.transcript_only}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Web UI polling endpoint returning current job status.

    Called by: the browser UI via GET `/api/jobs/{job_id}`.

    Returns:
        Job dictionary or an error placeholder if the job is missing.
    """

    return jobs.get(job_id, {"state": "error", "error": "Job not found"})

@app.post("/api/shortcut/start")
def shortcut_start(req: JobRequest, background: BackgroundTasks):
    """iOS Shortcut-only entrypoint; always runs in transcript-only mode.

    Called by: Apple Shortcut via POST `/api/shortcut/start`.

    Returns:
        Dict with job_id, confirmation message, and transcript_only flag.
    """

    job_id = str(uuid.uuid4())
    options = build_job_options(req, force_transcript_only=True)

    jobs[job_id] = create_job_record(
        job_id, transcript_only=options.transcript_only, model_key=options.model_key
    )

    background.add_task(process_job, job_id, options)

    return {"job_id": job_id, "message": "Job started", "transcript_only": options.transcript_only}

@app.get("/api/shortcut/status/{job_id}")
def shortcut_status(job_id: str):
    """iOS Shortcut polling endpoint returning clipboard payloads.

    Called by: Apple Shortcut via GET `/api/shortcut/status/{job_id}`.

    Returns:
        Running state, error details, or clipboard_payload when done.
    """

    job = jobs.get(job_id)

    if not job:
        return {"state": "error", "message": "Job not found"}

    if job["state"] == "done":
        return {
            "state": "done",
            "clipboard_payload": job.get("clipboard_payload"),
        }

    if job["state"] == "error":
        return {
            "state": "error",
            "message": job.get("error")
        }

    return {"state": "running"}
