#!/usr/bin/env bash
# Campaign Edit —— 本地一键启动
#
# 用法：
#   ./scripts/dev.sh              同时启动前后端（Ctrl+C 停止）
#   ./scripts/dev.sh backend      只启动后端
#   ./scripts/dev.sh frontend     只启动前端
#   ./scripts/dev.sh test         跑端到端冒烟测试
#
# Windows 用户可改用 scripts/dev.ps1

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
MODE="${1:-all}"

PY_BIN=""
if [ -x "$BACKEND/.venv/bin/python" ]; then
  PY_BIN="$BACKEND/.venv/bin/python"
elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
  PY_BIN="$BACKEND/.venv/Scripts/python.exe"
else
  PY_BIN="$(command -v python3 || command -v python)"
fi

echo "项目根目录: $ROOT"
echo "Python: $PY_BIN"

ensure_backend() {
  if [ ! -d "$BACKEND/.venv" ]; then
    echo "==> 创建后端虚拟环境"
    "$PY_BIN" -m venv "$BACKEND/.venv"
    "$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements.txt" 2>/dev/null \
      || "$BACKEND/.venv/Scripts/python.exe" -m pip install -r "$BACKEND/requirements.txt"
  fi
  if [ -x "$BACKEND/.venv/bin/python" ]; then PY_BIN="$BACKEND/.venv/bin/python";
  else PY_BIN="$BACKEND/.venv/Scripts/python.exe"; fi
}

wait_for_api() {
  echo "==> 等待后端就绪"
  for i in $(seq 1 40); do
    if curl -sf --max-time 3 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
      echo "    后端就绪: http://127.0.0.1:8000/docs"
      return 0
    fi
    sleep 1.5
  done
  echo "    后端启动超时，请检查日志"
  return 1
}

start_backend() {
  ensure_backend
  cd "$BACKEND"
  "$PY_BIN" -m uvicorn app.main:app --reload --port 8000
}

start_frontend() {
  cd "$FRONTEND"
  if [ ! -d node_modules ]; then
    echo "==> 安装前端依赖"
    npm install
  fi
  npm run dev
}

case "$MODE" in
  backend)
    start_backend
    ;;
  frontend)
    start_frontend
    ;;
  test)
    ensure_backend
    cd "$BACKEND"
    "$PY_BIN" scripts/smoke_test.py "${2:-http://127.0.0.1:8000}"
    ;;
  all)
    echo "==> 启动后端"
    (cd "$BACKEND" && "$PY_BIN" -m uvicorn app.main:app --reload --port 8000) &
    BACKEND_PID=$!
    trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT INT TERM
    wait_for_api || exit 1
    echo
    echo "后端: http://127.0.0.1:8000/docs"
    echo "前端: http://127.0.0.1:5173"
    echo
    start_frontend
    ;;
  *)
    echo "未知模式: $MODE（可选 all|backend|frontend|test）"
    exit 1
    ;;
esac