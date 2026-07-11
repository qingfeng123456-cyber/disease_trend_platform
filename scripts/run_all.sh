#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---demo}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [[ "$MODE" == "--demo" ]]; then
  "$PYTHON_BIN" -m src.collectors.generate_demo_data
  "$PYTHON_BIN" -m src.models.run_models --demo
  echo "Demo 数据已生成。运行 bash scripts/start_web.sh 后访问 http://服务器IP:5000"
elif [[ "$MODE" == "--real" ]]; then
  "$PYTHON_BIN" -m src.collectors.run_all
  bash scripts/init_hdfs.sh
  bash scripts/upload_raw_to_hdfs.sh
  bash scripts/run_pipeline.sh
else
  echo "用法: bash scripts/run_all.sh --demo 或 bash scripts/run_all.sh --real"
  exit 2
fi
