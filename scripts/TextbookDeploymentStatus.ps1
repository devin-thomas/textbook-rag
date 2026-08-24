#Requires -Version 5.1

Set-StrictMode -Version Latest

function Get-TextbookDeploymentTaskNames {
    [CmdletBinding()]
    param()

    return @('TextbookDesk-OllamaTunnel', 'TextbookDesk-App')
}

function Get-TextbookListenerAssessment {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [object[]]$Connections = @()
    )

    foreach ($connection in $Connections) {
        if ($connection.LocalPort -notin @(8766, 11435)) { continue }
        $isLoopback = $connection.LocalAddress -in @('127.0.0.1', '::1')
        [pscustomobject]@{
            LocalAddress = [string]$connection.LocalAddress
            LocalPort = [int]$connection.LocalPort
            OwningProcess = [int]$connection.OwningProcess
            Safety = if ($isLoopback) { 'SAFE' } else { 'UNSAFE' }
        }
    }
}

function Get-TextbookTaskHealthCheck {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [AllowNull()][object]$Task,
        [AllowNull()][object]$TaskInfo
    )

    if ($null -eq $Task) {
        return [pscustomobject]@{
            Check = "Scheduled task $TaskName"
            Result = 'FAIL'
            Detail = 'Not installed at the root task path.'
        }
    }

    $tasks = @($Task)
    if ($tasks.Count -ne 1) {
        return [pscustomobject]@{
            Check = "Scheduled task $TaskName"
            Result = 'FAIL'
            Detail = "Expected one root task, observed $($tasks.Count)."
        }
    }

    $state = [string]$tasks[0].State
    $lastResult = if ($null -ne $TaskInfo) { [string]$TaskInfo.LastTaskResult } else { '<unavailable>' }
    $result = if ($state -eq 'Running') { 'PASS' } else { 'FAIL' }
    return [pscustomobject]@{
        Check = "Scheduled task $TaskName"
        Result = $result
        Detail = "State=$state; LastResult=$lastResult"
    }
}
