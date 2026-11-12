# Expose Participant Portal via Cloudflare Tunnel
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "       RESEARCH-CTF PUBLIC PARTICIPANT TUNNEL            " -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Connecting to Cloudflare Edge to expose Participant Portal (port 8503)..." -ForegroundColor Yellow
Write-Host "Look for the public HTTPS URL ending in '.trycloudflare.com' below." -ForegroundColor Green
Write-Host "Share that URL with all participants!`n" -ForegroundColor Green
Write-Host "Keep this window OPEN during the entire event.`n" -ForegroundColor DarkGray

if (Test-Path "cloudflared.exe") {
    .\cloudflared.exe tunnel --url http://localhost:8503
} else {
    Write-Host "[ERROR] cloudflared.exe not found in current directory." -ForegroundColor Red
    Write-Host "Downloading cloudflared.exe automatically..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "cloudflared.exe"
    .\cloudflared.exe tunnel --url http://localhost:8503
}
