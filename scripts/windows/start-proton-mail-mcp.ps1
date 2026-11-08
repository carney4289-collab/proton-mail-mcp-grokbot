# Start the loopback HTTP connector. No secret is accepted as a parameter.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Entry = Join-Path $Root "scripts\proton-mail-mcp-http.py"
$EnvFile = Join-Path $Root "config\windows.env"
if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Error "missing $Entry"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Error "missing $EnvFile (copy config\windows.env.example and fill the non-secret values)"
}

Get-Content -LiteralPath $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) { throw "invalid env line" }
    $name = $parts[0].Trim()
    if ($name -match "PASSWORD|SECRET|TOKEN|AUTH") {
        throw "refusing to load a secret from the env file: $name"
    }
    Set-Item -Path "Env:$name" -Value $parts[1]
}

$Python = $env:PYTHON_EXE
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python was not found; set PYTHON_EXE to python.exe" }
    $Python = $cmd.Source
}

& $Python -u $Entry
exit $LASTEXITCODE
