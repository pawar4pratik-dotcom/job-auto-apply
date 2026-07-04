@echo off
title Job Auto-Apply Bot Portal
color 0A

echo.
echo  =====================================================
echo    JOB AUTO-APPLY BOT  ^|  Dashboard Launcher
echo  =====================================================
echo.

:: 1. Set Python Executable Path
set "PYTHON_EXE=C:\Users\Pratik\AppData\Local\Python\pythoncore-3.14-64\python.exe"

:: 2. Move to project folder
cd /d "C:\Users\Pratik\Downloads\job auto apply"

:: 3. Kill any stale Python process on port 5006
echo  [1/3] Clearing old processes on port 5006...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5006" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: 4. Install / verify dependencies fast
echo  [2/3] Checking dependencies...
"%PYTHON_EXE%" -c "import flask, selenium, webdriver_manager, undetected_chromedriver, fake_useragent, requests, bs4, pypdf, reportlab, apscheduler, google.generativeai, pdfminer, feedparser" >nul 2>&1
if errorlevel 1 (
    echo        Missing packages detected. Installing dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --disable-pip-version-check
) else (
    echo        Dependencies OK - Cached.
)

:: 5. Start Flask server directly
echo  [3/3] Starting Flask server on http://localhost:5006 ...
echo        (Keep this terminal window open while using the bot)
echo.

:: 6. Open browser
start http://127.0.0.1:5006

:: 7. Run Flask app directly
"%PYTHON_EXE%" -u app.py
