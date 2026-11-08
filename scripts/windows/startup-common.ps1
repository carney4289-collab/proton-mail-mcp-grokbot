# Shared checks for the logon task. Dot-sourcing this file does not start anything.
#Requires -Version 5.1

$ProtonLogonTaskName = "ProtonMailMCP-Loopback"
$ProtonLogonDelay = "PT45S"
$ProtonLogonDescription = "Starts the loopback Proton Mail MCP connector after the current user signs in."
$ProtonExtraHost = "dell-sean.tail545f1e.ts.net"

function Get-ProtonPackageRoot {
    return (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

function Get-ProtonLogonTaskName {
    return $ProtonLogonTaskName
}

function Get-ProtonRuntimePython {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)
    $override = $env:PYTHON_EXE
    if ($override) {
        if (-not [System.IO.Path]::IsPathRooted($override)) {
            throw "PYTHON_EXE must be a full path to python.exe"
        }
        if (-not (Test-Path -LiteralPath $override)) {
            throw "PYTHON_EXE was not found"
        }
        return (Resolve-Path -LiteralPath $override).Path
    }
    $installRoot = Split-Path -Parent (Split-Path -Parent $PackageRoot)
    $python = Join-Path $installRoot "runtimes\Python314\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "installed Python runtime was not found"
    }
    return (Resolve-Path -LiteralPath $python).Path
}

function Test-ProtonLoopbackPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    if ($Port -ne 8765 -and $Port -ne 1143 -and $Port -ne 1025) {
        throw "refusing to probe a port other than 8765, 1143, or 1025"
    }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(400, $false)) {
            return $false
        }
        try {
            $client.EndConnect($wait)
        } catch {
            return $false
        }
        return [bool]$client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-ProtonBridgePorts {
    param([Parameter(Mandatory = $true)][int]$Seconds)
    if ($Seconds -lt 0 -or $Seconds -gt 120) {
        throw "bridge wait must be from 0 through 120 seconds"
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ($true) {
        $imap = Test-ProtonLoopbackPort -Port 1143
        $smtp = Test-ProtonLoopbackPort -Port 1025
        if ($imap -and $smtp) { return $true }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Seconds 1
    }
}

function Assert-ProtonStartupConfig {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "missing config\windows.env"
    }
    $bindHost = $null
    $bindPort = $null
    $extra = $null
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
            throw "refusing to read a secret from the env file"
        }
        if ($name -eq "BIND_HOST") { $bindHost = $value }
        elseif ($name -eq "BIND_PORT") { $bindPort = $value }
        elseif ($name -eq "PROTON_MCP_EXTRA_HOSTS") { $extra = $value }
    }
    if ($bindHost -cne "127.0.0.1") { throw "BIND_HOST must be 127.0.0.1" }
    if ($bindPort -cne "8765") { throw "BIND_PORT must be 8765" }
    if ($extra -cne $ProtonExtraHost) {
        throw "PROTON_MCP_EXTRA_HOSTS must be dell-sean.tail545f1e.ts.net"
    }
}

function Test-ProtonCurrentUser {
    param([string]$Stored)
    if (-not $Stored) { return $false }
    if ($Stored -match '^(?i)(SYSTEM|LOCAL SERVICE|NETWORK SERVICE|NT AUTHORITY\\.+)$') { return $false }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $name = [string]$identity.Name
    if ($Stored -ieq $name) { return $true }
    if ($Stored -eq [string]$identity.User.Value) { return $true }
    $simple = $name.Split('\')[-1]
    $storedSimple = $Stored.Split('\')[-1]
    if ($simple -and $storedSimple -ieq $simple) { return $true }
    return $false
}

function Get-ProtonLogonWrapperPath {
    return (Join-Path $PSScriptRoot "run-at-logon.ps1")
}

function Get-ProtonLogonPowerShell {
    return (Join-Path $PSHOME "powershell.exe")
}

function Get-ProtonLogonArgument {
    $wrapper = Get-ProtonLogonWrapperPath
    return '-NoProfile -NonInteractive -File "' + $wrapper + '"'
}

function Assert-ProtonScriptPolicy {
    param([Parameter(Mandatory = $true)][string[]]$Paths)
    $effective = [string](Get-ExecutionPolicy)
    if ($effective -eq "Restricted" -or $effective -eq "AllSigned") {
        throw "Windows PowerShell execution policy is $effective. The logon task was not registered. This installer does not change execution policy and does not unblock files."
    }
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath ($path + ":Zone.Identifier")) {
            throw "A startup script is marked as downloaded, so normal execution policy can refuse it. The logon task was not registered. This installer does not unblock files and does not change execution policy."
        }
    }
}

