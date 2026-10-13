#!/bin/bash
# 停止本地 Flask 去水印服务（macOS / Linux）
set -e
cd "$(dirname "$0")/.."
LOG_DIR="$(pwd)/logs"
PID_FILE="$LOG_DIR/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "未找到 PID 文件，服务可能未启动"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -z "$PID" ]; then
  rm -f "$PID_FILE"
  echo "PID 文件为空，已清理"
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "已发送停止信号给 pid=$PID"
  for _ in 1 2 3 4 5; do
    sleep 1
    if ! kill -0 "$PID" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "服务已停止"
      exit 0
    fi
  done
  echo "服务未能在 5 秒内停止，强制 kill -9"
  kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE"
echo "服务已停止"