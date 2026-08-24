#Requires -Version 5.1

Set-StrictMode -Version Latest

function Get-TailscaleServeMappingTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][ValidatePattern('^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*$')][string]$Path
    )

    $pathPattern = [regex]::Escape($Path)
    $pattern = "(?m)^\s*\|--\s+$pathPattern\s+proxy\s+(\S+)\s*$"
    $matches = [regex]::Matches($Status, $pattern)
    if ($matches.Count -gt 1) {
        throw "Tailscale Serve status contains more than one mapping for '$Path'."
    }
    if ($matches.Count -eq 0) { return $null }
    return $matches[0].Groups[1].Value
}

function Get-TailscaleServeHealthChecks {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$ExpectedRootTarget = 'http://127.0.0.1:8787',
        [string]$ExpectedTextbookTarget = 'http://127.0.0.1:8766/textbooks'
    )

    foreach ($mapping in @(
        @{ Name = 'Tailscale Serve root mapping'; Path = '/'; Expected = $ExpectedRootTarget },
        @{ Name = 'Tailscale Serve textbook mapping'; Path = '/textbooks'; Expected = $ExpectedTextbookTarget }
    )) {
        try {
            $actual = Get-TailscaleServeMappingTarget -Status $Status -Path $mapping.Path
            $observed = if ($actual) { $actual } else { '<absent>' }
            [pscustomobject]@{
                Check = $mapping.Name
                Result = if ($actual -eq $mapping.Expected) { 'PASS' } else { 'FAIL' }
                Detail = "$($mapping.Path) -> $observed (expected $($mapping.Expected))"
            }
        }
        catch {
            [pscustomobject]@{
                Check = $mapping.Name
                Result = 'FAIL'
                Detail = $_.Exception.Message
            }
        }
    }
}