function Test-ProtonDuration {
    param([string]$Actual, [string]$Expected)
    if (-not $Actual -and $Expected -eq "PT0S") { return $true }
    if ($Actual -eq $Expected) { return $true }
    try {
        $expectedSpan = [System.Xml.XmlConvert]::ToTimeSpan($Expected)
        if ($Actual -match "^P") {
            $actualSpan = [System.Xml.XmlConvert]::ToTimeSpan($Actual)
        } else {
            $actualSpan = [TimeSpan]$Actual
        }
        return $expectedSpan -eq $actualSpan
    } catch {
        return $false
    }
}

function Get-ProtonLogonTaskMismatch {
    param($Task)
    if (-not $Task) { return "missing" }
    $root = Get-ProtonPackageRoot
    $expectedArg = Get-ProtonLogonArgument
    $powerShell = Get-ProtonLogonPowerShell
    if (@($Task.Actions).Count -ne 1) { return "action-count" }
    $action = @($Task.Actions)[0]
    if ($action.Execute -ine $powerShell) { return "execute" }
    if ($action.Arguments -cne $expectedArg) { return "arguments" }
    $actualDir = ([string]$action.WorkingDirectory).TrimEnd('\')
    if ($actualDir -and ($actualDir -ine $root.TrimEnd('\'))) { return "working-directory" }
    $principal = $Task.Principal
    if (-not (Test-ProtonCurrentUser -Stored ([string]$principal.UserId))) { return "user" }
    $logon = [string]$principal.LogonType
    if ($logon -ne "Interactive" -and $logon -ne "3") { return "logon=$logon" }
    $level = [string]$principal.RunLevel
    if ($level -ne "Limited" -and $level -ne "0") { return "run-level=$level" }
    if (@($Task.Triggers).Count -ne 1) { return "trigger-count" }
    $trigger = @($Task.Triggers)[0]
    if ($trigger.CimClass.CimClassName -ne "MSFT_TaskLogonTrigger") {
        return "trigger-type=" + $trigger.CimClass.CimClassName
    }
    if (-not (Test-ProtonDuration -Actual ([string]$trigger.Delay) -Expected $ProtonLogonDelay)) {
        return "delay=" + [string]$trigger.Delay
    }
    $triggerUser = [string]$trigger.UserId
    if ($triggerUser -and -not (Test-ProtonCurrentUser -Stored $triggerUser)) { return "trigger-user" }
    $settings = $Task.Settings
    $instances = [string]$settings.MultipleInstances
    if ($instances -ne "IgnoreNew" -and $instances -ne "2") { return "instances=$instances" }
    if ([int]$settings.RestartCount -ne 3) { return "restart-count=" + [string]$settings.RestartCount }
    if (-not (Test-ProtonDuration -Actual ([string]$settings.ExecutionTimeLimit) -Expected "PT0S")) {
        return "execution-limit=" + [string]$settings.ExecutionTimeLimit
    }
    if (-not (Test-ProtonDuration -Actual ([string]$settings.RestartInterval) -Expected "PT1M")) {
        return "restart-interval=" + [string]$settings.RestartInterval
    }
    if ($settings.Enabled -ne $true) { return "disabled" }
    return ""
}
