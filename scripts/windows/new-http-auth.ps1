# Generate a bearer token and store it as proton-mail-mcp:http-auth.
# The token is created in Python and written with CredWrite. It is not
# printed, passed as an argument, or written to a file. An existing token
# is left in place.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Store = Join-Path $Root "scripts\proton-mail-mcp-store.py"
if (-not (Test-Path -LiteralPath $Store)) {
    Write-Error "missing $Store"
}
$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
& $Python -u $Store --generate http-auth
exit $LASTEXITCODE
