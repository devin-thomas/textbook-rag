[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InputPath,
    [string]$OutputDirectory = 'reports\generated\quiz',
    [string]$BaseUrl = 'http://127.0.0.1:8766/textbooks',
    [ValidateRange(0.1, 120.0)]
    [double]$RequestsPerMinute = 6.0,
    [ValidateRange(0, 10)]
    [int]$MaxRetries = 3,
    [switch]$Resume,
    [switch]$NoHistory
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Textbook Desk Python environment not found. Run scripts\Setup-TextbookRag.ps1 first."
}
$resolvedOutputDirectory = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
}

$arguments = @(
    '-m', 'textbook_rag.quiz',
    (Resolve-Path -LiteralPath $InputPath).Path,
    '--output-dir', $resolvedOutputDirectory,
    '--base-url', $BaseUrl,
    '--requests-per-minute', $RequestsPerMinute.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--max-retries', $MaxRetries.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($Resume) { $arguments += '--resume' }
if ($NoHistory) { $arguments += '--no-history' }

& $python @arguments
exit $LASTEXITCODE
