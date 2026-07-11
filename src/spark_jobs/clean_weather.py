from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.window import Window

from src.common.config import load_settings
from src.common.paths import project_path
from src.spark_jobs.schemas import weather_raw_schema
from src.spark_jobs.spark_session import create_spark, resolve_hdfs_paths


def write_json(path: str | Path, payload: dict) -> None:
    output = project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def missing_rates(df: DataFrame) -> dict[str, float]:
    total = df.count()
    if total == 0:
        return {column: 0.0 for column in df.columns}
    return {column: round(df.filter(F.col(column).isNull()).count() / total, 6) for column in df.columns}


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean Open-Meteo raw CSV files into Silver weather parquet.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--master", default=None)
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--quality-output", default="data/serving/weather_silver_quality.json")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    paths = resolve_hdfs_paths(settings)
    input_root = args.input or paths["weather_raw"]
    output_path = args.output or paths["weather_silver"]
    input_pattern = input_root.rstrip("/") + "/*/*.csv"

    spark = create_spark("clean_weather", config_path=project_path(args.config), master=args.master, check_hdfs=True)
    raw = spark.read.option("header", True).schema(weather_raw_schema()).csv(input_pattern)
    input_rows = raw.count()

    parsed = raw.select(
        F.to_date(F.col("date")).alias("date"),
        F.trim(F.col("location")).alias("location"),
        F.upper(F.trim(F.col("location_code"))).alias("location_code"),
        F.trim(F.col("representative_city")).alias("representative_city"),
        F.col("latitude").cast("double").alias("latitude"),
        F.col("longitude").cast("double").alias("longitude"),
        F.col("temperature_mean").cast("double").alias("temperature_mean"),
        F.col("temperature_max").cast("double").alias("temperature_max"),
        F.col("temperature_min").cast("double").alias("temperature_min"),
        F.col("precipitation_sum").cast("double").alias("precipitation_sum"),
        F.col("relative_humidity_mean").cast("double").alias("relative_humidity_mean"),
        F.col("wind_speed_max").cast("double").alias("wind_speed_max"),
        F.col("source").cast("string").alias("source"),
        F.to_timestamp(F.col("downloaded_at")).alias("collected_at"),
    ).filter(F.col("location_code").rlike("^[A-Z]{3}$") & F.col("date").isNotNull())

    duplicate_key_count = parsed.count() - parsed.dropDuplicates(["location_code", "date"]).count()
    dedup_window = Window.partitionBy("location_code", "date").orderBy(F.col("collected_at").desc_nulls_last())
    cleaned = (
        parsed.withColumn("_rn", F.row_number().over(dedup_window))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
        .withColumn("year", F.year("date"))
    )

    cleaned.write.mode("overwrite").partitionBy("year", "location_code").parquet(output_path)

    bounds = cleaned.agg(F.min("date").alias("date_min"), F.max("date").alias("date_max")).first()
    rows_by_country = {
        row["location_code"]: row["count"]
        for row in cleaned.groupBy("location_code").count().orderBy("location_code").collect()
    }
    quality = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": input_pattern,
        "output_path": output_path,
        "input_rows": input_rows,
        "output_rows": cleaned.count(),
        "country_count": cleaned.select("location_code").distinct().count(),
        "date_min": str(bounds["date_min"]),
        "date_max": str(bounds["date_max"]),
        "duplicate_key_count": duplicate_key_count,
        "rows_by_country": rows_by_country,
        "missing_rate_by_column": missing_rates(cleaned),
        "temperature_unit": "°C, from Open-Meteo daily archive metadata",
        "precipitation_unit": "mm",
        "wind_speed_unit": "km/h",
        "representative_city_notice": "代表城市天气仅作为国家天气背景的近似代理，不代表整个国家的气象状况。",
    }
    write_json(args.quality_output, quality)
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
