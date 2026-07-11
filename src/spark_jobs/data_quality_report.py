from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyspark.sql import DataFrame, functions as F

from src.common.config import get_setting, load_settings
from src.common.hdfs_cli import HdfsCli, HdfsCliError
from src.common.paths import project_path
from src.spark_jobs.spark_session import create_spark, hdfs_uri, resolve_hdfs_paths


def missing_rates(df: DataFrame) -> dict[str, float]:
    total = df.count()
    if total == 0:
        return {column: 0.0 for column in df.columns}
    return {column: round(df.filter(F.col(column).isNull()).count() / total, 6) for column in df.columns}


def safe_min_max(df: DataFrame, column: str) -> tuple[str | None, str | None]:
    if column not in df.columns:
        return None, None
    row = df.agg(F.min(column).alias("min_value"), F.max(column).alias("max_value")).first()
    return (str(row["min_value"]) if row["min_value"] is not None else None, str(row["max_value"]) if row["max_value"] is not None else None)


def count_duplicate(df: DataFrame, keys: list[str]) -> int:
    if not all(key in df.columns for key in keys):
        return 0
    total = df.count()
    distinct = df.dropDuplicates(keys).count()
    return total - distinct


def epidemic_report(df: DataFrame) -> dict[str, Any]:
    date_min, date_max = safe_min_max(df, "date")
    unmapped = [
        row["location"]
        for row in df.filter(F.col("location_code").isNull()).select("location").distinct().orderBy("location").collect()
    ]
    return {
        "input_rows": None,
        "output_rows": df.count(),
        "date_min": date_min,
        "date_max": date_max,
        "country_count": df.select("location").distinct().count(),
        "duplicate_count": count_duplicate(df, ["location_code", "location", "date"]),
        "unmapped_country_count": len(unmapped),
        "unmapped_countries": unmapped,
        "national_province_conflict_count": df.filter(F.col("aggregation_conflict")).count()
        if "aggregation_conflict" in df.columns
        else 0,
        "negative_case_correction_count": df.filter(F.col("is_negative_case_correction")).count()
        if "is_negative_case_correction" in df.columns
        else 0,
        "negative_death_correction_count": df.filter(F.col("is_negative_death_correction")).count()
        if "is_negative_death_correction" in df.columns
        else 0,
        "missing_rate_by_column": missing_rates(df),
    }


def population_report(df: DataFrame) -> dict[str, Any]:
    year_min, year_max = safe_min_max(df, "year")
    return {
        "input_rows": None,
        "output_rows": df.count(),
        "country_count": df.select("location_code").distinct().count(),
        "year_min": int(year_min) if year_min is not None else None,
        "year_max": int(year_max) if year_max is not None else None,
        "duplicate_count": count_duplicate(df, ["location_code", "year"]),
        "missing_rate_by_column": missing_rates(df),
    }


def weather_report(df: DataFrame) -> dict[str, Any]:
    date_min, date_max = safe_min_max(df, "date")
    rows_by_country = {
        row["location_code"]: row["count"]
        for row in df.groupBy("location_code").count().orderBy("location_code").collect()
    }
    return {
        "input_rows": None,
        "output_rows": df.count(),
        "country_count": df.select("location_code").distinct().count(),
        "date_min": date_min,
        "date_max": date_max,
        "duplicate_key_count": count_duplicate(df, ["location_code", "date"]),
        "rows_by_country": rows_by_country,
        "missing_rate_by_column": missing_rates(df),
        "representative_city_notice": "代表城市天气仅作为国家天气背景的近似代理，不代表整个国家的气象状况。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Silver data quality report.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--master", default=None)
    parser.add_argument("--epidemic", default=None)
    parser.add_argument("--population", default=None)
    parser.add_argument("--weather", default=None)
    parser.add_argument("--output", default="data/serving/silver_data_quality_report.json")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    paths = resolve_hdfs_paths(settings)
    epidemic_path = args.epidemic or paths["epidemic_silver"]
    population_path = args.population or paths["population_silver"]
    weather_path = args.weather or paths["weather_silver"]

    spark = create_spark("silver_data_quality_report", config_path=project_path(args.config), master=args.master, check_hdfs=True)
    epidemic_df = spark.read.parquet(epidemic_path)
    population_df = spark.read.parquet(population_path)
    weather_df = spark.read.parquet(weather_path)

    spark_version = spark.version
    spark_master = spark.sparkContext.master
    fs_default_fs = spark.sparkContext._jsc.hadoopConfiguration().get("fs.defaultFS")

    epidemic = epidemic_report(epidemic_df)
    population = population_report(population_df)
    weather = weather_report(weather_df)
    can_enter_gold_stage = (
        epidemic["output_rows"] > 0
        and population["output_rows"] > 0
        and weather["output_rows"] > 0
        and weather["duplicate_key_count"] == 0
        and population["duplicate_count"] == 0
    )
    report = {
        "epidemic": epidemic,
        "population": population,
        "weather": weather,
        "general": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spark_version": spark_version,
            "spark_master": spark_master,
            "fs_default_fs": fs_default_fs,
            "demo_mode": bool(get_setting(settings, "project.demo_mode", False)),
            "can_enter_gold_stage": can_enter_gold_stage,
        },
    }

    output = project_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    hdfs_report_path = str(get_setting(settings, "hdfs.serving_path", "/disease_platform/serving")).rstrip(
        "/"
    ) + "/silver_data_quality_report.json"
    upload_status = {"hdfs_path": hdfs_uri(hdfs_report_path), "uploaded": False, "error": None}
    try:
        HdfsCli().upload_file(output, hdfs_report_path, overwrite=True)
        upload_status["uploaded"] = True
    except (HdfsCliError, OSError) as exc:
        upload_status["error"] = str(exc)
    report["general"]["hdfs_upload"] = upload_status
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
