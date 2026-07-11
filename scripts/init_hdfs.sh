#!/usr/bin/env bash
set -euo pipefail

ROOT="${HDFS_ROOT:-/disease_platform}"

echo "[INFO] Checking hdfs command..."
if ! command -v hdfs >/dev/null 2>&1; then
  echo "[ERROR] hdfs command not found. Run this script on the Ubuntu VM after Hadoop is installed and PATH is configured."
  exit 1
fi

echo "[INFO] Checking HDFS availability..."
if ! hdfs dfs -ls / >/dev/null 2>&1; then
  echo "[ERROR] HDFS is not accessible. Start HDFS first:"
  echo "        start-dfs.sh"
  echo "[SAFEGUARD] This script never runs: hdfs namenode -format"
  exit 1
fi

echo "[INFO] Creating project HDFS directories under ${ROOT}"
for path in \
  "$ROOT" \
  "$ROOT/raw" \
  "$ROOT/silver" \
  "$ROOT/gold" \
  "$ROOT/serving" \
  "$ROOT/checkpoints"; do
  hdfs dfs -mkdir -p "$path"
  echo "[OK] $path"
done

echo "[INFO] Current project HDFS tree:"
hdfs dfs -ls -R "$ROOT" || true

echo "[DONE] HDFS project directories are ready."
