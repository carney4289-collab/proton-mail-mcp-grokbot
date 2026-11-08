# Print the private Serve handover plan. Does not change Tailscale unless status is only read.
#Requires -Version 5.1
param(
    [string]$StatusText = "",
    [string]$StatusJson = "",
    [switch]$ReadLocalStatus
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "startup-common.ps1")

if ($ReadLocalStatus -and ($StatusText -or $StatusJson)) {
    throw "pass either saved status arguments or -ReadLocalStatus"
}
if (-not $ReadLocalStatus -and -not $PSBoundParameters.ContainsKey("StatusText")) {
    throw "pass -StatusText and -StatusJson, or -ReadLocalStatus"
}
$root = Get-ProtonPackageRoot
$textFile = ""
$jsonFile = ""
if ($ReadLocalStatus) {
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    if (-not $tailscale) { throw "tailscale.exe was not found" }
    $state = Join-Path $root "state"
    New-Item -ItemType Directory -Force -Path $state | Out-Null
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $textFile = Join-Path $state ("serve-status-" + $stamp + ".txt")
    $jsonFile = Join-Path $state ("serve-status-" + $stamp + ".json")
    $procFile = Join-Path $state ("serve-processes-" + $stamp + ".txt")
    & $tailscale.Source serve status | Out-File -FilePath $textFile -Encoding utf8
    & $tailscale.Source serve status --json | Out-File -FilePath $jsonFile -Encoding utf8
    $lines = @()
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'tailscale.exe'"
    foreach ($item in $processes) {
        $command = [string]$item.CommandLine
        if ($command -match '(?i)(^|\s)serve(\s|$)' -and $command -notmatch '(?i)funnel|--bg|serve status|serve reset') {
            $lines += $command
        }
    }
    [System.IO.File]::WriteAllLines($procFile, $lines)
    Write-Output "saved serve status under state\"
}

$python = Get-ProtonRuntimePython -PackageRoot $root
$planner = Join-Path $root "scripts\proton-mail-mcp-serve-plan.py"
if ($ReadLocalStatus) {
    & $python -u $planner --status-text-file $textFile --status-json-file $jsonFile
} else {
    & $python -u $planner --status-text $StatusText --status-json $StatusJson
}
exit $LASTEXITCODE
