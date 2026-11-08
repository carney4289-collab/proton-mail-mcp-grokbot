# Logon entry point. Starts the existing connector after Bridge accepts TCP.
# Does not read Credential Manager itself and does not stop an existing listener.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "startup-common.ps1")

if (Test-ProtonLoopbackPort -Port 8765) {
    Write-Output "connector port 127.0.0.1:8765 is already open; not starting another process"
    exit 0
}

$wait = 90
if ($env:PROTON_MCP_BRIDGE_WAIT_SECONDS) {
    $parsed = 0
    if (-not [int]::TryParse($env:PROTON_MCP_BRIDGE_WAIT_SECONDS, [ref]$parsed)) {
        throw "bridge wait must be from 0 through 120 seconds"
    }
    $wait = $parsed
}
$ready = Wait-ProtonBridgePorts -Seconds $wait
if (-not $ready) {
    Write-Output "bridge ports 127.0.0.1:1143 and 127.0.0.1:1025 were not both open; connector was not started"
    Write-Output "Bridge Open on startup was not verified. This script does not change Bridge settings."
    exit 1
}

$root = Get-ProtonPackageRoot
$env:PYTHON_EXE = Get-ProtonRuntimePython -PackageRoot $root
& (Join-Path $PSScriptRoot "start-proton-mail-mcp.ps1")
exit $LASTEXITCODE
