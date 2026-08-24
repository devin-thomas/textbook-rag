#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$TailnetUrl = '',
    [ValidateRange(1, 60)][int]$TimeoutSeconds = 10,
    [switch]$SkipConfigurationChecks
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'TextbookDeploymentStatus.ps1')
. (Join-Path $PSScriptRoot 'TailscaleServeStatus.ps1')

function Test-HttpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSeconds
        [pscustomobject]@{ Check = $Name; Result = 'PASS'; Detail = "HTTP $([int]$response.StatusCode) $Uri" }
    }
    catch {
        [pscustomobject]@{ Check = $Name; Result = 'FAIL'; Detail = "$Uri - $($_.Exception.Message)" }
    }
}

$results = @()
try {
    $connections = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    $listenerAssessment = @(Get-TextbookListenerAssessment -Connections $connections)
    $unexpectedListeners = @($listenerAssessment | Where-Object { $_.Safety -eq 'UNSAFE' })
    if ($unexpectedListeners.Count -gt 0) {
        $addresses = ($unexpectedListeners | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }) -join ', '
        $results += [pscustomobject]@{ Check = 'Loopback listener policy'; Result = 'FAIL'; Detail = "Unsafe listener(s): $addresses" }
    }
    else {
        $safeBindings = ($listenerAssessment | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }) -join ', '
        if (-not $safeBindings) { $safeBindings = 'No Textbook Desk listeners found.' }
        $results += [pscustomobject]@{ Check = 'Loopback listener policy'; Result = 'PASS'; Detail = $safeBindings }
    }
}
catch {
    $results += [pscustomobject]@{ Check = 'Loopback listener policy'; Result = 'FAIL'; Detail = $_.Exception.Message }
}

if ($SkipConfigurationChecks) {
    $results += [pscustomobject]@{ Check = 'Scheduled task configuration'; Result = 'SKIP'; Detail = 'Skipped by -SkipConfigurationChecks.' }
    $results += [pscustomobject]@{ Check = 'Tailscale Serve configuration'; Result = 'SKIP'; Detail = 'Skipped by -SkipConfigurationChecks.' }
}
else {
    foreach ($taskName in @(Get-TextbookDeploymentTaskNames)) {
        try {
            $task = @(Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue)
            $taskInfo = if ($task.Count -eq 1) {
                Get-ScheduledTaskInfo -TaskPath '\' -TaskName $taskName -ErrorAction Stop
            }
            else { $null }
            $taskValue = if ($task.Count -eq 0) { $null } else { $task }
            $results += Get-TextbookTaskHealthCheck -TaskName $taskName -Task $taskValue -TaskInfo $taskInfo
        }
        catch {
            $results += [pscustomobject]@{ Check = "Scheduled task $taskName"; Result = 'FAIL'; Detail = $_.Exception.Message }
        }
    }

    try {
        $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
        if (-not $tailscale) { $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue }
        if (-not $tailscale) { throw 'Tailscale CLI is required and was not found on PATH.' }
        $serveOutput = & $tailscale.Source serve status 2>&1
        if ($LASTEXITCODE -ne 0) { throw "tailscale serve status failed: $($serveOutput -join [Environment]::NewLine)" }
        $results += Get-TailscaleServeHealthChecks -Status ($serveOutput -join [Environment]::NewLine)
    }
    catch {
        $results += [pscustomobject]@{ Check = 'Tailscale Serve configuration'; Result = 'FAIL'; Detail = $_.Exception.Message }
    }
}

$results += Test-HttpEndpoint -Name 'Existing root app' -Uri 'http://127.0.0.1:8787/'
$results += Test-HttpEndpoint -Name 'Textbook Desk health' -Uri 'http://127.0.0.1:8766/textbooks/api/health'
$results += Test-HttpEndpoint -Name 'Textbook Desk UI' -Uri 'http://127.0.0.1:8766/textbooks/'
$results += Test-HttpEndpoint -Name 'Ollama tunnel' -Uri 'http://127.0.0.1:11435/api/tags'

if ($TailnetUrl) {
    $baseUrl = $TailnetUrl.TrimEnd('/')
    if ($baseUrl -notmatch '^https://[A-Za-z0-9.-]+\.ts\.net$') {
        throw "TailnetUrl must be an HTTPS ts.net origin, received: $TailnetUrl"
    }
    $results += Test-HttpEndpoint -Name 'Tailnet root' -Uri "$baseUrl/"
    $results += Test-HttpEndpoint -Name 'Tailnet Textbook Desk' -Uri "$baseUrl/textbooks/"
}

$results | Format-Table -AutoSize -Wrap
if ($results.Result -contains 'FAIL') { throw 'One or more deployment checks failed.' }
