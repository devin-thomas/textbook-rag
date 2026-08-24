#Requires -Version 5.1

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $projectRoot 'scripts\TextbookDeploymentStatus.ps1')

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Case)
    if ($Actual -ne $Expected) {
        throw "$Case failed. Expected '$Expected', received '$Actual'."
    }
}

$taskNames = @(Get-TextbookDeploymentTaskNames)
Assert-Equal $taskNames.Count 2 'owned task count'
Assert-Equal ($taskNames -join ',') 'TextbookDesk-OllamaTunnel,TextbookDesk-App' 'owned task names'

$runningTask = [pscustomobject]@{ State = 'Running' }
$runningInfo = [pscustomobject]@{ LastTaskResult = 267009 }
$runningCheck = Get-TextbookTaskHealthCheck -TaskName $taskNames[0] -Task $runningTask -TaskInfo $runningInfo
Assert-Equal $runningCheck.Result 'PASS' 'running task health'

$readyTask = [pscustomobject]@{ State = 'Ready' }
$readyInfo = [pscustomobject]@{ LastTaskResult = 0 }
$readyCheck = Get-TextbookTaskHealthCheck -TaskName $taskNames[1] -Task $readyTask -TaskInfo $readyInfo
Assert-Equal $readyCheck.Result 'FAIL' 'non-running task health'

$missingCheck = Get-TextbookTaskHealthCheck -TaskName $taskNames[1] -Task $null -TaskInfo $null
Assert-Equal $missingCheck.Result 'FAIL' 'missing task health'

$duplicateCheck = Get-TextbookTaskHealthCheck -TaskName $taskNames[1] -Task @($runningTask, $readyTask) -TaskInfo $null
Assert-Equal $duplicateCheck.Result 'FAIL' 'duplicate task health'

$connections = @(
    [pscustomobject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8766; OwningProcess = 10 },
    [pscustomobject]@{ LocalAddress = '::1'; LocalPort = 11435; OwningProcess = 11 },
    [pscustomobject]@{ LocalAddress = '0.0.0.0'; LocalPort = 8766; OwningProcess = 12 },
    [pscustomobject]@{ LocalAddress = '::'; LocalPort = 11435; OwningProcess = 13 },
    [pscustomobject]@{ LocalAddress = '192.168.1.20'; LocalPort = 8766; OwningProcess = 14 },
    [pscustomobject]@{ LocalAddress = '0.0.0.0'; LocalPort = 9999; OwningProcess = 15 }
)
$listeners = @(Get-TextbookListenerAssessment -Connections $connections)
Assert-Equal $listeners.Count 5 'tracked listener count'
Assert-Equal (@($listeners | Where-Object { $_.Safety -eq 'SAFE' }).Count) 2 'safe listener count'
Assert-Equal (@($listeners | Where-Object { $_.Safety -eq 'UNSAFE' }).Count) 3 'unsafe listener count'

Write-Output 'PASS Textbook deployment task and listener status'
