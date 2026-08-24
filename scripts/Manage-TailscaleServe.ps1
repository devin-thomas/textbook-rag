#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Inspect', 'Rollback')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'TailscaleServeStatus.ps1')

$tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $tailscale) { $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue }
if (-not $tailscale) { throw 'Tailscale CLI is required and was not found on PATH.' }

$rootTarget = 'http://127.0.0.1:8787'
$textbookTarget = 'http://127.0.0.1:8766/textbooks'

function Get-ServeStatusText {
    $output = & $tailscale.Source serve status 2>&1
    if ($LASTEXITCODE -ne 0) { throw "tailscale serve status failed: $($output -join [Environment]::NewLine)" }
    return ($output -join [Environment]::NewLine)
}

function Assert-ExistingRootPreserved {
    param([Parameter(Mandatory = $true)][string]$Status)
    $actualRootTarget = Get-TailscaleServeMappingTarget -Status $Status -Path '/'
    if ($actualRootTarget -ne $rootTarget) {
        $observed = if ($actualRootTarget) { $actualRootTarget } else { '<absent>' }
        throw "Expected existing root mapping '/ -> $rootTarget', observed '/ -> $observed'. Refusing to alter Serve configuration."
    }
}

$before = Get-ServeStatusText
if ($Action -eq 'Inspect') {
    Write-Output $before
    return
}

Assert-ExistingRootPreserved -Status $before
$beforeTextbookTarget = Get-TailscaleServeMappingTarget -Status $before -Path '/textbooks'

if ($Action -eq 'Install') {
    if ($beforeTextbookTarget -eq $textbookTarget) {
        Write-Host "The /textbooks mapping is already configured for $textbookTarget."
        return
    }
    if ($PSCmdlet.ShouldProcess('/textbooks', "Mount Tailscale Serve path to $textbookTarget")) {
        & $tailscale.Source serve --bg --yes --https=443 --set-path=/textbooks $textbookTarget
        if ($LASTEXITCODE -ne 0) { throw "Tailscale Serve path installation failed with exit code $LASTEXITCODE" }

        $after = Get-ServeStatusText
        Assert-ExistingRootPreserved -Status $after
        $afterTextbookTarget = Get-TailscaleServeMappingTarget -Status $after -Path '/textbooks'
        if ($afterTextbookTarget -ne $textbookTarget) {
            $observed = if ($afterTextbookTarget) { $afterTextbookTarget } else { '<absent>' }
            throw "Tailscale accepted the command, but '/textbooks -> $textbookTarget' was not confirmed (observed '$observed')."
        }
        Write-Output $after
    }
    return
}

if ($Action -eq 'Rollback') {
    if (-not $beforeTextbookTarget) {
        Write-Host 'The Textbook Desk /textbooks mapping is already absent.'
        return
    }
    if ($PSCmdlet.ShouldProcess('/textbooks', 'Remove only the Textbook Desk Tailscale Serve path')) {
        & $tailscale.Source serve --https=443 --set-path=/textbooks off
        if ($LASTEXITCODE -ne 0) { throw "Tailscale Serve rollback failed with exit code $LASTEXITCODE" }

        $after = Get-ServeStatusText
        Assert-ExistingRootPreserved -Status $after
        $afterTextbookTarget = Get-TailscaleServeMappingTarget -Status $after -Path '/textbooks'
        if ($afterTextbookTarget) {
            throw "The /textbooks mapping is still present after rollback (target '$afterTextbookTarget')."
        }
        Write-Output $after
    }
}
