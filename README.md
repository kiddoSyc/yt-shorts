# YouTube-to-Shorts AI

<<<<<<< HEAD
<p align="center"> <strong>Turn long YouTube videos into engaging Shorts with AI.</strong> </p>

<p align="center"> <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"> <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white"> <img src="https://img.shields.io/badge/Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white"> <img src="https://img.shields.io/badge/FFmpeg-Video-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"> </p>

<p align="center"> <a href="https://github.com/kiddoSyc/yt-shorts">Repository</a> · <a href="https://github.com/kiddoSyc/yt-shorts/issues">Issues</a> </p>
=======
Zero-cost tool: YouTube URL -> transcribe -> AI picks moments -> clip -> captions -> vertical shorts.

**Status: complete local pipeline with a job-based API and a frontend.** The full video is never downloaded - only the transcript (YouTube captions or audio-only + Whisper) and the byte ranges needed for each clip. Paste a URL in the browser UI (or call the API directly) and get vertical, captioned Shorts out.

## Stack
Python 3.10+, FastAPI, yt-dlp, FFmpeg, Whisper (faster-whisper), Google Gemini free tier. No local LLM, no paid services.
>>>>>>> 25ff75b (file update)

## Requirements
- Python 3.10 or newer
- FFmpeg installed and on your PATH (installed separately, see below)

<<<<<<< HEAD
YouTube Shorts AI takes a YouTube video, analyzes its transcript with AI, finds potential highlights, and automatically turns them into captioned 9:16 short-form videos.

YouTube URL
     ↓
Transcript / Whisper
     ↓
   Gemini AI
     ↓
Best Moments
     ↓
Clip Extraction
     ↓
Captions + 9:16
     ↓
   🎬 Short
🚀 Features
🤖 AI moment detection — finds interesting sections from the transcript
📝 Smart transcription — YouTube captions with Whisper fallback
✂️ Automatic clipping — extracts selected moments from the source
💬 Burned-in captions — makes clips ready for short-form platforms
📱 9:16 output — optimized for Shorts, TikTok and Reels
⏱️ Custom durations — configurable clip length from 15–180 seconds
⚡ FastAPI backend — lightweight API-based architecture
🐳 Docker ready — easy deployment to container platforms
☁️ Railway ready — built with cloud deployment in mind
🛠️ Built With

Python · FastAPI · yt-dlp · FFmpeg · faster-whisper · Gemini

⚡ Quick Start
git clone https://github.com/kiddoSyc/yt-shorts.git
cd yt-shorts

py -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Create a .env file:

AI_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=your_model

Start the server:
=======
## Install
**Windows**
```
setup.bat
.venv\Scripts\activate
```
**Linux / macOS / Git Bash**
```
./setup.sh
source .venv/bin/activate
```
Manual alternative: `python -m venv .venv`, activate it, `pip install -r requirements.txt`, then copy `.env.example` to `.env`.

### Install FFmpeg (manual)
- Windows: `winget install Gyan.FFmpeg` (then reopen the terminal)
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`

Check with `ffmpeg -version`.

### Gemini API key (free)
Create a key at https://aistudio.google.com/apikey and put it in `.env` as `GEMINI_API_KEY=...`.
Not needed to start the server in this step.
>>>>>>> 25ff75b (file update)

## Run
```
uvicorn app.main:app --reload
```
Then open:
- **http://127.0.0.1:8000/app/ - the web UI** (paste a URL, pick a duration, watch it process, preview/download the Shorts)
- http://127.0.0.1:8000/docs - interactive API docs
- http://127.0.0.1:8000/health - liveness
- http://127.0.0.1:8000/status - what is installed/configured

<<<<<<< HEAD
http://127.0.0.1:8000/docs
⚙️ Pipeline

The project is designed to avoid unnecessary processing of entire long-form videos whenever possible.

Captions available?
       │
   ┌───┴───┐
  YES      NO
   │        │
   ▼        ▼
Caption   Whisper
   │        │
   └───┬────┘
       ▼
   Gemini AI
       ↓
 Moment Selection
       ↓
 Video Processing
       ↓
 Captions + 9:16
       ↓
    Final MP4
📁 Project Status

🚧 Active development

The core processing pipeline is in place, with the API, transcription, AI analysis, clip generation, captions and vertical rendering being actively developed.

<p align="center"> <strong>🎥 YouTube → 📝 Transcript → 🤖 AI → ✂️ Moments → 💬 Captions → 📱 Shorts</strong> </p>

<p align="center"> Made with ❤️ by <strong>kiddoSyc</strong> </p>
=======
Visiting `http://127.0.0.1:8000/` (no path) redirects to `/app/`.

