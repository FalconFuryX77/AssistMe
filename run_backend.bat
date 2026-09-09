@echo off
title AssistMe Backend Server
echo Starting AssistMe Backend on http://0.0.0.0:8000...
cd /d "%~dp0backend"
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
pause
