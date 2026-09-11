#Requires -Version 5.1
# Remote Transcribe launcher.
#
# Starts uvicorn on port 8080 (creating the venv on first run and reinstalling
# dependencies if requirements.txt has changed), waits for the port to answer,
# then opens the app in the default browser.
#
# Meant to be called from launcher.vbs so the console window stays hidden.

$ErrorActionPreference = "Stop"

# windows/ sits one level below the repo root.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
$uvicorn = Join-Path $repo ".venv\Scripts\uvicorn.exe"
$reqsHash = Join-Path $repo ".venv\.reqs-hash"
$startupLog = Join-Path $repo "windows\last-startup.log"

function Write-Log([string]$message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $startupLog -Value "[$stamp] $message" -Encoding utf8
}

# Fresh log for each launch.
Set-Content -Path $startupLog -Value "" -Encoding utf8
Write-Log "Launcher started in $repo"

# First-run bootstrap: create the venv and install requirements.
if (-not (Test-Path $python)) {
    Write-Log "No venv found, creating one."
    try {
        python -m venv .venv
    } catch {
        [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
        [System.Windows.Forms.MessageBox]::Show(
            "Python 3.11+ was not found on PATH. Install it from python.org (tick 'Add Python to PATH') and try again.",
            "Remote Transcribe") | Out-Null
        exit 1
    }
    & $python -m pip install --upgrade pip | Out-Null
    & $python -m pip install -r requirements.txt | Out-Null
    (Get-FileHash requirements.txt).Hash | Set-Content $reqsHash
    Write-Log "Venv created and dependencies installed."
} else {
    # If requirements.txt has changed since last launch, sync it.
    $current = (Get-FileHash requirements.txt).Hash
    $stored = if (Test-Path $reqsHash) { Get-Content $reqsHash } else { "" }
    if ($current -ne $stored) {
        Write-Log "requirements.txt changed, reinstalling dependencies."
        & $python -m pip install -r requirements.txt | Out-Null
        $current | Set-Content $reqsHash
    }
}

# Make sure there is an .env; open it in Notepad the first time so the user
# can drop their key in before anything tries to reach Groq.
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Log "Created .env from .env.example, opening Notepad."
        Start-Process notepad.exe ".env" -Wait
    }
}

# If port 8080 already answers, assume the app is up and just open the browser.
function Test-Port([int]$port) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

if (Test-Port 8080) {
    Write-Log "Port 8080 already answers; skipping server start."
    Start-Process "http://localhost:8080"
    exit 0
}

# Start uvicorn detached and hidden; write its output next to the log.
$serverLog = Join-Path $repo "windows\uvicorn.log"
Write-Log "Starting uvicorn."
Start-Process -FilePath $uvicorn `
    -ArgumentList "app.main:app","--host","127.0.0.1","--port","8080" `
    -WorkingDirectory $repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $serverLog `
    -RedirectStandardError (Join-Path $repo "windows\uvicorn.err.log") | Out-Null

# Poll for the port for up to 30 seconds.
$deadline = (Get-Date).AddSeconds(30)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Port 8080) { $ready = $true; break }
    Start-Sleep -Milliseconds 300
}

if ($ready) {
    Write-Log "Server ready, opening browser."
    Start-Process "http://localhost:8080"
} else {
    Write-Log "Server did not answer within 30s."
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    [System.Windows.Forms.MessageBox]::Show(
        "Remote Transcribe did not start within 30 seconds.`n`nSee windows\uvicorn.err.log for details.",
        "Remote Transcribe") | Out-Null
}
