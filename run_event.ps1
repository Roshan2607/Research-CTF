# Start all Research-CTF event services
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "       STARTING RESEARCH-CTF EVENT PLATFORM               " -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

# 1. Start Participant Portal on Port 8503
Write-Host "[1/3] Starting Participant Portal on http://localhost:8503..." -ForegroundColor Green
$portalJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    python -m streamlit run event_portal.py --server.port 8503 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false
}

# 2. Start Admin Console on Port 8504
Write-Host "[2/3] Starting Organiser Admin Console on http://localhost:8504..." -ForegroundColor Green
$adminJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    python -m streamlit run event_admin.py --server.port 8504 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false
}

# 3. Start Automatic 5-Minute Backup Daemon
Write-Host "[3/3] Starting Automatic 5-minute Backup Daemon..." -ForegroundColor Green
$backupJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    python scripts/backup_event.py --auto --interval 300
}

Write-Host "`nAll services are active in the background!" -ForegroundColor Yellow
Write-Host "  • Participant Portal: http://localhost:8503"
Write-Host "  • Admin Console:      http://localhost:8504"
Write-Host "  • Backup Daemon:      Running every 300s (data/backups/)"
Write-Host "`nTo view logs:  Receive-Job -Id $($portalJob.Id)"
Write-Host "To stop all:   Get-Job | Stop-Job; Get-Job | Remove-Job"
