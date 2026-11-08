# Dot-source this from the starter and the local check.
# A non-empty process variable wins. Otherwise the value comes from the file.
# Windows PowerShell 5.1: do not use String.Split(string, int); that overload
# is not the one PowerShell binds, and it breaks values that contain '='.
#Requires -Version 5.1

function Import-ProtonWindowsEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "missing $Path (copy config\windows.env.example and fill the non-secret values)"
    }
    $text = [System.IO.File]::ReadAllText($Path)
    $lines = $text.Split([string[]]@("`r`n", "`n"), [System.StringSplitOptions]::None)
    foreach ($raw in $lines) {
        $line = $raw.Trim().TrimStart([char]0xFEFF)
        if ($line -eq "" -or $line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { throw "invalid env line" }
        $name = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($name -match "PASSWORD|SECRET|TOKEN|AUTH") {
            throw "refusing to load a secret from the env file: $name"
        }
        $current = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrEmpty($current)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}
