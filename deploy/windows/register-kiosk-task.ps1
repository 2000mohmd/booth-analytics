<#
.SYNOPSIS
    Registers a Task Scheduler task that launches the marketing kiosk display
    (services/kiosk_display) at logon and restarts it within seconds if it crashes - the Windows
    equivalent of a systemd Restart=always unit (see deploy/README.md's Windows section).

    Requires: Windows auto-login configured for the kiosk account (one-time OS setting, not
    something this script does), and requirements-kiosk.txt installed in the Python environment
    this points at.

.EXAMPLE
    .\deploy\windows\register-kiosk-task.ps1
    .\deploy\windows\register-kiosk-task.ps1 -PythonExe "C:\...\booth-analytics\.venv-kiosk\Scripts\python.exe"
#>
param(
    [string]$TaskName = "BoothAnalyticsKioskDisplay",
    [string]$RepoPath = (Get-Location).Path,
    [string]$PythonExe = (Join-Path (Get-Location).Path ".venv-kiosk\Scripts\python.exe")
)

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python executable not found at '$PythonExe'. Create the kiosk venv first: " `
        "python -m venv .venv-kiosk && .venv-kiosk\Scripts\pip install -r requirements-kiosk.txt"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $PythonExe `
    -Argument "-m services.kiosk_display.main" `
    -WorkingDirectory $RepoPath

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
# ExecutionTimeLimit 0 = no limit (this is meant to run for days). RestartCount/RestartInterval
# is the closest Task Scheduler equivalent to systemd's Restart=always/RestartSec - a crashed
# kiosk display should reappear on its own, not require someone to notice and relaunch it.
# 1 minute is Task Scheduler's actual minimum granularity for RestartInterval - anything
# shorter (e.g. a few seconds) fails registration with "value ... incorrectly formatted or
# out of range" (confirmed the hard way). There is no sub-minute restart option here.

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Marketing kiosk display, auto-restarting - see deploy/README.md" `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register task '$TaskName': $_"
    exit 1
}

# Register-ScheduledTask can report success on a non-terminating warning without actually
# creating the task - verify it's really there before claiming success.
if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Error "Register-ScheduledTask returned no error, but '$TaskName' does not exist afterward."
    exit 1
}

Write-Host "Registered task '$TaskName' to launch at logon. Also required (one-time, manual):"
Write-Host "  - Configure Windows auto-login for this account (netplwiz or registry)"
Write-Host "  - powercfg /change standby-timeout-ac 0"
Write-Host "  - powercfg /change monitor-timeout-ac 0"
