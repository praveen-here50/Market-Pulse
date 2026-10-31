@echo off
rem Start n8n for MarketPulse. It listens only on this computer, like the API.
rem Anything set before running this wins, so a test copy can use its own folder and ports.

if not defined N8N_USER_FOLDER set "N8N_USER_FOLDER=%~dp0..\data\n8n"
if not defined N8N_PORT set "N8N_PORT=5678"
if not defined MARKETPULSE_API_URL set "MARKETPULSE_API_URL=http://127.0.0.1:8000"

set "N8N_LISTEN_ADDRESS=127.0.0.1"
set "N8N_HOST=127.0.0.1"

rem Portfolio data passes through n8n, so nothing is reported back to its makers.
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N_VERSION_NOTIFICATIONS_ENABLED=false"

rem Workflows read MARKETPULSE_API_URL and TELEGRAM_CHAT_ID from the environment, so
rem exported files hold neither. Secrets go in n8n's encrypted credentials instead.
set "N8N_BLOCK_ENV_ACCESS_IN_NODE=false"

call "%~dp0node_modules\.bin\n8n.cmd" %*
