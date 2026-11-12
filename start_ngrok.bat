@echo off
title Research-CTF ngrok Tunnel
echo =========================================================
echo         RESEARCH-CTF NGROK PARTICIPANT TUNNEL
echo =========================================================
echo.
echo Exposing Participant Portal (port 8503) via ngrok...
echo URL: https://antirust-alumni-grueling.ngrok-free.dev
echo.
echo Keep this window OPEN throughout the event.
echo =========================================================
echo.
npx ngrok http 8503 --url https://antirust-alumni-grueling.ngrok-free.dev
pause
