#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidatePattern('^[A-Za-z0-9._-]+$')][string]$SshHost = 'research',
    [ValidateRange(1024, 65535)][int]$LocalPort = 11435,
    [ValidateRange(1024, 65535)][int]$RemotePort = 11434
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) { throw 'OpenSSH client (ssh.exe) is required.' }

if (-not $WhatIfPreference) {
    $listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $bindings = ($listener | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) (PID $($_.OwningProcess))" }) -join ', '
        throw "Local port $LocalPort is already listening at $bindings. Inspect the owning process before starting another tunnel."
    }
}

$forward = "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}"
$arguments = @(
    '-N',
    '-T',
    '-o', 'BatchMode=yes',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-L', $forward,
    $SshHost
)

if ($PSCmdlet.ShouldProcess("$SshHost ($forward)", 'Start persistent Ollama SSH tunnel')) {
    $process = Start-Process -FilePath $ssh.Source -ArgumentList $arguments -NoNewWindow -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    $ownedListeners = @()
    while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
        $ownedListeners = @(
            Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $process.Id }
        )
        if ($ownedListeners.Count -gt 0) { break }
        Start-Sleep -Milliseconds 200
        $process.Refresh()
    }

    if ($process.HasExited) {
        throw "SSH tunnel exited before opening the listener (code $($process.ExitCode))."
    }
    if ($ownedListeners.Count -eq 0) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "SSH process $($process.Id) did not open local port $LocalPort within 10 seconds."
    }

    $allListeners = @(Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue)
    $unexpectedListeners = @($allListeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') })
    $ipv4Listener = @($ownedListeners | Where-Object { $_.LocalAddress -eq '127.0.0.1' })
    if ($unexpectedListeners.Count -gt 0 -or $ipv4Listener.Count -eq 0) {
        $bindings = ($allListeners | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) (PID $($_.OwningProcess))" }) -join ', '
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "SSH tunnel produced an unsafe listener set ($bindings); the new SSH process was stopped."
    }

    Write-Host "Verified loopback-only Ollama tunnel at 127.0.0.1:$LocalPort (PID $($process.Id))."
    try {
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "SSH tunnel exited with code $($process.ExitCode)" }
    }
    finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
}
