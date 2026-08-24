#Requires -Version 5.1

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$parseErrors = @()
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'scripts') -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $fileErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName,
        [ref]$tokens,
        [ref]$fileErrors
    )
    $parseErrors += $fileErrors
}

if ($parseErrors.Count -gt 0) {
    $parseErrors | Format-List
    throw "$($parseErrors.Count) PowerShell parse error(s) found."
}

Write-Output 'PASS PowerShell script syntax'
