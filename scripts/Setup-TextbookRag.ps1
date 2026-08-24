#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = '',
    [switch]$SkipFrontend,
    [switch]$SkipPython,
    [switch]$IncludeDevDependencies
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

function Resolve-ValidatedProjectRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ([System.IO.Path]::GetPathRoot($resolved) -eq $resolved) {
        throw "Refusing to use a filesystem root as ProjectRoot: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved 'SPEC.md') -PathType Leaf)) {
        throw "ProjectRoot does not look like Textbook Desk (SPEC.md is missing): $resolved"
    }
    return $resolved.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

function Find-Python312Launcher {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = 'py.exe'; Prefix = @('-3.12') }
        }
    }

    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = 'python.exe'; Prefix = @() }
        }
    }

    throw 'Python 3.12 is required. Install it, then rerun this script.'
}

$root = Resolve-ValidatedProjectRoot -Path $ProjectRoot
$venvPath = Join-Path $root '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$frontendPath = Join-Path $root 'frontend'

if (-not $SkipPython) {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'pyproject.toml') -PathType Leaf)) {
        throw "pyproject.toml is missing from $root"
    }

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $launcher = Find-Python312Launcher
        if ($PSCmdlet.ShouldProcess($venvPath, 'Create Python 3.12 virtual environment')) {
            & $launcher.Command @($launcher.Prefix) -m venv $venvPath
            if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE" }
        }
    }

    if ($PSCmdlet.ShouldProcess($root, 'Install Textbook Desk Python dependencies')) {
        & $venvPython -m pip install --disable-pip-version-check --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }

        $installTarget = if ($IncludeDevDependencies) { "$root[dev]" } else { $root }
        & $venvPython -m pip install --disable-pip-version-check --editable $installTarget
        if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed with exit code $LASTEXITCODE" }
    }
}

if (-not $SkipFrontend) {
    $packageJson = Join-Path $frontendPath 'package.json'
    $packageLock = Join-Path $frontendPath 'package-lock.json'
    if (-not (Test-Path -LiteralPath $packageJson -PathType Leaf)) {
        throw "Frontend package metadata is missing: $packageJson"
    }
    if (-not (Test-Path -LiteralPath $packageLock -PathType Leaf)) {
        throw "A deterministic frontend install requires package-lock.json: $packageLock"
    }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw 'npm is required to install and build the frontend.'
    }

    if ($PSCmdlet.ShouldProcess($frontendPath, 'Install locked frontend dependencies and build production assets')) {
        Push-Location -LiteralPath $frontendPath
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed with exit code $LASTEXITCODE" }
        }
        finally {
            Pop-Location
        }
    }
}

Write-Host "Textbook Desk setup completed for $root"
