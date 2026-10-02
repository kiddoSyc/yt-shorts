# Runs the FastAPI app + FFmpeg + Whisper + a JS runtime (deno), for cloud hosts like Railway.
# yt-dlp needs a JS runtime to extract YouTube video info reliably (deno is yt-dlp's
# built-in-supported runtime) - without it, YouTube extraction fails or gets flagged as a bot.
FROM python:3.12-slim

# ffmpeg: video processing. fonts-dejavu-core: the caption font (app/services/captions.py
# uses "DejaVu Sans"); without it libass silently falls back to a generic font.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno (yt-dlp's supported JS runtime - see https://github.com/yt-dlp/yt-dlp/wiki/EJS).
# Installed to /usr/local/bin so it's on PATH for every user/process.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs

# Railway (and most PaaS hosts) inject $PORT at runtime and route traffic to it - the app
# must bind 0.0.0.0:$PORT, not 127.0.0.1, or the platform can't reach it.
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
