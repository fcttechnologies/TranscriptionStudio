import json
import os
import re
import shutil
import subprocess
import time
import uuid
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

# Pick one:
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
# OLLAMA_MODEL = "qwen2.5:14b"
# ====================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

STEPS = [
    "Downloading audio",
    "Transcribing",
    "Summarizing",
    "Writing markdown file",
    "Cleaning up temp files",
]

jobs: dict[str, dict] = {}

app = FastAPI()


class JobRequest(BaseModel):
    url: str
    custom_title: str | None = None


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "Command failed")
    return p.stdout


def set_job(job_id: str, **updates):
    jobs[job_id].update(updates)


def set_step(job_id: str, idx: int, text: str, progress: int):
    set_job(job_id, active_step_index=idx, stage_text=text, progress=progress, steps=STEPS)


def sanitize_filename(name: str) -> str:
    # allow spaces; remove filesystem-hostile chars
    name = re.sub(r"[^\w\s\-\.\(\)]", "", name).strip()
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
    title = run([YT_DLP, "--print", "%(title)s", "--no-download", url]).strip()
    return title or ""


def download_audio(job_id: str, url: str) -> tuple[Path, str]:
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


def summarize(job_id: str, title_hint: str, url: str, transcript: str) -> dict:
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
        raw = run([OLLAMA, "run", OLLAMA_MODEL, prompt]).strip()
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

        out = run([OLLAMA, "run", OLLAMA_MODEL, prompt_notes]).strip()
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


def write_md(job_id: str, url: str, custom_title: str | None, yt_title: str, s: dict, transcript: str) -> tuple[Path, str]:
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
    return out_path, chosen_title


def cleanup(job_id: str):
    set_step(job_id, 4, "Cleaning up…", 100)
    for p in TEMP_DIR.glob(f"{job_id}*"):
        try:
            p.unlink()
        except Exception:
            pass


def process_job(job_id: str, url: str, custom_title: str | None):
    try:
        mp3, yt_title = download_audio(job_id, url)
        transcript = transcribe(job_id, mp3)
        s = summarize(job_id, yt_title, url, transcript)
        out_path, final_title = write_md(job_id, url, custom_title, yt_title, s, transcript)
        cleanup(job_id)

        paste_pack = "\n".join([
            f"TITLE: {final_title}",
            f"URL: {url}",
            f"SAVED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "SUMMARY:",
            (s.get("summary") or "").strip(),
            "",
            "KEY POINTS:",
            "\n".join([f"- {x}" for x in (s.get("key_points") or [])]),
            "",
            "TRANSCRIPT:",
            transcript.strip(),
        ]).strip()

        set_job(
            job_id,
            state="done",
            stage_text="Done",
            progress=100,
            file_path=str(out_path),
            file_name=out_path.name,
            paste_pack=paste_pack,
            active_step_index=len(STEPS),
        )
    except Exception as e:
        set_job(job_id, state="error", stage_text="Failed", error=str(e), progress=100)


@app.get("/", response_class=HTMLResponse)
def home():
    if not INDEX_HTML.exists():
        return HTMLResponse("Missing index.html", status_code=500)
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.post("/api/jobs")
def create_job(req: JobRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "state": "running",
        "stage_text": "Queued…",
        "progress": 2,
        "error": None,
        "file_path": None,
        "paste_pack": None,
        "steps": STEPS,
        "active_step_index": 0,
        "created_at": time.time(),
    }
    background.add_task(process_job, job_id, req.url, req.custom_title)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return jobs.get(job_id, {"state": "error", "error": "Job not found"})

@app.post("/api/shortcut/start")
def shortcut_start(req: JobRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "job_id": job_id,
        "state": "running",
        "stage_text": "Queued",
        "progress": 0,
        "error": None,
        "file_path": None,
        "paste_pack": None,
        "active_step_index": 0,
        "created_at": time.time(),
    }

    background.add_task(process_job, job_id, req.url, req.custom_title)

    return {
        "job_id": job_id,
        "message": "Job started"
    }

@app.get("/api/shortcut/status/{job_id}")
def shortcut_status(job_id: str):
    job = jobs.get(job_id)

    if not job:
        return {"state": "error", "message": "Job not found"}

    if job["state"] == "done":
        return {
            "state": "done",
            "file_path": job.get("file_path"),
            "file_name": job.get("file_name"),
        }

    if job["state"] == "error":
        return {
            "state": "error",
            "message": job.get("error")
        }

    return {
        "state": "running",
        "stage": job.get("stage_text", "Working"),
        "progress": job.get("progress", 0)
    }
