# SummarizeVideosApp

SummarizeVideosApp downloads audio from a TikTok/YouTube URL, transcribes it with Whisper, summarizes it with an Ollama model, and saves a markdown file with the results.

## Feature highlights
- Simple web UI for submitting a video link and optional custom title.
- Progress tracking across download, transcription, summarization, and file writing steps.
- Markdown output includes URL, timestamp, summary, key points, and full transcript.
- Clipboard-ready text block for quick sharing.

## Quick-start (macOS, Python 3.12)

1) **Install Homebrew dependencies**

```bash
brew install python@3.12 ffmpeg yt-dlp whisper-cpp
brew install --cask ollama
```

`whisper-cpp` installs the `whisper-cli` binary; `ffmpeg` is required by `yt-dlp` for some downloads. After installing the Ollama app, launch it once so it starts the local service.

2) **Download a Whisper model** (default path: `~/models/ggml-base.en.bin`)

```bash
mkdir -p ~/models
curl -L -o ~/models/ggml-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

3) **Pull an Ollama model** (default fast profile: `qwen3:8b`; pro profile: `qwen2.5:14b`)

```bash
ollama pull qwen3:8b
ollama pull qwen2.5:14b   # optional "pro" preset
```

4) **Create a Python 3.12 virtual environment and install deps**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

5) **Run the server from Terminal**

```bash
source .venv/bin/activate
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and paste a video URL to summarize.

## Launching with `launchctl` (keeps the app running after login)

Create a LaunchAgent plist at `~/Library/LaunchAgents/com.summarizevideosapp.server.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.summarizevideosapp.server</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>-lc</string>
      <string>cd /path/to/SummarizeVideosApp && source .venv/bin/activate && uvicorn server:app --host 0.0.0.0 --port 8000</string>
    </array>
    <key>WorkingDirectory</key><string>/path/to/SummarizeVideosApp</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/summarizevideosapp.out.log</string>
    <key>StandardErrorPath</key><string>/tmp/summarizevideosapp.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>SVA_OUTPUT_DIR</key><string>${HOME}/Documents/SummarizedVideos</string>
      <key>SVA_TEMP_DIR</key><string>/tmp/summarizevideosapp</string>
      <key>WHISPER_MODEL_PATH</key><string>${HOME}/models/ggml-base.en.bin</string>
      <key>OLLAMA_MODEL_FAST</key><string>qwen3:8b</string>
      <key>OLLAMA_MODEL_PRO</key><string>qwen2.5:14b</string>
    </dict>
  </dict>
</plist>
```

Load and start it:

```bash
launchctl load ~/Library/LaunchAgents/com.summarizevideosapp.server.plist
launchctl start com.summarizevideosapp.server
```

Logs will accumulate in `/tmp/summarizevideosapp.*.log` as configured above.

## Configuration reference

The server reads environment variables at startup. Defaults are set near the top of `server.py`:

```python
# server.py
OUTPUT_DIR = Path(os.environ.get("SVA_OUTPUT_DIR", Path.home() / "Documents" / "SummarizedVideos"))
TEMP_DIR = Path(os.environ.get("SVA_TEMP_DIR", Path("/tmp") / "summarizevideosapp"))
WHISPER_MODEL = Path(os.environ.get("WHISPER_MODEL_PATH", Path.home() / "models" / "ggml-base.en.bin"))
```

Command paths also resolve from the environment before falling back to Homebrew defaults:

```python
# server.py
YT_DLP = resolve_command("YT_DLP", "/opt/homebrew/bin/yt-dlp")
WHISPER_CLI = resolve_command("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")
OLLAMA = resolve_command("OLLAMA_BIN", "/usr/local/bin/ollama")
```

### Adjusting folders or binaries
- **Prefer env vars**: Export `SVA_OUTPUT_DIR`, `SVA_TEMP_DIR`, `WHISPER_MODEL_PATH`, `YT_DLP`, `WHISPER_CLI`, or `OLLAMA_BIN` in your shell/LaunchAgent to point to custom locations.
- **If editing code instead**: update the lines shown above to hardcode your paths. Keep the `Path(...)` wrappers so directories are created automatically.
- **Different Homebrew prefixes**: on Intel macOS, `ollama` usually lives in `/usr/local/bin`; on Apple Silicon, `yt-dlp`/`whisper-cli` from Homebrew default to `/opt/homebrew/bin`. Override with env vars if your setup differs.

### Model presets
The UI offers "Fast" and "Pro" radio buttons. Their defaults come from environment variables with sane fallbacks:

```python
# server.py
MODEL_PRESETS = {
    "fast": os.environ.get("OLLAMA_MODEL_FAST", "qwen3:8b"),
    "pro": os.environ.get("OLLAMA_MODEL_PRO", "qwen2.5:14b"),
}
DEFAULT_MODEL_KEY = os.environ.get("OLLAMA_MODEL_DEFAULT", "fast")
```

Change `OLLAMA_MODEL_FAST`, `OLLAMA_MODEL_PRO`, or `OLLAMA_MODEL_DEFAULT` to point at your preferred local models.

## Notes and tips
- The UI displays the saved file path and also provides a text area for quick copying.
- Long transcripts are chunked along whitespace boundaries to keep context intact before summarization.
- Temporary files are cleaned up after each job; output files are kept in the configured output directory.
