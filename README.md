# TranscribingApp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/fcttechnologies/TranscribingApp/actions/workflows/ci.yml/badge.svg)](https://github.com/fcttechnologies/TranscribingApp/actions/workflows/ci.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)

A self-hosted web app that downloads audio from a public TikTok or YouTube URL — or from an uploaded media file — and transcribes it locally with [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (the CTranslate2 Whisper runtime). FastAPI backend, single-page static frontend, runs end-to-end on a single machine. No external API keys, no cloud calls, no audio leaves your device.

## Why this exists

Most one-link transcription tools either upload your audio to someone else's server, paywall the model, or both. TranscribingApp is the local-first alternative: paste a link, run Whisper on your own hardware, and get the transcript without anyone else seeing the audio. It is the engine behind FCT Technologies' internal media workflows and is published as a reusable reference for anyone who wants a small, readable, fully-local transcription service.

## Why Faster-Whisper

Faster-Whisper is a re-implementation of OpenAI's Whisper using [CTranslate2](https://github.com/OpenNMT/CTranslate2). For the same accuracy as the upstream `openai-whisper` package it delivers ~4× faster inference and ~2× lower memory use on CPU, with `int8` quantization that lets `base.en` run comfortably on a 16 GB Mac mini. CTranslate2 also makes CUDA acceleration a configuration change rather than a code change.

## What's included

- **Frontend** — single-page UI for submitting URLs, polling progress, and copying the transcript (`frontend/`).
- **Backend** — FastAPI app with a URL-job pipeline (yt-dlp → FFmpeg → Faster-Whisper) and a direct file-upload endpoint (`backend/`).
- **Tests** — `pytest` suite for the configuration and job-tracking layers (`tests/`).

## How it compares

| Tool | Local | Open source | One-link UI | Notes |
|---|---|---|---|---|
| TranscribingApp | yes | yes | yes | Local FastAPI server you self-host. Paste-a-link UI on top of Faster-Whisper. |
| `whisper.cpp` | yes | yes | no | C++ CLI; fastest CPU runtime but no built-in URL ingestion or UI. |
| MacWhisper | yes | no | yes (desktop app) | Polished macOS app; paid for advanced features; no headless API. |
| Apple Transcribe Audio | yes | no | yes (Notes/Voice Memos) | Built-in to iOS/macOS; no URL ingestion, no programmatic access. |
| OpenAI Whisper API | no | partial | no | Cloud, per-minute pricing, audio uploaded to OpenAI. |

TranscribingApp's niche: a small, scriptable, self-hosted web service that swallows URLs and media files. It is the only entry in the table that exposes a JSON API and runs Whisper locally without writing your own glue.

## Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended).
- **FFmpeg** installed and available on your `PATH`.
- **Git** (optional, for cloning the repo).

## Clone the repo

```bash
git clone https://github.com/fcttechnologies/TranscribingApp
cd TranscribingApp
```

## Install system dependencies

### macOS (Homebrew)

```bash
brew install ffmpeg
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

### Windows (Winget)

```powershell
winget install --id=Gyan.FFmpeg -e
```

> **Verify installation**: run `ffmpeg -version` to confirm the binary is on your PATH.

## Set up the backend

1) **Create and activate a virtual environment**

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
```

> **Windows PowerShell**
> ```powershell
> python -m venv backend\.venv
> .\backend\.venv\Scripts\Activate.ps1
> ```

2) **Install Python dependencies**

```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

## Run the server

```bash
source backend/.venv/bin/activate
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open the app in your browser:

```
http://localhost:8000
```

On first run, Faster-Whisper downloads the configured model into `~/.cache/huggingface/hub` (a few hundred MB for `base.en`). Subsequent starts reuse the cached model.

## Configuration

The app's default configuration lives in `backend/app/config.py`. Every value can be overridden with an environment variable of the same name — no code edits required. Copy `.env.example` to `.env` if you want a starting point.

| Variable | Default | Purpose |
|---|---|---|
| `TRANSCRIBINGAPP_TEMP_DIR` | `<system-temp>/transcribingapp/` | Where downloaded audio and intermediate files are stored. |
| `WHISPER_MODEL_NAME` | `base.en` | Faster-Whisper model: `tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v3`, etc. |
| `WHISPER_DEVICE` | `cpu` | Inference device (`cpu`, `cuda`, `auto`). |
| `WHISPER_COMPUTE_TYPE` | `int8` | Precision/quantization (`int8` for low-RAM CPU; `float16` for CUDA). |
| `FFMPEG_LOCATION` | auto-detect | Directory containing `ffmpeg`. Auto-detected via `shutil.which`, with fallbacks to `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`. Set explicitly only if FFmpeg lives somewhere unusual. |
| `LOG_LEVEL` | `INFO` | Standard Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

