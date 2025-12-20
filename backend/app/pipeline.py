import json
import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import (
    OLLAMA,
    OLLAMA_MODEL,
    TEMP_DIR,
    OUTPUT_DIR,
    WHISPER_MODEL_NAME,
    FFMPEG_LOCATION,
)
from .jobs import JobOptions, jobs, set_job, set_step, step_index, STEPS, PDF_STEPS
from pypdf import PdfReader
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


def resolve_title(custom_title: Optional[str], detected_title: str, summary_title: Optional[str]) -> str:
    chosen_title = (
        (custom_title or "").strip()
        or clean_title(detected_title)
        or clean_title(summary_title or "")
        or "Untitled"
    )
    return clean_title(chosen_title) or "Untitled"


def extract_text_from_pdf(job_id: str, pdf_path: Path) -> str:
    set_step(job_id, step_index(job_id, "Extracting text"), "Extracting text…", 10)
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            raise RuntimeError("PDF is encrypted")
            
        params = {} # Placeholder for potential future params
        text_parts = []
        for page in reader.pages:
            text = page.extract_text(**params)
            if text:
                text_parts.append(text)
        
        full_text = "\n".join(text_parts).strip()
        if not full_text:
             raise RuntimeError("PDF extract produced empty text (scanned PDF?)")
        
        return full_text
    except Exception as exc:
        raise RuntimeError(f"PDF extraction failed: {str(exc)}") from exc


def clean_extracted_text(job_id: str, text: str) -> str:
    set_step(job_id, step_index(job_id, "Cleaning text"), "Cleaning text…", 25)
    
    # 1. Simple deterministic clean first
    text = re.sub(r'(\n\s*){3,}', '\n\n', text) # Normalize newlines
    
    # 2. AI Clean
    no_chunk_max_chars = 24000
    
    def prompt_clean(chunk_text: str) -> str:
        return f'''
Remove page numbers, headers, footers, and noisy artifacts from this text.
Return ONLY the clean main content. Do not summarize.

TEXT:
"""{chunk_text}"""
'''.strip()

    if len(text) <= no_chunk_max_chars:
         set_step(job_id, step_index(job_id, "Cleaning text"), "Cleaning text (single pass)…", 30)
         cleaned = run_command([OLLAMA, "run", OLLAMA_MODEL, prompt_clean(text)]).strip()
         return cleaned if cleaned else text # Fallback if model fails

    # Chunked cleaning
    chunks = chunk_text(text) # Uses global CHUNK_MAX_CHARS (13k)
    cleaned_parts = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        progress = 25 + int((idx / total) * 15)
        set_step(job_id, step_index(job_id, "Cleaning text"), f"Cleaning text (chunk {idx}/{total})…", progress)
        cleaned_chunk = run_command([OLLAMA, "run", OLLAMA_MODEL, prompt_clean(chunk)]).strip()
        cleaned_parts.append(cleaned_chunk if cleaned_chunk else chunk)
    
    return "\n\n".join(cleaned_parts).strip()



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


def chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    i = 0

    while i < len(text):
        end = min(i + CHUNK_MAX_CHARS, len(text))
        if end < len(text):
            boundary = text.rfind(" ", i, end)
            if boundary != -1 and boundary > i + (CHUNK_MAX_CHARS * 0.6):
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
        char = raw[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:i + 1]
                return json.loads(candidate)

    raise RuntimeError("Unterminated JSON object in LLM output")


