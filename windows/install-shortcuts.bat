@echo off
REM One-click wrapper: sets execution policy for this call only, then runs
REM install-shortcuts.ps1 to create Desktop and Start Menu shortcuts.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-shortcuts.ps1"
