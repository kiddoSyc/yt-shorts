🎬 YouTube Shorts AI

<p align="center"> <strong>Turn long YouTube videos into engaging Shorts with AI.</strong> </p>

<p align="center"> <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"> <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white"> <img src="https://img.shields.io/badge/Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white"> <img src="https://img.shields.io/badge/FFmpeg-Video-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"> </p>

<p align="center"> <a href="https://github.com/kiddoSyc/yt-shorts">Repository</a> · <a href="https://github.com/kiddoSyc/yt-shorts/issues">Issues</a> </p>

✨ What it does

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

uvicorn app.main:app --reload

Then open:

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
