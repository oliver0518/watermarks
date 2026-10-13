# Watermark Remover 一键安装脚本 (Windows PowerShell)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

Write-Host "==> Watermark Remover 1.0.0 安装" -ForegroundColor Cyan

# 检查 Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "错误：未检测到 python，请先安装 Python 3.10+" -ForegroundColor Red
    Write-Host "  下载地址：https://www.python.org/downloads/"
    Write-Host "  安装时务必勾选 'Add Python to PATH'"
    exit 1
}

$needVersion = & python -c "import sys; print(sys.version_info >= (3, 10))"
if ($needVersion -ne "True") {
    $pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Write-Host "错误：需要 Python 3.10+，当前是 $pyVersion" -ForegroundColor Red
    exit 1
}

# 检查 ffmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "警告：未检测到 ffmpeg" -ForegroundColor Yellow
    Write-Host "  推荐安装：choco install ffmpeg"
    Write-Host "  或从 https://ffmpeg.org/download.html 下载并加入 PATH"
    Write-Host ""
    $continue = Read-Host "是否继续安装？(y/n)"
    if ($continue -ne "y") { exit 1 }
}

# 创建 venv
Write-Host "==> 创建虚拟环境并安装依赖..." -ForegroundColor Cyan
if (-not (Test-Path .\.venv)) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet

Write-Host ""
Write-Host "==> 安装完成！" -ForegroundColor Green
Write-Host ""
Write-Host "启动服务："
Write-Host "  .\scripts\dev.ps1"
Write-Host ""
Write-Host "浏览器访问："
Write-Host "  http://127.0.0.1:8300"
Write-Host ""
Write-Host "停止服务："
Write-Host "  .\scripts\stop.ps1"