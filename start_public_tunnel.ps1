# Expose Participant Portal via Cloudflare Tunnel
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "       RESEARCH-CTF PUBLIC PARTICIPANT TUNNEL            " -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Connecting to Cloudflare Edge to expose Participant Portal (port 8503)..." -ForegroundColor Yellow
Write-Host "Look for the public HTTPS URL ending in '.trycloudflare.com' below." -ForegroundColor Green
Write-Host "Share that URL with all participants!`n" -ForegroundColor Green
Write-Host "Keep this window OPEN during the entire event.`n" -ForegroundColor DarkGray

if (-not (Test-Path "cloudflared.exe")) {
    Write-Host "[ERROR] cloudflared.exe not found. Downloading..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "cloudflared.exe"
}

while ($true) {
    .\cloudflared.exe tunnel --protocol http2 --url http://127.0.0.1:8503
    Write-Host "`n[Notice] Tunnel disconnected or timed out. Reconnecting in 3 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}
