# SummarizeVideosApp

SummarizeVideosApp downloads audio from a TikTok/YouTube URL, transcribes it with Whisper, summarizes it with an Ollama model, and saves a markdown file with the results.

## Features
- Simple web UI for submitting a video link and optional custom title.
- Progress tracking across download, transcription, summarization, and file writing steps.
- Markdown output includes URL, timestamp, summary, key points, and full transcript.
- Clipboard-ready text block for quick sharing.

## Requirements
- Python 3.11+
- External tools:
  - `yt-dlp` (for audio download)
  - `whisper-cli` plus a Whisper model file (default: `~/models/ggml-base.en.bin`)
  - `ollama` with a locally available model (default: `qwen3:8b`)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Configuration
- `SVA_OUTPUT_DIR` (default: `~/Documents/SummarizedVideos`): where markdown files are written.
- `SVA_TEMP_DIR` (default: `/tmp/summarizevideosapp`): working directory for intermediate files.
- `WHISPER_MODEL_PATH`: override the Whisper model location.
- `YT_DLP`: path or command name for `yt-dlp`.
- `WHISPER_CLI`: path or command name for `whisper-cli`.
- `OLLAMA_BIN`: path or command name for the `ollama` binary.
- `OLLAMA_MODEL`: model name to run (default: `qwen3:8b`).

These values are resolved at startup; the server raises a clear error if required binaries cannot be found.

## Running the server

Start FastAPI with uvicorn:

```bash
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` and paste a video URL to summarize.

## Notes and tips
- The UI displays the saved file path and also provides a text area for quick copying.
- Long transcripts are chunked along whitespace boundaries to keep context intact before summarization.
- Temporary files are cleaned up after each job; output files are kept in the configured output directory.
