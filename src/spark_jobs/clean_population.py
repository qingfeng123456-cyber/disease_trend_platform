from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from functools import reduce
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyspark.sql import DataFrame, functions as F

from src.common.config import load_settings
from src.common.paths import project_path
from src.spark_jobs.schemas import population_raw_schema
from src.spark_jobs.spark_session import create_spark, resolve_hdfs_paths


POPULATION_YEARS = [2022, 2020, 2015, 2010, 2000, 1990, 1980, 1970]


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
    parser = argparse.ArgumentParser(description="Clean world population raw data into Silver parquet.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--master", default=None)
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--quality-output", default="data/serving/population_silver_quality.json")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    paths = resolve_hdfs_paths(settings)
    input_path = args.input or paths["population_raw"]
    output_path = args.output or paths["population_silver"]

    spark = create_spark("clean_population", config_path=project_path(args.config), master=args.master, check_hdfs=True)
    raw = spark.read.option("header", True).schema(population_raw_schema()).csv(input_path)
    input_rows = raw.count()

    base = raw.select(
        F.trim(F.col("Country/Territory")).alias("location"),
        F.upper(F.trim(F.col("CCA3"))).alias("location_code"),
        F.col("Continent").cast("string").alias("continent"),
        F.col("Area (km²)").cast("double").alias("area_km2"),
        F.col("Density (per km²)").cast("double").alias("population_density"),
        F.col("Growth Rate").cast("double").alias("growth_rate"),
        F.col("World Population Percentage").cast("double").alias("world_population_percentage"),
        *[F.col(f"{year} Population").cast("long").alias(f"population_{year}") for year in POPULATION_YEARS],
    )

    year_frames = [
        base.select(
            "location",
            "location_code",
            "continent",
            F.lit(year).cast("int").alias("year"),
            F.col(f"population_{year}").cast("long").alias("population"),
            "area_km2",
            "population_density",
            "growth_rate",
            "world_population_percentage",
            F.lit("Kaggle world_population.csv").alias("source"),
        )
        for year in POPULATION_YEARS
    ]
    long_df = reduce(lambda left, right: left.unionByName(right), year_frames).filter(
        F.col("location_code").rlike("^[A-Z]{3}$") & F.col("year").isNotNull()
    )

    duplicate_count = long_df.count() - long_df.dropDuplicates(["location_code", "year"]).count()
    cleaned = long_df.dropDuplicates(["location_code", "year"])

    cleaned.write.mode("overwrite").partitionBy("year").parquet(output_path)

    year_bounds = cleaned.agg(F.min("year").alias("min_year"), F.max("year").alias("max_year")).first()
    quality = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": input_path,
        "output_path": output_path,
        "input_rows": input_rows,
        "output_rows": cleaned.count(),
        "country_count": cleaned.select("location_code").distinct().count(),
        "year_min": year_bounds["min_year"],
        "year_max": year_bounds["max_year"],
        "duplicate_count": duplicate_count,
        "missing_rate_by_column": missing_rates(cleaned),
        "future_fill_policy": "No future-year fill is applied in Silver. 2022 values are retained only as their own year.",
    }
    write_json(args.quality_output, quality)
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
