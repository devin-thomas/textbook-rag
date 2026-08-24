#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Inspect', 'Restart', 'Remove')]
    [string]$Action,
    [string]$ProjectRoot = '',
    [string]$NvidiaDotEnvPath = '',
    [ValidatePattern('^[A-Za-z0-9._-]+$')][string]$ResearchSshHost = 'research'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

. (Join-Path $PSScriptRoot 'TextbookDeploymentStatus.ps1')

$root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
if ([System.IO.Path]::GetPathRoot($root) -eq $root) { throw "Refusing to use a filesystem root: $root" }
if (-not (Test-Path -LiteralPath (Join-Path $root 'SPEC.md') -PathType Leaf)) {
    throw "ProjectRoot does not look like Textbook Desk: $root"
}

$taskNames = @(Get-TextbookDeploymentTaskNames)
$taskPath = '\'
$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tunnelScript = Join-Path $root 'scripts\Start-ResearchOllamaTunnel.ps1'
$appScript = Join-Path $root 'scripts\Start-TextbookRag.ps1'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Get-TaskSummary {
    foreach ($name in $taskNames) {
        $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) {
            [pscustomobject]@{ TaskName = $name; State = 'NotInstalled'; LastRunTime = $null; LastResult = $null; Command = $null }
            continue
        }
        $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $name
        [pscustomobject]@{
            TaskName = $name
            State = $task.State
            LastRunTime = $info.LastRunTime
            LastResult = $info.LastTaskResult
            Command = (($task.Actions | ForEach-Object { "$( $_.Execute ) $( $_.Arguments )" }) -join '; ')
        }
    }
}

if ($Action -eq 'Inspect') {
    Get-TaskSummary | Format-Table -AutoSize
    Write-Host ''
    Write-Host 'Runtime listeners:'
    $connections = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    $listenerAssessment = @(Get-TextbookListenerAssessment -Connections $connections)
    if ($listenerAssessment.Count -eq 0) {
        Write-Host 'No listeners found on ports 8766 or 11435.'
    }
    else {
        $listenerAssessment |
            Sort-Object LocalPort, LocalAddress |
            Format-Table LocalAddress, LocalPort, OwningProcess, Safety -AutoSize
    }
    $unsafeListeners = @($listenerAssessment | Where-Object { $_.Safety -eq 'UNSAFE' })
    if ($unsafeListeners.Count -gt 0) {
        $bindings = ($unsafeListeners | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }) -join ', '
        throw "Textbook Desk ports have unsafe non-loopback listener(s): $bindings"
    }
    return
}

if ($Action -eq 'Install') {
    foreach ($path in @($powerShellExe, $tunnelScript, $appScript)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
    }
    if ($NvidiaDotEnvPath) {
        $NvidiaDotEnvPath = [System.IO.Path]::GetFullPath($NvidiaDotEnvPath)
        if (-not (Test-Path -LiteralPath $NvidiaDotEnvPath -PathType Leaf)) { throw "NVIDIA dotenv file not found: $NvidiaDotEnvPath" }
    }

    $tunnelArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tunnelScript`" -SshHost `"$ResearchSshHost`""
    $appArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$appScript`" -ProjectRoot `"$root`""
    if ($NvidiaDotEnvPath) { $appArguments += " -NvidiaDotEnvPath `"$NvidiaDotEnvPath`"" }

    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 12 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 3650)

    $definitions = @(
        @{ Name = $taskNames[0]; Description = 'Maintains the loopback SSH tunnel from Titan to Ollama on Research.'; Arguments = $tunnelArguments },
        @{ Name = $taskNames[1]; Description = 'Runs the loopback-only Textbook Desk web application.'; Arguments = $appArguments }
    )

    foreach ($definition in $definitions) {
        if ($PSCmdlet.ShouldProcess($definition.Name, 'Register or update scheduled task')) {
            $taskAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument $definition.Arguments -WorkingDirectory $root
            Register-ScheduledTask `
                -TaskPath $taskPath `
                -TaskName $definition.Name `
                -Description $definition.Description `
                -Action $taskAction `
                -Trigger $trigger `
                -Settings $settings `
                -Principal $principal `
                -Force | Out-Null
        }
    }
    Get-TaskSummary | Format-Table -AutoSize
    return
}

if ($Action -eq 'Restart') {
    foreach ($name in $taskNames) {
        $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { throw "Scheduled task is not installed: $name" }
        if ($PSCmdlet.ShouldProcess($name, 'Stop and restart scheduled task')) {
            if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskPath $taskPath -TaskName $name }
            Start-ScheduledTask -TaskPath $taskPath -TaskName $name
        }
    }
    return
}

if ($Action -eq 'Remove') {
    foreach ($name in $taskNames) {
        $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "$name is already absent."
            continue
        }
        if ($PSCmdlet.ShouldProcess($name, 'Unregister Textbook Desk scheduled task')) {
            if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskPath $taskPath -TaskName $name }
            Unregister-ScheduledTask -TaskPath $taskPath -TaskName $name -Confirm:$false
        }
    }
}
