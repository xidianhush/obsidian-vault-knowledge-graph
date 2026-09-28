$ErrorActionPreference = "Continue"

$root = "D:\obsidian_vault\knowledge-graph"
$log  = "$root\sync-graph.log"
$lock = "$root\sync-graph.lock"

function Write-Log($msg) {
  "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -Append -Encoding UTF8 $log
}

# Prevent overlapping runs (a previous build still walking the vault).
if (Test-Path $lock) {
  $age = (Get-Date) - (Get-Item $lock).LastWriteTime
  if ($age.TotalHours -lt 2) {
    Write-Log "skipped: another run is still active"
    exit 0
  }
}
New-Item -ItemType File -Path $lock -Force | Out-Null

try {
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Log "sync FAILED: python not on PATH"
    exit 1
  }
  Set-Location $root
  # build.py 的输出含中文，不改输出编码会在日志里变成乱码
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
  $out  = & python build.py build 2>&1
  $code = $LASTEXITCODE
  $tail = ($out | Select-Object -Last 4) -join " | "
  if ($code -eq 0) {
    Write-Log "sync ok (exit 0): $tail"
  } else {
    Write-Log "sync FAILED (exit $code): $tail"
  }
} catch {
  Write-Log "sync EXCEPTION: $($_.Exception.Message)"
} finally {
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}

# Keep the log from growing unboundedly: keep only the last 400 lines.
$lines = Get-Content $log -Encoding UTF8
if ($lines -and $lines.Count -gt 400) {
  $lines | Select-Object -Last 400 | Set-Content $log -Encoding UTF8
}
