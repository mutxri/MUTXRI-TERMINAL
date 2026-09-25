@echo off
rem One-click launcher for the MUTXRI TERMINAL Discord bot.
cd /d "%~dp0"
if not exist ".env" (
  echo [setup] .env is missing.
  echo   Copy .env.example to .env and paste your bot token, then run this again.
  pause
  exit /b 1
)
python -c "import discord" 2>nul || (
  echo [setup] Installing dependencies first...
  python -m pip install -r requirements.txt
)
echo Starting MUTXRI TERMINAL bot... keep this window open.
python bot.py
pause
