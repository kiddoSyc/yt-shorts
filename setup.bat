@echo off
REM Windows: create venv and install dependencies.
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || exit /b 1
if not exist .env copy .env.example .env
echo Done. Activate with: .venv\Scripts\activate
