# Copy proton-mail-mcp:http-auth to the clipboard as the Authorization value.
# Python reads Credential Manager. The token is not a parameter and is not printed.
# -Confirm is required because the current clipboard contents are replaced.
#Requires -Version 5.1
param(
    [switch]$Confirm,
    [int]$Seconds = 45
)
$ErrorActionPreference = "Stop"
if (-not $Confirm) {
    throw "Refusing to replace the clipboard without -Confirm"
}
if ($Seconds -lt 15 -or $Seconds -gt 90) {
    throw "Seconds must be from 15 through 90"
}
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Script = Join-Path $Root "scripts\proton-mail-mcp-clipboard-auth.py"
if (-not (Test-Path -LiteralPath $Script)) {
    Write-Error "missing $Script"
}
$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
Write-Output "The clipboard will be replaced for $Seconds seconds if the stored token can be copied."
Write-Output "Paste the Authorization value into the form. This window does not register the connector."
& $Python -u $Script --confirm --seconds $Seconds
exit $LASTEXITCODE
