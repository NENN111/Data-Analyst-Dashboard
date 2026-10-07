@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Install the project first: python -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
if not exist ".env" (
    echo Create .env and set DATABASE_URL to your Neon PostgreSQL connection string.
    pause
    exit /b 1
)
if not defined DASHBOARD_FETCH_PAGE_SIZE set "DASHBOARD_FETCH_PAGE_SIZE=50"
if not defined DASHBOARD_FETCH_WORKERS set "DASHBOARD_FETCH_WORKERS=1"
if not defined DASHBOARD_CACHE_TTL_SECONDS set "DASHBOARD_CACHE_TTL_SECONDS=3600"
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
if errorlevel 1 pause
