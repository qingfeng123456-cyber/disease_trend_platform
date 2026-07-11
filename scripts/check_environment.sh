#!/usr/bin/env bash
set -euo pipefail

echo "== 当前目录 =="
pwd

echo "== 文件清单 =="
find . -maxdepth 3 -type f | sort

echo "== Python =="
if command -v python3 >/dev/null 2>&1; then
  python3 --version
elif command -v python >/dev/null 2>&1; then
  python --version
else
  echo "python3/python 未找到"
fi

echo "== Java =="
if command -v java >/dev/null 2>&1; then
  java -version
else
  echo "java 未找到"
fi

echo "== Hadoop =="
if command -v hadoop >/dev/null 2>&1; then
  hadoop version
else
  echo "hadoop 未找到"
fi

echo "== Spark =="
if command -v spark-submit >/dev/null 2>&1; then
  spark-submit --version
else
  echo "spark-submit 未找到"
fi

echo "== Git =="
if command -v git >/dev/null 2>&1; then
  git status
else
  echo "git 未找到"
fi
