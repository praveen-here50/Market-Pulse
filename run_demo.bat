@echo off
rem Start the sample-data demo at http://127.0.0.1:8502. It uses no real data or keys,
rem and can run beside the real MarketPulse. Close this window to stop it.

cd /d "%~dp0"
.venv\Scripts\python.exe -m streamlit run demo_app.py --server.port 8502
