#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = '',
    [ValidateRange(1024, 65535)][int]$Port = 8766,
    [string]$HostAddress = '127.0.0.1',
    [string]$EnvFile = '',
    [string]$NvidiaDotEnvPath = '',
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

$root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
if ([System.IO.Path]::GetPathRoot($root) -eq $root) { throw "Refusing to run from a filesystem root: $root" }
if (-not (Test-Path -LiteralPath (Join-Path $root 'SPEC.md') -PathType Leaf)) {
    throw "ProjectRoot does not look like Textbook Desk: $root"
}
if ($HostAddress -ne '127.0.0.1') {
    throw "Textbook Desk must bind to 127.0.0.1; received '$HostAddress'."
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment not found at $python. Run scripts\Setup-TextbookRag.ps1 first."
}

if (-not $EnvFile) { $EnvFile = Join-Path $root '.env' }
. (Join-Path $PSScriptRoot 'Import-TextbookEnv.ps1')
Import-TextbookEnv -Path $EnvFile

if ($NvidiaDotEnvPath) {
    $resolvedDotEnv = [System.IO.Path]::GetFullPath($NvidiaDotEnvPath)
    if (-not (Test-Path -LiteralPath $resolvedDotEnv -PathType Leaf)) {
        throw "NVIDIA dotenv file not found: $resolvedDotEnv"
    }
    $env:NVIDIA_DOTENV_PATH = $resolvedDotEnv
}

$env:TEXTBOOK_HOST = $HostAddress
$env:TEXTBOOK_PORT = $Port.ToString([System.Globalization.CultureInfo]::InvariantCulture)
$env:TEXTBOOK_ROOT_PATH = '/textbooks'
$arguments = @('-m', 'uvicorn', 'textbook_rag.app:app', '--host', $HostAddress, '--port', $Port.ToString())
if ($Reload) { $arguments += '--reload' }

if ($PSCmdlet.ShouldProcess("http://${HostAddress}:$Port/textbooks", 'Start Textbook Desk')) {
    Push-Location -LiteralPath $root
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "Textbook Desk exited with code $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}
