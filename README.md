🎬 YouTube Shorts AI

<p align="center"> <b>Turn long YouTube videos into engaging Shorts with AI.</b> </p>

<p align="center"> <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"> <img src="https://img.shields.io/badge/FastAPI-0.1+-009688?style=for-the-badge&logo=fastapi&logoColor=white"> <img src="https://img.shields.io/badge/Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white"> <img src="https://img.shields.io/badge/FFmpeg-Video-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"> </p>

<p align="center"> <a href="https://github.com/kiddoSyc/yt-shorts">GitHub</a> · <a href="https://github.com/kiddoSyc/yt-shorts/issues">Issues</a> </p>

✨ What it does

YouTube Shorts AI automatically finds interesting moments in YouTube videos and turns them into vertical short-form content.

YouTube Video
      ↓
   Transcript
      ↓
   Gemini AI
      ↓
 Best Moments
      ↓
 Clip + Captions
      ↓
    9:16 Short
🚀 Features
🤖 AI-powered moment detection
📝 Whisper transcription
✂️ Automatic clip extraction
💬 Automatic captions
📱 9:16 vertical videos
⚡ FastAPI backend
🐳 Docker support
☁️ Railway deployment ready
🛠️ Built With

Python · FastAPI · yt-dlp · FFmpeg · Whisper · Gemini

⚡ Quick Start
git clone https://github.com/kiddoSyc/yt-shorts.git
cd yt-shorts

py -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Create .env:

AI_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=your_model

Run:

uvicorn app.main:app --reload

Then open:

http://127.0.0.1:8000/docs

<p align="center"> <b>🎥 YouTube → 🤖 AI → ✂️ Clips → 💬 Captions → 📱 Shorts</b> </p>

<p align="center"> Made with ❤️ by <b>kiddoSyc</b> </p>
