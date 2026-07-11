#!/usr/bin/env bash
set -euo pipefail

WITH_YARN=false
if [[ "${1:-}" == "--with-yarn" ]]; then
  WITH_YARN=true
fi

echo "[INFO] jps before shutdown:"
jps || true

if [[ "$WITH_YARN" == "true" ]]; then
  echo "[INFO] Stopping YARN with stop-yarn.sh"
  stop-yarn.sh || true
else
  echo "[INFO] YARN stop not requested. Use --with-yarn if you started YARN."
fi

echo "[INFO] Stopping HDFS with stop-dfs.sh"
stop-dfs.sh || true

echo "[INFO] jps after shutdown:"
jps || true

echo "[SAFEGUARD] No HDFS data was deleted."
