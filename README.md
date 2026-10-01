# YouTube-to-Shorts AI

Zero-cost tool: YouTube URL -> transcribe -> AI picks moments -> clip -> captions -> vertical shorts.

**Status: complete local pipeline with a job-based API and a frontend.** The full video is never downloaded - only the transcript (YouTube captions or audio-only + Whisper) and the byte ranges needed for each clip. Paste a URL in the browser UI (or call the API directly) and get vertical, captioned Shorts out.

## Stack
Python 3.10+, FastAPI, yt-dlp, FFmpeg, Whisper (faster-whisper), Google Gemini free tier. No local LLM, no paid services.

## Requirements
- Python 3.10 or newer
- FFmpeg installed and on your PATH (installed separately, see below)

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

## Run
```
uvicorn app.main:app --reload
```
Then open:
- **http://127.0.0.1:8000/app/ - the web UI** (paste a URL, pick a duration, watch it process, preview/download the Shorts)
- http://127.0.0.1:8000/docs - interactive API docs
- http://127.0.0.1:8000/health - liveness
- http://127.0.0.1:8000/status - what is installed/configured

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
leaner/faster setup.

## Layout
```
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
