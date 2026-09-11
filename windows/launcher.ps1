#Requires -Version 5.1
# Remote Transcribe launcher.
#
# The installer places bundled Python and ffmpeg alongside the app, so the
# launcher just points at those, starts uvicorn hidden, waits for the port,
# and opens the browser. No venv, no pip, no PATH pollution.

$ErrorActionPreference = "Stop"

# windows/ sits one level below the install root.
$app = Split-Path -Parent $PSScriptRoot
Set-Location $app

$python = Join-Path $app "python\python.exe"
$ffmpeg = Join-Path $app "ffmpeg\bin"
$logDir = Join-Path $app "windows"
$startupLog = Join-Path $logDir "last-startup.log"
$serverLog = Join-Path $logDir "uvicorn.log"
$serverErr = Join-Path $logDir "uvicorn.err.log"
$port = 8080

function Write-Log([string]$message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $startupLog -Value "[$stamp] $message" -Encoding utf8
}

function Show-Error([string]$message) {
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    [System.Windows.Forms.MessageBox]::Show($message, "Remote Transcribe",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
}

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

Set-Content -Path $startupLog -Value "" -Encoding utf8
Write-Log "Launcher started in $app"

if (-not (Test-Path $python)) {
    Show-Error "The bundled Python runtime is missing.`n`nRun the installer again and choose Repair."
    exit 1
}

# Put bundled ffmpeg on PATH for this launch only.
if (Test-Path $ffmpeg) {
    $env:PATH = "$ffmpeg;$env:PATH"
}

# If the server already answers, just open the browser.
if (Test-Port $port) {
    Write-Log "Server already running on port $port; opening browser."
    Start-Process "http://localhost:$port"
    exit 0
}

# Warn if .env is missing or the Groq key looks empty.
$envPath = Join-Path $app ".env"
if (-not (Test-Path $envPath)) {
    Show-Error "Configuration file .env is missing.`n`nRun the installer again to set your API keys."
    exit 1
}
$envContents = Get-Content $envPath -Raw
if ($envContents -notmatch "(?m)^\s*GROQ_API_KEY\s*=\s*\S") {
    Show-Error "No Groq API key is set.`n`nRun the installer again and enter your key on the Configuration page."
    exit 1
}

Write-Log "Starting uvicorn on port $port."
try {
    Start-Process -FilePath $python `
        -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$port" `
        -WorkingDirectory $app `
        -WindowStyle Hidden `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError $serverErr | Out-Null
} catch {
    Write-Log "Failed to start uvicorn: $($_.Exception.Message)"
    Show-Error "Could not start the server. See:`n$startupLog"
    exit 1
}

# Poll for the port for up to 30 seconds.
$deadline = (Get-Date).AddSeconds(30)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Port $port) { $ready = $true; break }
    Start-Sleep -Milliseconds 300
}

if ($ready) {
    Write-Log "Server ready, opening browser."
    Start-Process "http://localhost:$port"
} else {
    Write-Log "Server did not answer within 30s."
    Show-Error "Remote Transcribe did not start within 30 seconds.`n`nSee $serverErr for details."
}
