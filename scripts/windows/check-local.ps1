# Run initialize and tools/list against a short-lived loopback server.
# Loads config\windows.env from the package root (the folder that contains
# scripts and config), then lets Python read Credential Manager.
# Does not print the token or call tools/call.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Check = Join-Path $Root "scripts\proton-mail-mcp-check.py"
$EnvFile = Join-Path $Root "config\windows.env"
if (-not (Test-Path -LiteralPath $Check)) {
    Write-Error "missing $Check"
}
. (Join-Path $PSScriptRoot "load-windows-env.ps1")
Import-ProtonWindowsEnv -Path $EnvFile

$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
& $Python -u $Check
exit $LASTEXITCODE