def summarize(job_id: str, title_hint: str, source_label: str, text: str, content_type: str = "video") -> dict:
    set_step(job_id, step_index(job_id, "Summarizing"), "Summarizing…", 78)

    text = (text or "").strip()
    if not text:
        raise RuntimeError("No text to summarize")

    title_hint_clean = clean_title(title_hint)
    no_chunk_max_chars = 24000
    
    context_instruction = "Analyze CONTENT TYPE:"
    if content_type == "pdf":
        context_instruction = "Analyze DOCUMENT TYPE (e.g. Research Paper, Contract, Guide, or General):"

    def prompt_json_from_text(input_text: str) -> str:
        return f'''
Create a clean summary for later reuse.

1. {context_instruction}
- Tax/Finance: Focus on strategies, exact steps, tax forms, and specific money/percentage figures.
- AI/Apps: Focus on specific features, pricing tiers, limitations, and use cases.
- Coding/Tutorial: Focus on libraries used, specific commands, and architectural patterns.
- General: Standard summary.
- Documents: Focus on key clauses, findings, dates, or core concepts.

2. Hard Rules:
- Output MUST be valid JSON only. No markdown. No extra text.
- Do NOT invent facts.
- If the text contains numbers, dates, prices, or versions, the "key_points" MUST include them.
- "key_points" should be actionable (e.g., "Use tax form X", "Run command Y", "Clause Z implies...").
- Title must be clean: remove hashtags and trailing "..." (even if they appear in the hint).

3. Return ONLY JSON with EXACT keys:
{{
  "title": "clear concise title",
  "summary": "3-6 sentences describing content, context-aware",
  "key_points": ["10-16 bullets capturing the most useful points, prioritizing numbers/dates"]
}}

TITLE HINT: {title_hint_clean}
SOURCE: {source_label}

CONTENT:
"""{input_text}"""
'''.strip()

    def call_llm_json(prompt: str) -> dict:
        raw = run_command([OLLAMA, "run", OLLAMA_MODEL, prompt]).strip()
        try:
            data = extract_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            tail = raw[-800:] if raw else ""
            raise RuntimeError(f"LLM did not return valid JSON. Last output chars:\n{tail}") from exc

        if not str(data.get("summary", "")).strip():
            raise RuntimeError("LLM JSON missing summary")
        if not isinstance(data.get("key_points"), list) or not data["key_points"]:
            raise RuntimeError("LLM JSON missing key_points list")

        data["title"] = clean_title(str(data.get("title", ""))) or title_hint_clean or "Untitled"
        return data

    if len(text) <= no_chunk_max_chars:
        set_step(job_id, step_index(job_id, "Summarizing"), "Summarizing… (single pass)", 86)
        return call_llm_json(prompt_json_from_text(text))

    set_step(job_id, step_index(job_id, "Summarizing"), "Summarizing… (long transcript fallback)", 86)

    chunks = chunk_text(text)
    notes_parts = []
    total = len(chunks)

    for idx, chunk in enumerate(chunks, start=1):
        progress = 86 + int((idx / total) * 6)
        set_step(job_id, step_index(job_id, "Summarizing"), f"Summarizing… (chunk {idx}/{total})", progress)

        prompt_notes = f'''
Extract factual notes from this transcript chunk.

Rules:
- Output ONLY plain text.
- Do NOT add outside facts or examples.
- Keep numbers, names, URLs, and brand/site names EXACT.
- Prefer capturing more facts over fewer (redundancy is fine).

FACTS:
- ...

NUMBERS / DATES / PRICES:
- ...

STRATEGIES / STEPS:
- ...

TOOLS / COMMANDS / DEFINITIONS:
- ...

CHUNK:
"""{chunk}"""
'''.strip()

        notes_parts.append(run_command([OLLAMA, "run", OLLAMA_MODEL, prompt_notes]).strip())

    notes = "\n".join(notes_parts).strip()

    if len(notes) > NOTES_MAX_CHARS:
        set_step(
            job_id,
            step_index(job_id, "Summarizing"),
            "Summarizing… (compressing notes)",
            92,
        )

        prompt_compress = f'''
Condense these NOTES to under {NOTES_MAX_CHARS} characters.

Rules:
- Output ONLY plain text (no JSON, no markdown).
- Keep numbers, names, URLs, brands, dates, and key steps.
- Remove filler and redundancy but keep factual detail.

NOTES:
"""{notes}"""
'''.strip()

        compressed = run_command([OLLAMA, "run", OLLAMA_MODEL, prompt_compress]).strip()
        if compressed:
            notes = compressed

    set_step(job_id, step_index(job_id, "Summarizing"), "Summarizing… (finalizing)", 94)

    prompt_final = f'''
Create a clean summary for later reuse from NOTES.

1. Analyze CONTENT TYPE (Tax/Finance, AI/Apps, Coding, or General).
2. Hard rules:
- Output MUST be valid JSON only. No markdown. No extra text.
- Do NOT invent facts.
- If NOTES contain numbers, dates, prices, or versions, "key_points" MUST include them.
- "key_points" should be actionable (e.g., "Use tax form X", "Run command Y").
- Title must be clean: remove hashtags and trailing "..." (even if they appear in the hint).

Return ONLY JSON with EXACT keys:
{{
  "title": "clear concise title",
  "summary": "3-6 sentences describing content, context-aware",
  "key_points": ["10-16 bullets capturing the most useful points, prioritizing numbers/dates"]
}}

TITLE HINT: {title_hint_clean}
SOURCE: {source_label}

NOTES:
"""{notes}"""
'''.strip()

    return call_llm_json(prompt_final)


