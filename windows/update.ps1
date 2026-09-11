#Requires -Version 5.1
# Pulls the latest code and syncs Python dependencies. Run this occasionally
# to keep your local checkout current; launcher.ps1 also reinstalls deps
# automatically whenever requirements.txt changes.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Fetching latest changes..."
git pull --ff-only

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Host "Syncing dependencies..."
    & $python -m pip install -r requirements.txt
    (Get-FileHash requirements.txt).Hash | Set-Content (Join-Path $repo ".venv\.reqs-hash")
}

Write-Host ""
Write-Host "Done. Press any key to close."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
