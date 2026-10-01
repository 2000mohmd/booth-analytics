<#
.SYNOPSIS
    Registers a daily Task Scheduler task that runs services/reporting/main.py (PDF export) via
    docker compose - the Windows equivalent of a systemd timer, since this deployment runs on
    one Windows PC (see deploy/README.md's Windows section) rather than a Linux edge box.

.EXAMPLE
    .\deploy\windows\register-report-task.ps1
    .\deploy\windows\register-report-task.ps1 -At "23:55" -Format excel
#>
param(
    [string]$TaskName = "BoothAnalyticsReport",
    [string]$At = "23:55",
    [ValidateSet("pdf", "excel")]
    [string]$Format = "pdf",
    [string]$BoothId = "booth-01",
    [string]$RepoPath = (Get-Location).Path
)

$action = New-ScheduledTaskAction -Execute "docker" `
    -Argument "compose run --rm api python3 services/reporting/main.py --booth-id $BoothId --format $Format" `
    -WorkingDirectory $RepoPath

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
# -StartWhenAvailable is the Windows equivalent of systemd's Persistent=true - a day the PC
# was off/asleep at 23:55 still gets its report generated once the PC is next available.

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily booth-analytics report export ($Format) - see deploy/README.md" `
    -Force

Write-Host "Registered task '$TaskName', daily at $At. Check status: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