## Configuration
All settings live in `.env` (see `.env.example`). Notable ones: `MAX_VIDEO_HEIGHT` (default 720 - the
source resolution downloaded per clip; higher means a sharper Short since clips get upscaled to
1080x1920, at the cost of more data), `WHISPER_MODEL_SIZE` (default `small` - bigger models transcribe
more accurately, at the cost of speed: tiny < base < small < medium < large), `VIDEO_CRF`/`VIDEO_PRESET`
(default 17/`fast` - lower crf and a slower preset both raise encode quality, at the cost of time/file
size), `AI_PROVIDER`, `SHORTS_WIDTH`/`SHORTS_HEIGHT` (default 1080x1920), `CAPTIONS_ENABLED`, and the
`CAPTION_*` styling options. Defaults are tuned for quality over minimum data/CPU use; lower
`MAX_VIDEO_HEIGHT`, raise `VIDEO_CRF`, or use a smaller `WHISPER_MODEL_SIZE` to go back to a
leaner/faster setup. `YTDLP_COOKIES_FILE`/`YTDLP_COOKIES_CONTENT` are usually required on cloud
hosts - see "Deploying" below.

## Layout
```
Dockerfile, .dockerignore   container build for Railway/other cloud hosts (see "Deploying")
app/
  main.py            FastAPI app, error handlers
  config.py          .env settings
  logging_config.py  console + logs/app.log
  exceptions.py      error types -> HTTP codes
  models.py          Transcript, Moment
  api/
    routes.py           /health, /status, /process (synchronous)
    jobs_routes.py       /jobs, /files/*, /jobs/{id}/download-all (the job-based API the frontend uses)
    schemas.py            request bodies + validation
  services/
    downloader.py      URL validation, FFmpeg check, metadata/audio-only/section helpers, full download (legacy)
    youtube_transcript.py  YouTube captions -> transcript
    session.py         clip_duration validation, sessions
    pipeline.py        the low-data pipeline
    transcription.py   faster-whisper -> timestamped segments -> JSON
    moment_detection/  base interface, Gemini provider, provider-independent parsing/validation
    clipping.py         FFmpeg clip extraction -> data/clips/
    captions.py          transcript -> wrapped, timed captions -> .ass subtitle files
    shorts.py             vertical (9:16) crop + burned-in captions -> data/shorts/
    jobs.py                in-memory background job runner (JobManager) used by /jobs
frontend/
  index.html, styles.css, app.js   plain HTML/CSS/JS UI, served at /app - talks only to this API
data/
  downloads/, transcripts/  cached YouTube data (git-ignored)
  clips/                    raw cut clips, original aspect ratio (git-ignored)
  shorts/                   final vertical, captioned Shorts (git-ignored)
  output/                   moments JSON, pipeline reports (git-ignored)
logs/                       app.log (git-ignored)
```

## Tests
```
pip install -r requirements-dev.txt
pytest
```
Tests use fakes: no network, no model download, no real video needed. `tests/test_jobs.py` and
`tests/test_jobs_routes.py` cover the job manager and the `/jobs`, `/files`, `/jobs/{id}/download-all`
endpoints. `tests/test_pipeline.py` and `tests/test_full_flow.py` run the real pipeline with real FFmpeg
against a local fake video server (real network calls are still faked) and are slower.

## Low-data pipeline (current)
```
YouTube URL -> YouTube captions (else audio-only + Whisper) -> Gemini timestamps
            -> FFmpeg cuts only those ranges from the remote stream -> data/clips/
```
- Each session has a `clip_duration` (30, 40, 60 or a custom whole number, 15-180 s; set `CLIP_DURATION_MIN/MAX` in `.env`). Gemini is asked for moments that naturally fit it without cutting sentences.
- Transcript: YouTube captions (a few KB). If none, only the audio track is downloaded, transcribed locally with faster-whisper, and the temporary audio is deleted. `TRANSCRIPT_SOURCE=auto|captions|whisper`.
- Clips: FFmpeg reads just the needed byte ranges over HTTP (never the whole file). If that fails for a clip, yt-dlp's own section download is used for that clip.
- Captions: built from the same transcript (YouTube captions or Whisper), so both sources are supported automatically. Rendered as an `.ass` file and burned in with FFmpeg's `subtitles` filter - bold white text, black outline, positioned with a safe margin above the bottom edge so it clears typical Shorts/Reels/TikTok UI. Segments that straddle a clip's start/end are trimmed proportionally, and long segments are split into several shorter, better-timed captions. If a clip has no speech in its range, it's still formatted, just without captions. Set `CAPTIONS_ENABLED=false` to skip captions entirely.
- Vertical formatting: each raw clip in `data/clips/` is scaled to cover 1080x1920 and center-cropped - no letterboxing, minimal quality loss, audio copied (not re-encoded) so it stays in sync. Output goes to `data/shorts/<clip name>_short.mp4`, kept separate from the raw clips. A center crop keeps typical talking-head footage in frame; content pinned hard against one edge of a wide source can lose that edge.
## Job-based API (what the frontend uses)
`POST /process` blocks until the whole pipeline finishes - fine for scripts, awkward for a UI. The job API
runs the pipeline in the background and lets you poll progress:

