# 后台启动本地 Flask 去水印服务（Windows PowerShell）
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$ProjectRoot = (Get-Location)
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Port = if ($env:DEPLOY_RUN_PORT) { $env:DEPLOY_RUN_PORT } else { "8300" }
$PidFile = Join-Path $LogDir "server.pid"
$LogFile = Join-Path $LogDir "server.log"

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    Write-Error ".venv 不存在，请先执行 .\scripts\prepare.ps1"
    exit 1
}

# 检查是否已在运行
if (Test-Path $PidFile) {
    $existing = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Host "服务已在运行（pid=$existing），如需重启请先执行 .\scripts\stop.ps1"
        exit 1
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

# 使用 Start-Process 后台启动，日志重定向到文件
$proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "app.py" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $LogFile `
    -WindowStyle Hidden `
    -PassThru

if ($null -eq $proc) {
    Write-Error "启动失败，请查看日志：$LogFile"
    exit 1
}

$proc.Id | Out-File -Encoding ascii $PidFile
Write-Host "server starting, pid=$($proc.Id) port=$Port http://127.0.0.1:$Port"