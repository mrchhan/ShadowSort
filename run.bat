@echo off
REM ShadowSort by Shadow Creative Studio - run from source (first run installs everything into .venv)
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
if /I "%1"=="ai" (
  pip install -r requirements-ai.txt
) else (
  pip install -q -r requirements.txt
)
python main.py
