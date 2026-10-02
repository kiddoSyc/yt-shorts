🎬 YouTube Shorts AI

<p align="center"> <img src="https://img.shields.io/badge/AI-Powered-8A2BE2?style=for-the-badge"> <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"> <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white"> <img src="https://img.shields.io/badge/FFmpeg-Video-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"> </p>

<p align="center"> <strong>From long-form videos to ready-to-post Shorts.</strong> <br> AI finds the moments. The pipeline does the rest. </p>

<p align="center"> <a href="#-overview">Overview</a> • <a href="#-features">Features</a> • <a href="#-how-it-works">How It Works</a> • <a href="#-installation">Installation</a> • <a href="#-configuration">Configuration</a> </p>

🧠 Overview

YouTube Shorts AI is an automated short-form video generation pipeline built around FastAPI, Gemini, Whisper, yt-dlp and FFmpeg.

Give it a YouTube URL and a target clip duration.

The system handles the rest:

Transcript → AI analysis → moment detection → clip extraction → captions → 9:16 video

The goal is to make turning long-form content into Shorts fast, automated and low-bandwidth friendly.

✨ Features
🤖 AI Moment Detection

Gemini analyzes the available transcript and identifies sections that could work well as short-form content.

Instead of simply cutting a video every 60 seconds, the system attempts to understand what is actually being said before selecting moments.

🎙️ Smart Transcription

The pipeline can use existing YouTube captions when available and fall back to Whisper transcription when necessary.

YouTube Captions
      │
      └── available ──→ Use transcript
      │
      └── unavailable ─→ Whisper
✂️ Automatic Clip Generation

Once moments are selected, the corresponding timestamps are converted into actual video clips.

Clip duration can be controlled within configured limits.

📱 Vertical Shorts

Source footage is processed into a 9:16 vertical format, designed for:

YouTube Shorts
TikTok
Instagram Reels
💬 Captions

Generated transcripts can be converted into burned-in captions so viewers can follow the video without relying on audio.

⚡ API First

The backend is built with FastAPI, making the processing pipeline accessible through HTTP endpoints and easy to connect to a future frontend.

🔥 How It Works
                    ┌──────────────────┐
                    │   YouTube URL    │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │    Metadata      │
                    │     Fetch        │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   Transcript     │
                    │ Captions / Whisper│
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   Gemini AI      │
                    │ Moment Detection │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Timestamp / Clip │
                    │    Selection     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │     FFmpeg       │
                    │ Video Processing │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Captions + 9:16  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   Final Short    │
                    └──────────────────┘
🏗️ Architecture
                    ┌───────────────┐
                    │   FastAPI     │
                    │      API      │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
         Transcript      AI Engine     Video Engine
              │             │             │
              ▼             ▼             ▼
          Whisper         Gemini        FFmpeg
              │             │             │
              └─────────────┼─────────────┘
                            │
                            ▼
                       Short Output

The components are kept modular so individual processing stages can be improved without rebuilding the entire application.

🛠️ Tech Stack
Technology	Role
Python	Core application
FastAPI	REST API
yt-dlp	YouTube handling
Gemini	AI moment detection
faster-whisper	Speech-to-text
FFmpeg	Video processing
Pydantic	Configuration & validation
Docker	Deployment
Railway	Hosting
📂 Project Structure
yt-shorts/
│
├── app/
│   ├── api/
│   ├── core/
│   ├── services/
│   └── main.py
│
├── scripts/
│   └── test_pipeline.py
│
├── data/
│   ├── downloads/
│   ├── transcripts/
│   └── output/
│
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
⚙️ Installation
1. Clone
git clone https://github.com/kiddoSyc/yt-shorts.git
cd yt-shorts
2. Create environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1
3. Install dependencies
pip install -r requirements.txt
4. Install FFmpeg

Make sure FFmpeg is installed and available in your system PATH.

Verify:

ffmpeg -version
🔐 Configuration

Create a .env file:

AI_PROVIDER=gemini

GEMINI_API_KEY=your_api_key
GEMINI_MODEL=your_model

CLIP_DURATION_DEFAULT=60
CLIP_DURATION_MIN=15
CLIP_DURATION_MAX=180

MAX_MOMENTS=5
CAPTION_MARGIN_V=260
Configuration Overview
Variable	Purpose
AI_PROVIDER	Selects the AI processing provider
GEMINI_API_KEY	Gemini authentication
GEMINI_MODEL	Model used for analysis
CLIP_DURATION_DEFAULT	Default clip length
CLIP_DURATION_MIN	Minimum clip length
CLIP_DURATION_MAX	Maximum clip length
MAX_MOMENTS	Maximum detected moments
CAPTION_MARGIN_V	Caption vertical position

Never commit .env or API keys to GitHub.

▶️ Running

Start the development server:

uvicorn app.main:app --reload

API:

http://127.0.0.1:8000

Interactive documentation:

http://127.0.0.1:8000/docs

Health check:

http://127.0.0.1:8000/health
🧪 Pipeline Testing

The project includes a pipeline testing utility.

Example:

python -m scripts.test_pipeline "YOUTUBE_URL" --durations 30 --source whisper --fresh

This allows individual processing runs to be tested without relying on the full production interface.

Generated reports are stored in:

data/output/
🎞️ Output

A typical processing run looks like:

Input
│
├── YouTube URL
│
▼
Processing
│
├── Transcript
├── AI analysis
├── Selected timestamps
├── Video extraction
├── Caption generation
└── 9:16 conversion
│
▼
Output
│
└── short.mp4

The final video is optimized around the vertical short-form format.

🐳 Docker

Build:

docker build -t yt-shorts .

Run:

docker run -p 8000:8000 --env-file .env yt-shorts

The Docker image includes the system dependencies required for video processing.

☁️ Deployment

The application is designed to run in container-based environments.

Example deployment flow:

GitHub
   │
   ▼
Railway
   │
   ▼
Docker
   │
   ▼
FastAPI
   │
   ├── Gemini
   ├── Whisper
   ├── yt-dlp
   └── FFmpeg

Production secrets should be configured through the hosting platform's environment-variable system.

⚠️ YouTube Limitations

YouTube can apply rate limits, bot detection, authentication requirements, age restrictions, or other access controls to automated requests.

For example:

HTTP 429
Sign in to confirm you're not a bot

These conditions are controlled by YouTube and can change independently of this project.

🗺️ Roadmap
Core

YouTube processing

Transcript pipeline

Whisper fallback

Gemini integration

AI moment detection

Clip extraction

Caption generation

9:16 conversion

FastAPI backend

Docker support

Next

Web interface

Real-time processing progress

Background job queue

Multiple caption styles

Automatic titles

Automatic descriptions & hashtags

More AI providers

Cloud storage

User accounts

🤝 Contributing

Contributions and ideas are welcome.

git checkout -b feature/my-feature
git add .
git commit -m "Add my feature"
git push origin feature/my-feature

Then open a Pull Request.

📜 Disclaimer

This project is intended for legitimate content-processing and development purposes.

Users are responsible for ensuring they have the necessary rights or permissions to process and redistribute content.

👤 Author

<p align="center">

kiddoSyc

Building tools around AI, automation and media.

<br>

⭐ If you find this project useful, consider starring the repository.

</p>

<p align="center"> <sub> YouTube → Transcript → AI → Moments → Clips → Captions → Shorts </sub> </p>
