#!/usr/bin/env bash
set -euo pipefail
ROOT="${HDFS_ROOT:-/disease_platform}"

if ! command -v hdfs >/dev/null 2>&1; then
  echo "[WARN] hdfs 命令不存在，无法上传 raw 数据。当前保持本地模式。"
  exit 0
fi

upload_if_exists() {
  local local_glob="$1"
  local hdfs_dir="$2"
  shopt -s nullglob
  local files=( $local_glob )
  shopt -u nullglob
  if (( ${#files[@]} > 0 )); then
    hdfs dfs -mkdir -p "$hdfs_dir"
    hdfs dfs -put -f "${files[@]}" "$hdfs_dir/"
    echo "uploaded ${#files[@]} -> $hdfs_dir"
  else
    echo "skip: no files match $local_glob"
  fi
}

upload_if_exists "data/raw/owid/*.csv" "$ROOT/raw/owid"
upload_if_exists "data/raw/world_bank/*.csv" "$ROOT/raw/world_bank"
upload_if_exists "data/raw/open_meteo/*/*.csv" "$ROOT/raw/open_meteo"
upload_if_exists "data/raw/who/*.csv" "$ROOT/raw/who"
upload_if_exists "data/raw/china_cdc/*.jsonl" "$ROOT/raw/china_cdc"
upload_if_exists "data/raw/demo/*.csv" "$ROOT/raw/demo"
