# Report the logon task and loopback ports. Does not start the connector or read a secret.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "startup-common.ps1")
Import-Module ScheduledTasks

$name = Get-ProtonLogonTaskName
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
Write-Output "task: $name"
if (-not $existing) {
    Write-Output "installed: no"
} else {
    $principal = $existing.Principal
    $trigger = @($existing.Triggers)[0]
    $settings = $existing.Settings
    $mismatch = Get-ProtonLogonTaskMismatch -Task $existing
    if (-not $mismatch) {
        Write-Output "installed: yes"
    } else {
        Write-Output "installed: mismatched"
        Write-Output "mismatch: $mismatch"
    }
    Write-Output ("logon: " + [string]$principal.LogonType)
    Write-Output ("run-level: " + [string]$principal.RunLevel)
    Write-Output ("delay: " + [string]$trigger.Delay)
    Write-Output ("multiple-instances: " + [string]$settings.MultipleInstances)
    Write-Output ("restart-count: " + [string]$settings.RestartCount)
    Write-Output ("execution-limit: " + [string]$settings.ExecutionTimeLimit)
    if (Test-ProtonCurrentUser -Stored ([string]$principal.UserId)) {
        Write-Output "user: current-user"
    } elseif ([string]$principal.UserId -eq "SYSTEM") {
        Write-Output "user: SYSTEM"
    } else {
        Write-Output "user: other"
    }
    if ($mismatch) { exit 2 }
}

function Write-Port {
    param([string]$Label, [int]$Port)
    if (Test-ProtonLoopbackPort -Port $Port) {
        Write-Output "$Label open"
    } else {
        Write-Output "$Label closed"
    }
}
Write-Port -Label "connector-port 127.0.0.1:8765" -Port 8765
Write-Port -Label "imap-port 127.0.0.1:1143" -Port 1143
Write-Port -Label "smtp-port 127.0.0.1:1025" -Port 1025
Write-Output "bridge-autostart: not-verified"
Write-Output ("execution-policy: " + (Get-ProtonEffectiveExecutionPolicy))
Write-Output "serve-handoff: not changed"
$check = Join-Path $PSScriptRoot "check-endpoint.ps1"
Write-Output "protocol-check: powershell -NoProfile -File `"$check`" -Endpoint `"https://dell-sean.tail545f1e.ts.net/mcp`""
exit 0