def write_md(
    job_id: str,
    source_label: str,
    custom_title: Optional[str],
    detected_title: str,
    summary_data: dict,
    text: str,
) -> tuple[Path, str, str]:
    set_step(job_id, step_index(job_id, "Writing markdown file"), "Writing markdown file…", 92)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chosen_title = resolve_title(custom_title, detected_title, summary_data.get("title"))

    safe = sanitize_filename(chosen_title)
    out_path = dedupe_path(OUTPUT_DIR / f"{safe}.md")

    md_lines = [
        f"# {chosen_title}\n",
        f"- **Source:** {source_label}",
        f"- **Saved:** {now}\n",
        "## Summary",
        (summary_data.get("summary") or "").strip() or "—",
        "",
        "## Key Points",
    ]

    key_points = summary_data.get("key_points") or []
    for point in key_points:
        bullet = str(point).strip()
        if bullet:
            md_lines.append(f"- {bullet}")
    if not key_points:
        md_lines.append("—")

    md_lines.extend([
        "",
        "## Original Content",
        text.strip() or "—",
    ])

    out_path.write_text("\n".join(md_lines), encoding="utf-8")
    return out_path, chosen_title, now


def write_md_transcript_only(
    job_id: str,
    source_label: str,
    custom_title: Optional[str],
    detected_title: str,
    text: str,
) -> tuple[Path, str, str]:
    set_step(job_id, step_index(job_id, "Writing markdown file"), "Writing markdown file…", 90)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chosen_title = resolve_title(custom_title, detected_title, None)

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


def build_clipboard_payload(
    *,
    title: str,
    source_label: str,
    saved_at: str,
    summary: str,
    key_points: list[str],
    text: str,
    transcript_only: bool,
) -> str:
    if transcript_only:
        return text.strip()

    summary_text = (summary or "").strip() or "—"
    cleaned_points = [str(point).strip() for point in key_points if str(point).strip()]
    text_content = text.strip() or "—"

    lines = [
        "Summary:",
        summary_text,
        "",
        "Key Points:",
    ]

    if cleaned_points:
        lines.extend([f"- {point}" for point in cleaned_points])
    else:
        lines.append("—")

    lines.extend([
        "",
        "Original Content:",
        text_content,
    ])

    return "\n".join(lines).strip()


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
    """Router for any job type"""
    try:
        if options.mode == "pdf":
            process_job_file(job_id, options)
        else:
            process_job_url(job_id, options)
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, state="error", stage_text="Failed", error=str(exc), progress=100)


def process_job_url(job_id: str, options: JobOptions):
    mp3, yt_title = download_audio(job_id, options.url)
    transcript = transcribe(job_id, mp3)
    
    _finalize_job(job_id, options, transcript, yt_title, options.url, "video")


def process_job_file(job_id: str, options: JobOptions):
    file_path = Path(options.file_path)
    if not file_path.exists():
        raise RuntimeError("File path missing")

    raw_text = extract_text_from_pdf(job_id, file_path)
    clean_text = clean_extracted_text(job_id, raw_text)
    
    # Use filename as title hint
    title_hint = file_path.stem
    source_label = file_path.name
    
    _finalize_job(job_id, options, clean_text, title_hint, source_label, "pdf")


def _finalize_job(
    job_id: str, 
    options: JobOptions, 
    text: str, 
    title_hint: str, 
    source_label: str,
    content_type: str
):
    if options.transcript_only:
        summary_data = {"summary": "", "key_points": [], "title": ""}

        if options.save_markdown:
            out_path, final_title, saved_ts = write_md_transcript_only(
                job_id, source_label, options.custom_title, title_hint, text
            )
        else:
            out_path = None
            final_title = resolve_title(options.custom_title, title_hint, None)
            saved_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        summary_data = summarize(job_id, title_hint, source_label, text, content_type)

        if options.save_markdown:
            out_path, final_title, saved_ts = write_md(
                job_id,
                source_label,
                options.custom_title,
                title_hint,
                summary_data,
                text,
            )
        else:
            out_path = None
            final_title = resolve_title(options.custom_title, title_hint, summary_data.get("title"))
            saved_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cleanup(job_id)

    clipboard_payload = build_clipboard_payload(
        title=final_title,
        source_label=source_label,
        saved_at=saved_ts,
        summary=(summary_data.get("summary") or ""),
        key_points=summary_data.get("key_points") or [],
        text=text,
        transcript_only=options.transcript_only,
    )
    
    steps = jobs[job_id].get("steps", STEPS) # could be PDF_STEPS

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
