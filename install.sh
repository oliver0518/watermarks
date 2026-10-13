#!/bin/bash
# Watermark Remover 一键安装脚本 (macOS / Linux)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "==> Watermark Remover 1.0.0 安装"

# 检查 Python 3.10+
if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未检测到 python3，请安装 Python 3.10+" >&2
  echo "  macOS: brew install python@3.12" >&2
  echo "  Linux: sudo apt install python3 python3-venv python3-pip" >&2
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "错误：需要 Python 3.10+，当前是 $PY_VERSION" >&2
  exit 1
fi

# 检查 / 安装 ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "==> 未检测到 ffmpeg，正在尝试安装..."
  if [ "$(uname)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      brew install ffmpeg
    else
      echo "错误：请先安装 Homebrew (https://brew.sh)，然后执行 brew install ffmpeg" >&2
      exit 1
    fi
  else
    if command -v apt >/dev/null 2>&1; then
      sudo apt update && sudo apt install -y ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y ffmpeg
    elif command -v yum >/dev/null 2>&1; then
      sudo yum install -y ffmpeg
    else
      echo "错误：请手动安装 ffmpeg 后重新运行本脚本" >&2
      exit 1
    fi
  fi
fi

# 创建 venv 并安装依赖
echo "==> 创建虚拟环境并安装依赖..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

echo ""
echo "==> 安装完成！"
echo ""
echo "启动服务："
echo "  bash scripts/dev.sh"
echo ""
echo "浏览器访问："
echo "  http://127.0.0.1:8300"
echo ""
echo "停止服务："
echo "  bash scripts/stop.sh"