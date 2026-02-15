# TranscribingApp

TranscribingApp is a lightweight web app that downloads audio from a TikTok or YouTube URL and transcribes it with OpenAI Whisper. It ships with a FastAPI backend and a static HTML/CSS/JS frontend so you can run everything locally.

## What’s included

- **Frontend**: A single-page UI to submit links and copy transcripts (`frontend/`).
- **Backend**: FastAPI server plus the download/transcription pipeline (`backend/`).

## Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended).
- **ffmpeg** installed and available on your `PATH`.
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

> ✅ **Verify installation**: Run `ffmpeg -version` to confirm the binary is on your PATH.

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

## Configuration

The app’s default configuration lives in `backend/app/config.py`:

- `TEMP_DIR`: Where downloaded audio and intermediate files are stored.
- `WHISPER_MODEL_NAME`: Whisper model size (e.g., `tiny`, `base`, `small.en`, `medium`, `large`).
- `FFMPEG_LOCATION`: Optional path added to `PATH` if ffmpeg isn’t discoverable.

If you change any of these, restart the server.

## Usage tips

- Make sure the video URL is publicly accessible.
- Larger Whisper models require more RAM and will run slower.
- The UI polls job status every ~800ms and updates the progress bar.

## Troubleshooting

**`ffmpeg` not found**
- Confirm `ffmpeg -version` works in the same shell you use to start Uvicorn.
- If you installed ffmpeg somewhere unusual, update `FFMPEG_LOCATION` in `backend/app/config.py`.

**`Download failed` or `Audio download failed`**
- Verify the URL opens in your browser.
- Some platforms block downloads or require authentication; use public URLs.

**Transcription is slow**
- Try a smaller model (e.g., `base` or `small.en`).
- Ensure your machine has enough RAM/CPU for Whisper.

## API endpoints

- `GET /` serves the static frontend.
- `POST /api/jobs/start` starts a new job (for video/website URLs). Body: `{ "url": "https://..." }`
- `GET /api/jobs/{job_id}` polls job progress and returns transcript data.
- `POST /api/transcribe/file` transcribes an uploaded audio file directly. Accepts multipart form with field `file`. Returns `{ "job_id": "...", "transcript": "...", "filename": "..." }`. Temp file is deleted after processing.

## Project structure

```
TranscribingApp/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── jobs.py
│   │   ├── main.py
│   │   └── pipeline.py
│   └── requirements.txt
└── frontend/
    ├── app.js
    ├── index.html
    └── styles.css
```

## Security & privacy

This project runs locally by default. The URLs you submit are fetched by your machine, and the audio/transcript is stored temporarily in `TEMP_DIR` until cleanup. Do not expose the server to the public internet unless you understand the security implications.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
