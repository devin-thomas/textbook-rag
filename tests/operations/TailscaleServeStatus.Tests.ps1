#Requires -Version 5.1

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $projectRoot 'scripts\TailscaleServeStatus.ps1')

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Case)
    if ($Actual -ne $Expected) {
        throw "$Case failed. Expected '$Expected', received '$Actual'."
    }
}

$validStatus = @'
https://titan.example.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8787
|-- /textbooks proxy http://127.0.0.1:8766/textbooks
'@
Assert-Equal (Get-TailscaleServeMappingTarget -Status $validStatus -Path '/') 'http://127.0.0.1:8787' 'root mapping'
Assert-Equal (Get-TailscaleServeMappingTarget -Status $validStatus -Path '/textbooks') 'http://127.0.0.1:8766/textbooks' 'textbook mapping'
$validChecks = @(Get-TailscaleServeHealthChecks -Status $validStatus)
Assert-Equal $validChecks.Count 2 'valid mapping check count'
Assert-Equal ($validChecks.Result -join ',') 'PASS,PASS' 'valid mapping health'

$staleStatus = @'
https://titan.example.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8787
|-- /textbooks proxy http://127.0.0.1:9999/stale
|-- /other proxy http://127.0.0.1:8766/textbooks
'@
Assert-Equal (Get-TailscaleServeMappingTarget -Status $staleStatus -Path '/textbooks') 'http://127.0.0.1:9999/stale' 'stale mapping cannot borrow another path target'
Assert-Equal (Get-TailscaleServeMappingTarget -Status $staleStatus -Path '/other') 'http://127.0.0.1:8766/textbooks' 'other mapping'
$staleChecks = @(Get-TailscaleServeHealthChecks -Status $staleStatus)
Assert-Equal $staleChecks[0].Result 'PASS' 'stale status root remains valid'
Assert-Equal $staleChecks[1].Result 'FAIL' 'stale textbook target is unhealthy'

$borrowedTargetStatus = @'
https://titan.example.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8787
|-- /other proxy http://127.0.0.1:8766/textbooks
'@
Assert-Equal (Get-TailscaleServeMappingTarget -Status $borrowedTargetStatus -Path '/textbooks') $null 'target URL under another path is not a textbook mapping'
$borrowedChecks = @(Get-TailscaleServeHealthChecks -Status $borrowedTargetStatus)
Assert-Equal $borrowedChecks[1].Result 'FAIL' 'borrowed target is not healthy'

$absentStatus = @'
https://titan.example.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8787
'@
Assert-Equal (Get-TailscaleServeMappingTarget -Status $absentStatus -Path '/textbooks') $null 'absent mapping'

$duplicateStatus = @'
https://titan.example.ts.net (tailnet only)
|-- /textbooks proxy http://127.0.0.1:8766/textbooks
|-- /textbooks proxy http://127.0.0.1:9999/stale
'@
$duplicateRejected = $false
try {
    [void](Get-TailscaleServeMappingTarget -Status $duplicateStatus -Path '/textbooks')
}
catch {
    $duplicateRejected = $true
}
if (-not $duplicateRejected) { throw 'duplicate mapping case was not rejected' }
$duplicateChecks = @(Get-TailscaleServeHealthChecks -Status $duplicateStatus)
Assert-Equal $duplicateChecks[1].Result 'FAIL' 'duplicate mapping health check'

Write-Output 'PASS Tailscale Serve status path-target parsing'
