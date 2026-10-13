#!/bin/bash
# 创建 .venv 并安装依赖（macOS / Linux）
set -e
cd "$(dirname "$0")/.."

PY=python3
# 优先使用 homebrew 或系统的 python3.12+，避免系统 3.9 过旧
for p in /opt/homebrew/bin/python3.12 /usr/bin/python3.12 python3.12 python3; do
  if command -v "$p" >/dev/null 2>&1; then
    PY="$p"
    break
  fi
done

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: 未检测到 python3，请先安装 Python 3.10+" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/python -m pip install -r requirements.txt -q
echo "deps-ready"