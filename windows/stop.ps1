#Requires -Version 5.1
# Stops any Remote Transcribe uvicorn process bound to port 8080.
$ErrorActionPreference = "SilentlyContinue"

$conns = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "Nothing listening on port 8080."
    Start-Sleep -Seconds 2
    exit 0
}

foreach ($conn in $conns) {
    try {
        Stop-Process -Id $conn.OwningProcess -Force
        Write-Host ("Stopped PID {0}." -f $conn.OwningProcess)
    } catch {
        Write-Host ("Could not stop PID {0}: {1}" -f $conn.OwningProcess, $_.Exception.Message)
    }
}
Start-Sleep -Seconds 2
