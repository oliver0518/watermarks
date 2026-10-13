# 停止本地 Flask 去水印服务（Windows PowerShell）
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path (Get-Location) "logs"
$PidFile = Join-Path $LogDir "server.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "未找到 PID 文件，服务可能未启动"
    exit 0
}

$pidVal = Get-Content $PidFile -ErrorAction SilentlyContinue
if ($pidVal -and (Get-Process -Id $pidVal -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $pidVal -Force
    Write-Host "已停止 pid=$pidVal"
} else {
    Write-Host "进程不存在（pid=$pidVal），清理 PID 文件"
}
Remove-Item $PidFile -ErrorAction SilentlyContinue