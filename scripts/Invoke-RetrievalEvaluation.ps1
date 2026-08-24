#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = '',
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

$root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
if (-not (Test-Path -LiteralPath (Join-Path $root 'eval\questions.json') -PathType Leaf)) {
    throw "Evaluation set not found under $root"
}
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python environment not found: $python" }

. (Join-Path $PSScriptRoot 'Import-TextbookEnv.ps1')
if (-not $EnvFile) { $EnvFile = Join-Path $root '.env' }
Import-TextbookEnv -Path $EnvFile

$questions = Join-Path $root 'eval\questions.json'
$jsonReport = Join-Path $root 'reports\generated\retrieval-evaluation.json'
$markdownReport = Join-Path $root 'reports\generated\retrieval-evaluation.md'
$arguments = @(
    '-m', 'textbook_rag.evaluate',
    '--questions', $questions,
    '--json', $jsonReport,
    '--markdown', $markdownReport
)

if ($PSCmdlet.ShouldProcess((Join-Path $root 'reports\generated'), 'Run retrieval evaluation and write reports')) {
    Push-Location -LiteralPath $root
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "Retrieval evaluation failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}
