# 创建 .venv 并安装依赖（Windows PowerShell）
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "未检测到 python，请先安装 Python 3.10+ 并加入 PATH（推荐从 https://www.python.org/downloads/ 安装）"
    exit 1
}

if (-not (Test-Path .\.venv)) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Host "deps-ready"