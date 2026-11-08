# Prompt for one secret and pass it on stdin, never as an argument.
#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("bridge-imap", "http-auth")]
    [string]$Name
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Store = Join-Path $Root "scripts\proton-mail-mcp-store.py"
$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}
$secure = Read-Host -AsSecureString "Value for proton-mail-mcp:$Name (not stored in the command line)"
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $plain | & $Python -u $Store $Name
    $code = $LASTEXITCODE
} finally {
    $plain = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
exit $code
