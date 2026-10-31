@echo off
rem Back up the database, then start the API, dashboard and n8n in minimized windows.
rem Close those windows to stop them. Each listens only on this computer.
rem Anything set before running this wins, so a test copy can use its own ports.

cd /d "%~dp0"
if not defined MARKETPULSE_API_PORT set "MARKETPULSE_API_PORT=8000"
if not defined MARKETPULSE_DASHBOARD_PORT set "MARKETPULSE_DASHBOARD_PORT=8501"
if not defined MARKETPULSE_API_URL set "MARKETPULSE_API_URL=http://127.0.0.1:%MARKETPULSE_API_PORT%"

.venv\Scripts\python.exe backup_data.py

start "MarketPulse API" /min .venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port %MARKETPULSE_API_PORT%
start "MarketPulse dashboard" /min .venv\Scripts\python.exe -m streamlit run dashboard.py --server.port %MARKETPULSE_DASHBOARD_PORT%
start "MarketPulse n8n" /min cmd /c automation\start_n8n.bat start
