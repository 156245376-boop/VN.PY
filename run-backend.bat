@echo off
cd /d "%~dp0backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8180 > "%~dp0backend\uvicorn.out.log" 2>&1
