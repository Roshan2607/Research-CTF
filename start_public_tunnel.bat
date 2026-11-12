@echo off
title Research-CTF Public Participant Tunnel
echo =========================================================
echo       RESEARCH-CTF PUBLIC PARTICIPANT TUNNEL
echo =========================================================
echo.
echo Connecting to Cloudflare Edge to expose Participant Portal (port 8503)...
echo.
echo Look for the public HTTPS URL ending in ".trycloudflare.com" below.
echo That is the link to share with all participants!
echo.
echo Keep this terminal window OPEN during the entire event.
echo =========================================================
echo.

if not exist "cloudflared.exe" (
    echo [ERROR] cloudflared.exe not found in current directory.
    pause
    exit /b 1
)

:loop
.\cloudflared.exe tunnel --protocol http2 --url http://127.0.0.1:8503
echo.
echo [Notice] Tunnel disconnected or request timed out. Reconnecting in 3 seconds...
timeout /t 3 /nobreak >nul
goto loop
