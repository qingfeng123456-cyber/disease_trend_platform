#!/usr/bin/env bash
set -euo pipefail

WITH_YARN=false
if [[ "${1:-}" == "--with-yarn" ]]; then
  WITH_YARN=true
fi

echo "[INFO] jps before startup:"
jps || true

if ! command -v hdfs >/dev/null 2>&1; then
  echo "[ERROR] hdfs command not found. Configure Hadoop before starting services."
  exit 1
fi

if ! jps | grep -Eq "NameNode|DataNode"; then
  echo "[INFO] Starting HDFS with start-dfs.sh"
  start-dfs.sh
else
  echo "[INFO] HDFS processes already visible in jps."
fi

if [[ "$WITH_YARN" == "true" ]]; then
  if ! jps | grep -Eq "ResourceManager|NodeManager"; then
    echo "[INFO] Starting YARN with start-yarn.sh"
    start-yarn.sh
  else
    echo "[INFO] YARN processes already visible in jps."
  fi
else
  echo "[INFO] YARN not requested. Spark local[*] mode does not require YARN."
fi

echo "[INFO] jps after startup:"
jps || true

echo "[INFO] HDFS report:"
hdfs dfsadmin -report

echo "[SAFEGUARD] This script never runs: hdfs namenode -format"
