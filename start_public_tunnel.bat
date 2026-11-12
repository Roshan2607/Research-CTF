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

if exist "cloudflared.exe" (
    .\cloudflared.exe tunnel --url http://localhost:8503
) else (
    echo [ERROR] cloudflared.exe not found in current directory.
    echo Please download it or run:
    echo powershell -Command "Invoke-WebRequest -Uri https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile cloudflared.exe"
    pause
)
