# Remove only this package's logon task. Does not stop the connector process.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 6) {
    throw "run this remover with Windows PowerShell 5.1"
}
. (Join-Path $PSScriptRoot "startup-common.ps1")
Import-Module ScheduledTasks

$name = Get-ProtonLogonTaskName
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Output "logon task is not installed"
    exit 0
}
$expectedArg = Get-ProtonLogonArgument
$powerShell = Get-ProtonLogonPowerShell
$action = @($existing.Actions)[0]
$owned = $false
if (@($existing.Actions).Count -eq 1 -and $action.Execute -ieq $powerShell -and $action.Arguments -ceq $expectedArg) {
    $owned = $true
}
if (-not $owned) {
    throw "refusing to remove $name because its action does not belong to this package"
}
Unregister-ScheduledTask -TaskName $name -Confirm:$false
Write-Output "logon task removed"
exit 0
