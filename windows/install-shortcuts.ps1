#Requires -Version 5.1
# Creates Desktop and Start Menu shortcuts that launch this checkout of
# Remote Transcribe with one click. Idempotent — running it again just
# refreshes the shortcuts against the current repo location.

$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
$repo = Split-Path -Parent $here

$launcher = Join-Path $here "launcher.vbs"
$stop = Join-Path $here "stop.vbs"
$update = Join-Path $here "update.ps1"
$icon = Join-Path $here "icon.ico"

if (-not (Test-Path $launcher)) {
    throw "launcher.vbs missing next to install-shortcuts.ps1."
}

$wsh = New-Object -ComObject WScript.Shell

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments = "",
        [string]$Description,
        [string]$WorkingDir,
        [string]$IconPath = ""
    )
    $sc = $wsh.CreateShortcut($Path)
    $sc.TargetPath = $Target
    if ($Arguments) { $sc.Arguments = $Arguments }
    $sc.WorkingDirectory = $WorkingDir
    $sc.Description = $Description
    if ($IconPath -and (Test-Path $IconPath)) { $sc.IconLocation = $IconPath }
    $sc.Save()
    Write-Host "  $Path"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Remote Transcribe"
if (-not (Test-Path $startMenu)) { New-Item -ItemType Directory -Path $startMenu | Out-Null }

Write-Host "Creating shortcuts:"
New-Shortcut -Path (Join-Path $desktop "Remote Transcribe.lnk") `
             -Target $launcher -WorkingDir $repo `
             -Description "Start Remote Transcribe and open it in the browser." `
             -IconPath $icon

New-Shortcut -Path (Join-Path $startMenu "Remote Transcribe.lnk") `
             -Target $launcher -WorkingDir $repo `
             -Description "Start Remote Transcribe and open it in the browser." `
             -IconPath $icon

New-Shortcut -Path (Join-Path $startMenu "Stop Remote Transcribe.lnk") `
             -Target $stop -WorkingDir $repo `
             -Description "Stop the Remote Transcribe server." `
             -IconPath $icon

New-Shortcut -Path (Join-Path $startMenu "Update Remote Transcribe.lnk") `
             -Target "powershell.exe" `
             -Arguments ("-NoProfile -ExecutionPolicy Bypass -File `"" + $update + "`"") `
             -WorkingDir $repo `
             -Description "Pull the latest code and sync dependencies." `
             -IconPath $icon

Write-Host ""
Write-Host "Done. Look for 'Remote Transcribe' on your Desktop and in the Start Menu."
Write-Host "Press any key to close."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
