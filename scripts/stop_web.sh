#!/usr/bin/env bash
set -euo pipefail

PORT="${FLASK_PORT:-5000}"
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:"$PORT" || true)"
  if [[ -n "$PIDS" ]]; then
    kill $PIDS
    echo "已停止监听端口 $PORT 的 Flask 进程。"
  else
    echo "端口 $PORT 没有发现进程。"
  fi
else
  echo "lsof 不存在，请手动停止 Flask 进程。"
fi
