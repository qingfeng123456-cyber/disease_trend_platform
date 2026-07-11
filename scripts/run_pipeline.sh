#!/usr/bin/env bash
set -euo pipefail
ROOT="${HDFS_ROOT:-/disease_platform}"

if ! command -v spark-submit >/dev/null 2>&1; then
  echo "[WARN] spark-submit 命令不存在，跳过 Spark 流水线。可先运行 python -m src.collectors.generate_demo_data 查看本地演示。"
  exit 0
fi

spark-submit src/spark_jobs/clean_epidemic.py \
  --input "$ROOT/raw/owid/*.csv" \
  --output "$ROOT/silver/epidemic_daily"

spark-submit src/spark_jobs/clean_weather.py \
  --input "$ROOT/raw/open_meteo/*.csv" \
  --output "$ROOT/silver/weather_daily"

spark-submit src/spark_jobs/clean_population.py \
  --input "$ROOT/raw/world_bank/*.csv" \
  --output "$ROOT/silver/population_yearly"

spark-submit src/spark_jobs/build_features.py \
  --epidemic "$ROOT/silver/epidemic_daily" \
  --weather "$ROOT/silver/weather_daily" \
  --population "$ROOT/silver/population_yearly" \
  --output "$ROOT/gold/forecast_features" \
  --horizon 7

spark-submit src/spark_jobs/data_quality_report.py \
  --features "$ROOT/gold/forecast_features" \
  --output data/serving/data_quality_report.json

spark-submit src/spark_jobs/train_gbt.py \
  --input "$ROOT/gold/forecast_features" \
  --model-output "$ROOT/models/gbt_t_plus_7" \
  --prediction-output "$ROOT/gold/predictions" \
  --metrics-local data/serving/model_metrics.json

spark-submit src/spark_jobs/export_dashboard.py \
  --features "$ROOT/gold/forecast_features" \
  --predictions "$ROOT/gold/predictions" \
  --serving-dir data/serving \
  --default-location CHN
