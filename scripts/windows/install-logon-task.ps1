# Register the current-user logon task. Does not start it and does not stop a running connector.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 6) {
    throw "run this installer with Windows PowerShell 5.1"
}
. (Join-Path $PSScriptRoot "startup-common.ps1")
Import-Module ScheduledTasks

$root = Get-ProtonPackageRoot
Assert-ProtonStartupConfig -Path (Join-Path $root "config\windows.env")
$name = Get-ProtonLogonTaskName
$wrapper = Get-ProtonLogonWrapperPath
if (-not (Test-Path -LiteralPath $wrapper)) { throw "missing run-at-logon.ps1" }
$expectedArg = Get-ProtonLogonArgument
$powerShell = Get-ProtonLogonPowerShell
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    $reason = Get-ProtonLogonTaskMismatch -Task $existing
    if (-not $reason) {
        Write-Output "logon task already installed"
        exit 0
    }
    throw "refusing to replace $name ($reason)"
}

$action = New-ScheduledTaskAction -Execute $powerShell -Argument $expectedArg -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$trigger.Delay = $ProtonLogonDelay
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable:$false
$settings.ExecutionTimeLimit = "PT0S"
$settings.WakeToRun = $false
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $ProtonLogonDescription | Out-Null

$created = Get-ScheduledTask -TaskName $name
$createdReason = Get-ProtonLogonTaskMismatch -Task $created
if ($createdReason) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    throw "logon task did not match the required definition ($createdReason) and was removed"
}
Write-Output "logon task installed"
exit 0
