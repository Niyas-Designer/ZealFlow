@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo .venv not found. Run SETUP_PROJECT_WINDOWS.bat first.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env
start "ZealFlow Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
cd frontend
npm run dev
