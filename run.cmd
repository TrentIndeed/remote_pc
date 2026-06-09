@echo off
REM One-command launcher. Runs run.ps1 regardless of PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
