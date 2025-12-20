# TranscribingApp

TranscribingApp downloads audio from a TikTok/YouTube URL, transcribes it with Whisper, and can optionally save a markdown file with the results.

## Project layout
- `frontend/`: static HTML/CSS/JS for the single-page UI.
- `backend/`: FastAPI app code (`backend/app`) and Python dependencies (`backend/requirements.txt`).

## Feature highlights
- Simple web UI for submitting a video link and optional custom title.
- Markdown output (when enabled) includes URL, timestamp, and full transcript.
- Toggle to skip markdown file creation (off by default) if you only want the clipboard-ready text.
- Clipboard-ready text block for quick sharing.

## Quick-start (macOS, Python 3.14)

1) **Install Homebrew dependencies**

```bash
brew install ffmpeg

3) **Create a Python 3 virtual environment and install deps**

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

4) **Run the server from Terminal**

```bash
source backend/.venv/bin/activate
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and paste a video URL to transcribe.

## Launching with `launchctl` (keeps the app running after login)

Create a LaunchAgent plist at `~/Library/LaunchAgents/com.transcribingapp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.transcribingapp</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/fernando7ct/Projects/TranscribingApp/backend/.venv/bin/python3</string>
      <string>-m</string>
      <string>uvicorn</string>
      <string>backend.app.main:app</string>
      <string>--host</string><string>0.0.0.0</string>
      <string>--port</string><string>8000</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/fernando7ct/Projects/TranscribingApp</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
  </dict>
</plist>
```

You are definitely **not** on `fernando7ct`’s machine, so update these before loading:

```bash
# Point to your venv's Python (check with: source backend/.venv/bin/activate && which python3)
/Users/fernando7ct/Projects/TranscribingApp/backend/.venv/bin/python3

# Point to your clone directory
/Users/fernando7ct/Projects/TranscribingApp

# Change port if 8000 is in use
--port
8000
```

Load plist file and start server:

```bash
launchctl load ~/Library/LaunchAgents/com.transcribingapp.plist
launchctl start com.transcribingapp
```

## Configuration reference

Key paths are hardcoded near the top of `backend/app/config.py`. Change these variables if you want different locations or binaries:

```python
# backend/app/config.py
OUTPUT_DIR = Path.home() / "Documents" / "TranscribedFiles"
TEMP_DIR = Path("/tmp") / "transcribingapp"
WHISPER_MODEL_NAME = "small.en"
```

### Adjusting folders or binaries
- Keep the `Path(...)` wrappers so directories are created automatically.
- `WHISPER_MODEL_NAME` can be changed to other Whisper model sizes (e.g., "medium", "large").
- If you prefer environment variables, point the plist to a small shell script that exports them before launching `uvicorn`.

### Verifying your binaries
- `which python3` and `which uvicorn` should match what is in `backend/app/config.py` and the plist.
- If you use a different Python version/venv, update both the plist `ProgramArguments` and the `pip install` step to match.
- When changing the port or host, update both the plist and wherever you visit the UI (e.g., `http://localhost:9000`).

## Notes and tips
- The UI displays the saved file name and also provides a text area for quick copying.
- Temporary files are cleaned up after each job; output files are kept in the configured output directory.