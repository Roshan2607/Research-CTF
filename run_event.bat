@echo off
echo =========================================================
echo        STARTING RESEARCH-CTF EVENT PLATFORM
echo =========================================================
echo.
echo [1/3] Starting Participant Portal on port 8503...
start "Participant Portal (Port 8503)" python -m streamlit run event_portal.py --server.port 8503 --server.headless true

echo [2/3] Starting Admin Console on port 8504...
start "Admin Console (Port 8504)" python -m streamlit run event_admin.py --server.port 8504 --server.headless true

echo [3/3] Starting Automatic 5-Minute Backup Daemon...
start "Backup Daemon (every 5m)" python scripts/backup_event.py --auto --interval 300

echo.
echo All services launched!
echo - Participant Portal: http://localhost:8503
echo - Admin Console:      http://localhost:8504
echo.
pause
