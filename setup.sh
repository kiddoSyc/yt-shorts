#!/usr/bin/env bash
# Linux / macOS / Git Bash: create venv and install dependencies.
set -e
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Done. Activate with: source .venv/bin/activate"