Example:

```bash
WHISPER_MODEL_NAME=small.en WHISPER_DEVICE=cuda \
  uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Restart the server after changing any of these.

## Architecture

```
                ┌──────────────────────────────────────────────┐
                │            Browser (static SPA)              │
                │   submit URL · poll progress · copy text     │
                └──────────────────────┬───────────────────────┘
                                       │  HTTP (JSON)
                ┌──────────────────────▼───────────────────────┐
                │                FastAPI app                   │
                │   /api/jobs/start  →  background task        │
                │   /api/jobs/{id}   →  poll job state         │
                │   /api/transcribe/file → upload + transcribe │
                └──────────────────────┬───────────────────────┘
                                       │
                ┌──────────────────────▼───────────────────────┐
                │             Pipeline (per job)               │
                │   yt-dlp ──► FFmpeg ──► Faster-Whisper       │
                │              (mp3)        (transcript)       │
                └──────────────────────┬───────────────────────┘
                                       │
                              <TEMP_DIR>/transcribingapp/
                                  (cleaned per job)
```

Jobs are tracked in an in-memory dict (`backend/app/jobs.py`) keyed by UUID. State resets on server restart. Completed/failed jobs are evicted after a 24-hour retention window. URL jobs run on FastAPI background tasks; file uploads transcribe inline and return the transcript in the response. The Whisper model is loaded once at import time and reused across jobs.

## Usage tips

- Make sure the video URL is publicly accessible.
- Larger Whisper models require more RAM and run slower.
- The UI polls job status every ~800 ms and updates the progress bar.

## Troubleshooting

**`ffmpeg` not found**
- Confirm `ffmpeg -version` works in the same shell you use to start Uvicorn.
- If FFmpeg is installed somewhere unusual, set `FFMPEG_LOCATION` to its directory.

**`Download failed` or `Audio download failed`**
- Verify the URL opens in your browser.
- Some platforms block downloads or require authentication; use public URLs.

**Transcription is slow**
- Try a smaller model (e.g., `tiny.en` or `base.en`).
- Use `WHISPER_COMPUTE_TYPE=int8` on CPU for lower RAM usage.
- On NVIDIA hardware, set `WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16`.

**Model download is slow on first run**
- Faster-Whisper pulls models from the Hugging Face Hub on first use. Set `HF_HUB_ENABLE_HF_TRANSFER=1` (after `pip install hf-transfer`) to speed it up.

## API endpoints

- `GET /` — serves the static frontend.
- `POST /api/jobs/start` — starts a URL job. Body: `{ "url": "https://..." }`. Returns `{ "job_id": "..." }`.
- `GET /api/jobs/{job_id}` — polls job progress and returns transcript data when `state == "done"`.
- `POST /api/transcribe/file` — transcribes an uploaded audio file directly. Multipart form, field `file`. Returns `{ "job_id": "...", "transcript": "...", "filename": "..." }`. The temp file is deleted after processing.

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

The included tests cover the configuration loader and the in-memory job store. The pipeline layer (yt-dlp + Faster-Whisper) is exercised end-to-end by running the server against real media; there are no recorded fixtures for it because the model and downloader are the integration surfaces that change most often.

## Project structure

```
TranscribingApp/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py        # Env-var-driven configuration
│   │   ├── jobs.py          # In-memory job store + step helpers
│   │   ├── main.py          # FastAPI entry point + routes
│   │   └── pipeline.py      # Download + transcribe + cleanup
│   └── requirements.txt
├── frontend/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── tests/
│   ├── test_config.py
│   └── test_jobs.py
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/ci.yml
├── .env.example
├── LICENSE
└── README.md
```

## Security & privacy

This project runs locally by default. The URLs you submit are fetched by your machine, and the audio/transcript is stored temporarily in `TEMP_DIR` until cleanup. Do not expose the server to the public internet unless you understand the security implications — there is no authentication on the API.

See [`SECURITY.md`](.github/SECURITY.md) for how to report security issues.

## Credits

- [OpenAI Whisper](https://github.com/openai/whisper) — original Whisper models and research.
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 re-implementation that powers transcription.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — media acquisition from URLs.
- [FastAPI](https://fastapi.tiangolo.com/) — backend framework.

## Related work

- [VoicePipeline](https://github.com/fcttechnologies/VoicePipeline) — FCT Technologies' end-to-end pipeline for training custom F5-TTS voice models. Uses the same Faster-Whisper runtime for word-level timestamps during dataset extraction.
- [fct-technologies.com/projects/transcribingapp/](https://fct-technologies.com/projects/transcribingapp/) — case study.

## License

MIT License. See [`LICENSE`](LICENSE) for details.
