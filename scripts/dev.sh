#!/bin/bash
# 后台启动本地 Flask 去水印服务（macOS / Linux）
set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
PORT="${DEPLOY_RUN_PORT:-8300}"
PID_FILE="$LOG_DIR/server.pid"
LOG_FILE="$LOG_DIR/server.log"

if [ ! -x "./.venv/bin/python" ]; then
  echo "error: .venv 不存在，请先执行 bash scripts/prepare.sh" >&2
  exit 1
fi

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
  EXIST_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$EXIST_PID" ] && kill -0 "$EXIST_PID" 2>/dev/null; then
    echo "服务已在运行（pid=$EXIST_PID），如需重启请先执行 bash scripts/stop.sh"
    exit 1
  fi
  rm -f "$PID_FILE"
fi

# macOS / Linux 用 nohup + disown 脱离当前会话
nohup ./.venv/bin/python app.py > "$LOG_FILE" 2>&1 < /dev/null &
PID=$!
echo "$PID" > "$PID_FILE"
disown 2>/dev/null || true

# 等 1 秒确认进程未立即崩溃
sleep 1
if ! kill -0 "$PID" 2>/dev/null; then
  echo "error: 服务进程已退出，请查看日志：$LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi

echo "server starting, pid=$PID port=$PORT http://127.0.0.1:$PORT"