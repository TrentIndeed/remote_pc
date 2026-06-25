# Remote-access hardening so Windows security prompts stop locking you out.
# RUN THIS ONCE, AT THE PC (it needs ONE UAC approval on the secure desktop, which
# can't be clicked over the remote stream). After this, UAC prompts appear on the
# normal desktop and the stream server runs elevated, so remote control keeps
# working through them.
#
# What it does (both LOWER Windows' elevation protection -- fine for a single-user
# remote box, but understand the tradeoff):
#   1. PromptOnSecureDesktop = 0  -> UAC prompts no longer switch to the secure
#      desktop, so a prompt won't freeze the whole screen/cursor remotely.
#   2. Registers an ELEVATED scheduled task "RemotePCStream" that runs the stream
#      watchdog (-StreamOnly) at logon, so it can drive elevated/UAC windows.
#      Chrome + VS Code stay NON-elevated via the Startup launcher (-AppsOnly).
#
# Undo: delete task "RemotePCStream", set PromptOnSecureDesktop back to 1, and
# restore the Startup .bat to run watchdog.ps1 with no args.

$ErrorActionPreference = "Stop"
$root = "C:\Users\Trenton\CodeProjects\remote_pc"
$wd   = Join-Path $root "watchdog.ps1"

# --- self-elevate (this is the one UAC prompt; approve it at the PC) ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
          ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting administrator rights -- approve the UAC prompt..."
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"")
    return
}

Write-Host "Applying remote-access hardening (elevated)..."

# 1. UAC: do not switch to the secure desktop
New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
    -Name PromptOnSecureDesktop -Value 0 -PropertyType DWord -Force | Out-Null
Write-Host "  [1/3] PromptOnSecureDesktop = 0"

# 2. elevated scheduled task: stream watchdog at logon
$user = "$env:USERDOMAIN\$env:USERNAME"
$action    = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$wd`" -StreamOnly"
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -RunLevel Highest -LogonType Interactive
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "RemotePCStream" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "  [2/3] registered elevated scheduled task 'RemotePCStream'"

# 3. Startup launcher now only opens the apps (non-elevated)
$bat = Join-Path ([Environment]::GetFolderPath('Startup')) "startup-vscode-stream.bat"
@"
@echo off
REM Non-elevated: open Chrome + VS Code only. The stream runs via the elevated
REM scheduled task 'RemotePCStream' (set up by apply-hardening.ps1).
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$wd" -AppsOnly
"@ | Set-Content -Path $bat -Encoding ASCII
Write-Host "  [3/3] Startup launcher set to -AppsOnly"

Write-Host ""
Write-Host "Done. Reboot (or log off and back on) to start the elevated stream task."
Write-Host "Press Enter to close."
[void](Read-Host)
