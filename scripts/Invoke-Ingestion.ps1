#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = '',
    [string]$EnvFile = '',
    [switch]$Rebuild,
    [ValidateRange(1, 128)][int]$BatchSize = 16
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

$root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
if (-not (Test-Path -LiteralPath (Join-Path $root 'config\sources.json') -PathType Leaf)) { throw "Source catalog not found under $root" }
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python environment not found: $python" }

. (Join-Path $PSScriptRoot 'Import-TextbookEnv.ps1')
if (-not $EnvFile) { $EnvFile = Join-Path $root '.env' }
Import-TextbookEnv -Path $EnvFile

$arguments = @('-m', 'textbook_rag.ingest', '--batch-size', $BatchSize.ToString())
if ($Rebuild) { $arguments += '--force' }
if ($PSCmdlet.ShouldProcess((Join-Path $root 'data'), 'Ingest configured textbooks and update the local index')) {
    Push-Location -LiteralPath $root
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "Ingestion failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}