1. `POST /jobs` `{"url": "...", "clip_duration": 40, "num_clips": 3}` -> `{"job_id": "...", "status": "queued", ...}`.
   Both fields are optional (server defaults from `.env` apply). `num_clips` caps how many Shorts to make;
   Gemini still chooses which moments.
2. `GET /jobs/{job_id}` -> poll this. `status` is `queued` / `running` / `completed` / `failed`. While
   running, `stage` (`transcript`, `moments`, `clipping`, `formatting`, ...) and `progress`
   (`{"done": i, "total": n}` during clipping/formatting) show what's happening. On `completed`, the full
   result (same shape as `/process`'s response) is included under `result`. On `failed`, `error` has the message.
3. `GET /jobs/{job_id}/shorts` -> the final vertical, captioned Shorts with ready-to-use download URLs
   (empty list until the job completes).
4. `GET /jobs/{job_id}/clips` -> the raw (pre-formatting) clips, same shape.
5. `GET /files/shorts/{filename}` / `GET /files/clips/{filename}` -> stream/download one file (also usable
   directly as a `<video src>` for in-browser preview).
6. `GET /jobs/{job_id}/download-all` -> a `.zip` of every Short from that job.
7. `GET /jobs` -> recent jobs, newest first (in-memory only - cleared on server restart; the cached
   transcripts/clips on disk are unaffected and get reused on the next request for the same video).

Jobs run one at a time (a single background worker), which keeps a local, single-user setup predictable -
a second job just waits its turn rather than fighting the first one over CPU/FFmpeg.

Live test with a real URL (needs GEMINI_API_KEY):
```
python -m scripts.test_pipeline "https://www.youtube.com/watch?v=VIDEO_ID" --durations 30 40 60
```

## Try the local-file flow (older, uses an already-downloaded video)
```
python -m scripts.test_flow
```
Takes the newest transcript in `data/transcripts/`, asks Gemini for moments (text only), and cuts clips into `data/clips/`.

## Frontend
Plain HTML/CSS/JS in `frontend/`, served by this same FastAPI app at `/app` (`app.mount`, no build step,
no framework). It only calls this server's own API (`/jobs`, `/files/*`) - no processing logic is
duplicated in the browser.

- Paste a URL, pick a duration (30/40/60 or Custom, 15-180s), optionally pick a clip count, click
  **Generate Shorts**.
- A progress bar polls `GET /jobs/{id}` every 2s and shows the current stage (transcript, moment
  detection, clipping i/n, formatting i/n).
- On completion, each Short is shown in a `<video controls>` preview with its own **Download** link, plus
  a **Download all (.zip)** button.
- Handles: invalid URL (client-side check + server 400), invalid duration/clip count (422 with a message),
  a failed job (error card with the reason, "Try again"), lost connection during polling, and a completed
  job that produced zero Shorts (empty-state message rather than a blank grid).
- If you'd rather open it standalone (not via `/app`) during development, any static file server pointed
  at `frontend/` works, as long as this API is reachable and CORS is enabled - CORS is on automatically
  when `APP_ENV=development` (the default). Tighten `allow_origins` in `app/main.py` before hosting anywhere shared.

## Swapping the AI provider
Subclass `MomentDetector` in `app/services/moment_detection/`, register it in `get_moment_detector()`, and set `AI_PROVIDER`.

## Deploying (Railway, a VPS, or similar)
A `Dockerfile` is included - Railway and most PaaS hosts auto-detect it and build/run the app
directly. It installs FFmpeg, the `DejaVu Sans` caption font, and `deno` (see below), and
binds to `0.0.0.0:$PORT` using whatever port the platform assigns at runtime.

**YouTube will very likely block the server at first - this is expected on any cloud host,**
not specific to this project. Two separate problems show up together, both visible in the
server logs:

1. **`No supported JavaScript runtime could be found`** - yt-dlp needs a JS runtime (`deno`)
   installed to extract current YouTube video info reliably. The `Dockerfile` installs it, so
   this is fixed automatically as long as you deploy from the Dockerfile (not a bare
   `pip install` on a host that skips it).
2. **`Sign in to confirm you're not a bot` / HTTP 429 Too Many Requests** - YouTube treats
   shared datacenter IPs (Railway, most VPS providers, etc.) with suspicion, independent of
   the JS runtime fix above. The reliable fix is giving yt-dlp cookies from a real, logged-in
   YouTube session:
   1. On your own computer, while logged into YouTube in Chrome/Firefox, export cookies with a
      browser extension such as "Get cookies.txt LOCALLY" (search your browser's extension
      store) - save it as `cookies.txt`.
   2. On the host: either put that file on the server and set `YTDLP_COOKIES_FILE=/path/to/cookies.txt`,
      or - if the host has no persistent file storage (Railway's default) - open `cookies.txt`
      in a text editor, copy its full contents, and paste them into the `YTDLP_COOKIES_CONTENT`
      environment variable. The app writes it to a file automatically on startup.
   3. Use a throwaway/secondary Google account for this, not your main one - treat the cookie
      file like a password (anyone with it can access that account), and expect to need to
      refresh it occasionally as cookies expire.

Without cookies configured, expect intermittent failures under real traffic even with the JS
runtime fixed - this is YouTube's anti-bot behavior on cloud IPs, not a bug in the app.
Every job failure includes the specific reason in its `error` field so you can tell these
apart from an actually-unavailable or age-restricted video.

`/status` reports whether cookies are configured and valid under `checks.cookies`, without ever
exposing the cookie values themselves - check it first if downloads are failing.

**If transcription fails with `TypeError: open() got an unexpected keyword argument
'metadata_errors'`**: this is a dependency version mismatch, not a config issue - PyAV
(the `av` package) removed that parameter in v19.0.0, which breaks faster-whisper's internal
call to it. `requirements.txt` pins `av<19.0.0` to avoid this; if you see this error, your
environment likely installed from a stale `requirements.txt` or bypassed the pin somehow -
reinstall dependencies from the current `requirements.txt`.

**If vertical formatting fails with a vague `FFmpeg failed while formatting` and no real reason**:
the app now reports the FFmpeg exit code in this message, and specifically calls out when it
looks like the OS killed FFmpeg for using too much memory (exit code `-9`/`137` with empty
output - this is what "out of memory" looks like from a subprocess, since the process is killed
before it can print anything). This is common on small cloud plans (512MB-1GB RAM): the
1080x1920 encode + caption burn-in is the most memory-hungry step in the pipeline. If you see
this, either upgrade the plan's RAM, or trade quality for headroom in `.env`:
`MAX_VIDEO_HEIGHT` (lower = less memory for the upscale), `WHISPER_MODEL_SIZE` (smaller = less
memory during transcription), or `VIDEO_PRESET=veryfast` (uses less memory than `fast`/`medium`
at the same crf, though with slightly larger output files).

## Data usage
- The full video is never downloaded - only the transcript and the FFmpeg byte-ranges needed for each clip.
- Only transcript text is sent to the AI API (Gemini), never video or audio.
- The Whisper model downloads once, on the first transcription run (not during install).
- Captions and vertical formatting run entirely on the already-local clip files, so they use no extra network data.
- The job API adds no network use of its own - it wraps the same pipeline described above.

## Known limitations
- Jobs are stored in memory only - restarting the server loses job history/progress (cached transcripts
  and clips on disk are unaffected). Fine for local single-user use; would need a real job store (e.g. a
  small database) before hosting for multiple people.
- One job runs at a time by design (see "Job-based API" above) - intentional for a local low-spec PC, but
  means a second person's request would queue behind the first if this were ever exposed to more than one user.
- Vertical formatting does a second FFmpeg re-encode pass on top of clipping's own encode (needed to burn
  in captions and crop to 9:16), so total processing time is roughly clip-length x (1 to 2), depending on
  your CPU. The current quality-focused defaults (720p source, `small` Whisper, crf 17) push this further
  than the original low-data defaults - expect noticeably longer processing per video than earlier builds.
  Lower `MAX_VIDEO_HEIGHT`/`WHISPER_MODEL_SIZE` or raise `VIDEO_CRF` to trade quality back for speed.
- A center crop can lose content pinned hard to one edge of a wide shot (see "Low-data pipeline" above).
- No word-level caption timing (see "Low-data pipeline" above) - captions are readable and synced per
  sentence/phrase, not karaoke-precise.
>>>>>>> 25ff75b (file update)
