# Security Policy

## Reporting a vulnerability

Transcription Studio is a small, self-hosted local web service. If you discover a vulnerability — a path-traversal, an SSRF in the URL ingestion path, an unsafe deserialization, or anything that could compromise a machine running this server — please report it privately rather than opening a public issue.

**Preferred channel**

[Open a private security advisory on GitHub.](https://github.com/fcttechnologies/TranscriptionStudio/security/advisories/new)

**Alternative**

Email **fernando@fct-technologies.com** with:

- a description of the issue,
- the version or commit you found it on,
- a minimal reproduction, and
- any suggested remediation.

You can expect an acknowledgement within a few business days. Reports that allow remote code execution, file disclosure, or other significant impact are prioritized.

## Scope

In scope:

- The Python backend (`backend/app/`).
- The static frontend (`frontend/`).
- The configuration and FFmpeg-detection layer (`backend/app/config.py`).

Out of scope:

- Upstream vulnerabilities in `faster-whisper`, `ctranslate2`, `yt-dlp`, or `FastAPI` — report those to the relevant projects directly. We will update pinned versions when fixes ship.
- Issues that require running the server intentionally exposed to the public internet with no authentication layer in front. The README and `SECURITY.md` are explicit that this is unsupported.

## Supported versions

Only the latest commit on `main` is supported.
