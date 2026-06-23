<#
.SYNOPSIS
  Free a TCP port by stopping whatever process is listening on it.

.DESCRIPTION
  Used by `make kill-port` to clear an orphaned dev server (typically a
  `resume-agent serve` grandchild left behind when `make dev` is interrupted
  on Windows, where Ctrl-C does not always propagate through `make -j2`).
#>
param(
    [int]$Port = 8000
)

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Output "Port $Port is already free."
    return
}

$conns.OwningProcess | Sort-Object -Unique | ForEach-Object {
    $proc = Get-Process -Id $_ -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Output "Stopping PID $($proc.Id) ($($proc.ProcessName)) on port $Port"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
Write-Output "Port $Port cleared."
