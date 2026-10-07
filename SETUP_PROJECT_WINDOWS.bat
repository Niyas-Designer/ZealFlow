@echo off
setlocal
cd /d %~dp0
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
cd frontend
call npm install
cd ..
echo.
echo ZealFlow setup complete.
echo Run START_PROJECT_WINDOWS.bat, then add the API key from the ZealFlow sidebar.
pause
