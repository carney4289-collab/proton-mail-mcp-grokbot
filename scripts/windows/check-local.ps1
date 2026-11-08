# Run initialize and tools/list against a short-lived loopback server.
# Reads Credential Manager inside Python. Does not print the token or call tools/call.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Check = Join-Path $Root "scripts\proton-mail-mcp-check.py"
if (-not (Test-Path -LiteralPath $Check)) {
    Write-Error "missing $Check"
}
$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
& $Python -u $Check
exit $LASTEXITCODE
