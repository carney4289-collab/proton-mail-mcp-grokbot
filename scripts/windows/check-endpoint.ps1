# Check the already-running private HTTPS endpoint. Does not start or stop it.
# The HTTP token stays inside Python's Credential Manager read.
#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint
)
$ErrorActionPreference = "Stop"
if ($Endpoint -cne "https://dell-sean.tail545f1e.ts.net/mcp") {
    throw "endpoint must be https://dell-sean.tail545f1e.ts.net/mcp"
}
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Script = Join-Path $Root "scripts\proton-mail-mcp-check-endpoint.py"
if (-not (Test-Path -LiteralPath $Script)) {
    Write-Error "missing $Script"
}
$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
& $Python -u $Script --endpoint $Endpoint
exit $LASTEXITCODE
