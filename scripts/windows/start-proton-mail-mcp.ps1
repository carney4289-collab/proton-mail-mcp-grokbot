# Start the loopback HTTP connector. No secret is accepted as a parameter.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Entry = Join-Path $Root "scripts\proton-mail-mcp-http.py"
$EnvFile = Join-Path $Root "config\windows.env"
if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Error "missing $Entry"
}
. (Join-Path $PSScriptRoot "load-windows-env.ps1")
Import-ProtonWindowsEnv -Path $EnvFile

$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}

& $Python -u $Entry
exit $LASTEXITCODE
