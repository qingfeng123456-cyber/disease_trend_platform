from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyspark.sql import functions as F
from pyspark.sql.window import Window

from src.common.config import load_settings
from src.common.paths import project_path
from src.spark_jobs.schemas import country_mapping_schema, epidemic_raw_schema
from src.spark_jobs.spark_session import create_spark, resolve_hdfs_paths


def write_json(path: str | Path, payload: dict) -> None:
    output = project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean Kaggle COVID-19 raw data into Silver epidemic parquet.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--master", default=None)
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--quality-output", default="data/serving/epidemic_silver_quality.json")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    paths = resolve_hdfs_paths(settings)
    input_path = args.input or paths["epidemic_raw"]
    output_path = args.output or paths["epidemic_silver"]

    spark = create_spark("clean_epidemic", config_path=project_path(args.config), master=args.master, check_hdfs=True)
    raw = (
        spark.read.option("header", True)
        .schema(epidemic_raw_schema())
        .csv(input_path)
        .withColumnRenamed("Province/State", "province_raw")
        .withColumnRenamed("Country/Region", "country_region")
        .withColumnRenamed("Last Update", "last_update_raw")
    )
    input_rows = raw.count()

    parsed = (
        raw.withColumn("date", F.to_date(F.col("ObservationDate"), "MM/dd/yyyy"))
        .withColumn(
            "province",
            F.when(F.trim(F.col("province_raw")) == F.lit(""), F.lit(None)).otherwise(F.trim(F.col("province_raw"))),
        )
        .withColumn("country_region", F.trim(F.col("country_region")))
        .withColumn("last_update_ts", F.to_timestamp(F.col("last_update_raw")))
        .withColumn("total_cases_raw", F.col("Confirmed").cast("double"))
        .withColumn("total_deaths_raw", F.col("Deaths").cast("double"))
        .withColumn("total_recovered_raw", F.col("Recovered").cast("double"))
    )

    duplicate_key_count = (
        parsed.filter(F.col("date").isNotNull())
        .groupBy("country_region", "province", "date")
        .count()
        .filter(F.col("count") > 1)
        .count()
    )

    dedup_window = Window.partitionBy("country_region", "province", "date").orderBy(
        F.col("last_update_ts").desc_nulls_last(), F.col("SNo").desc_nulls_last()
    )
    dedup = (
        parsed.withColumn("_rn", F.row_number().over(dedup_window))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )

    mapping_path = project_path("config", "country_name_mapping.csv")
    mapping = (
        spark.read.option("header", True)
        .schema(country_mapping_schema())
        .csv(str(mapping_path))
        .withColumn("mapping_enabled", F.lower(F.col("enabled")) == F.lit("true"))
        .select(
            "epidemic_name",
            "population_name",
            "standard_name",
            F.when(F.col("mapping_enabled"), F.upper(F.col("location_code"))).otherwise(F.lit(None)).alias("mapped_code"),
            "mapping_enabled",
        )
    )

    normalized = (
        dedup.join(mapping, dedup.country_region == mapping.epidemic_name, "left")
        .withColumn("location", F.coalesce(F.col("standard_name"), F.col("country_region")))
        .withColumn("location_code", F.col("mapped_code"))
        .withColumn("is_national_row", F.col("province").isNull())
        .withColumn(
            "is_country_like_province",
            F.coalesce(
                F.lower(F.col("province")).isin("uk", "united kingdom")
                | (F.lower(F.col("province")) == F.lower(F.col("country_region"))),
                F.lit(False),
            ),
        )
        .filter(F.col("date").isNotNull())
    )

    raw_country_day = normalized.groupBy("country_region", "location", "location_code", "date").agg(
        F.sum(F.when(F.col("is_national_row"), F.col("total_cases_raw")).otherwise(F.lit(0.0))).alias("national_cases"),
        F.sum(F.when(~F.col("is_national_row"), F.col("total_cases_raw")).otherwise(F.lit(0.0))).alias("province_cases"),
        F.sum(F.when(F.col("is_national_row"), F.col("total_deaths_raw")).otherwise(F.lit(0.0))).alias("national_deaths"),
        F.sum(F.when(~F.col("is_national_row"), F.col("total_deaths_raw")).otherwise(F.lit(0.0))).alias("province_deaths"),
        F.sum(F.when(F.col("is_national_row"), F.col("total_recovered_raw")).otherwise(F.lit(0.0))).alias("national_recovered"),
        F.sum(F.when(~F.col("is_national_row"), F.col("total_recovered_raw")).otherwise(F.lit(0.0))).alias("province_recovered"),
        F.max(F.col("is_national_row").cast("int")).alias("has_national_row_int"),
        F.max((~F.col("is_national_row")).cast("int")).alias("has_province_rows_int"),
        F.sum(F.col("is_country_like_province").cast("int")).alias("country_like_province_count"),
    )

    with_rule = (
        raw_country_day.withColumn("has_national_row", F.col("has_national_row_int") == 1)
        .withColumn("has_province_rows", F.col("has_province_rows_int") == 1)
        .withColumn("aggregation_conflict", F.col("has_national_row") & F.col("has_province_rows"))
        .withColumn(
            "use_province_only",
            F.col("aggregation_conflict") & (F.col("country_like_province_count") > 0),
        )
        .withColumn(
            "total_cases",
            F.when(F.col("use_province_only"), F.col("province_cases"))
            .when(F.col("has_national_row") & ~F.col("has_province_rows"), F.col("national_cases"))
            .when(~F.col("has_national_row") & F.col("has_province_rows"), F.col("province_cases"))
            .otherwise(F.col("national_cases") + F.col("province_cases")),
        )
        .withColumn(
            "total_deaths",
            F.when(F.col("use_province_only"), F.col("province_deaths"))
            .when(F.col("has_national_row") & ~F.col("has_province_rows"), F.col("national_deaths"))
            .when(~F.col("has_national_row") & F.col("has_province_rows"), F.col("province_deaths"))
            .otherwise(F.col("national_deaths") + F.col("province_deaths")),
        )
        .withColumn(
            "total_recovered",
            F.when(F.col("use_province_only"), F.col("province_recovered"))
            .when(F.col("has_national_row") & ~F.col("has_province_rows"), F.col("national_recovered"))
            .when(~F.col("has_national_row") & F.col("has_province_rows"), F.col("province_recovered"))
            .otherwise(F.col("national_recovered") + F.col("province_recovered")),
        )
    )

    # Multiple raw labels can map to one ISO3 code, so aggregate once more after mapping.
    location_key = F.coalesce(F.col("location_code"), F.concat(F.lit("UNMAPPED:"), F.col("location")))
    country_day = (
        with_rule.withColumn("location_key", location_key)
        .groupBy("location_key", "location_code", "location", "date")
        .agg(
            F.sum("total_cases").alias("total_cases"),
            F.sum("total_deaths").alias("total_deaths"),
            F.sum("total_recovered").alias("total_recovered"),
            F.max(F.col("has_province_rows").cast("int")).alias("has_province_rows_int"),
            F.max(F.col("has_national_row").cast("int")).alias("has_national_row_int"),
            F.max(F.col("aggregation_conflict").cast("int")).alias("aggregation_conflict_int"),
        )
        .withColumn("has_province_rows", F.col("has_province_rows_int") == 1)
        .withColumn("has_national_row", F.col("has_national_row_int") == 1)
        .withColumn("aggregation_conflict", F.col("aggregation_conflict_int") == 1)
        .drop("has_province_rows_int", "has_national_row_int", "aggregation_conflict_int")
    )

    diff_window = Window.partitionBy("location_key").orderBy("date")
    result = (
        country_day.withColumn("prev_total_cases", F.lag("total_cases").over(diff_window))
        .withColumn("prev_total_deaths", F.lag("total_deaths").over(diff_window))
        .withColumn(
            "new_cases_raw",
            F.when(F.col("prev_total_cases").isNull(), F.col("total_cases")).otherwise(
                F.col("total_cases") - F.col("prev_total_cases")
            ),
        )
        .withColumn(
            "new_deaths_raw",
            F.when(F.col("prev_total_deaths").isNull(), F.col("total_deaths")).otherwise(
                F.col("total_deaths") - F.col("prev_total_deaths")
            ),
        )
        .withColumn("new_cases_clean", F.greatest(F.col("new_cases_raw"), F.lit(0.0)))
        .withColumn("new_deaths_clean", F.greatest(F.col("new_deaths_raw"), F.lit(0.0)))
        .withColumn("is_negative_case_correction", F.col("new_cases_raw") < 0)
        .withColumn("is_negative_death_correction", F.col("new_deaths_raw") < 0)
        .withColumn("source", F.lit("Kaggle COVID-19 daily report"))
        .withColumn("collected_at", F.current_timestamp())
        .withColumn("year", F.year("date"))
        .select(
            "date",
            "location",
            "location_code",
            "total_cases",
            "total_deaths",
            "total_recovered",
            "new_cases_raw",
            "new_cases_clean",
            "new_deaths_raw",
            "new_deaths_clean",
            "is_negative_case_correction",
            "is_negative_death_correction",
            "has_province_rows",
            "has_national_row",
            "aggregation_conflict",
            "source",
            "collected_at",
            "year",
        )
    )

    result.write.mode("overwrite").partitionBy("year", "location_code").parquet(output_path)

    unmapped = [
        row["country_region"]
        for row in normalized.filter(F.col("location_code").isNull()).select("country_region").distinct().orderBy("country_region").collect()
    ]
    quality = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": input_path,
        "output_path": output_path,
        "input_rows": input_rows,
        "output_rows": result.count(),
        "date_min": str(result.agg(F.min("date")).first()[0]),
        "date_max": str(result.agg(F.max("date")).first()[0]),
        "duplicate_country_province_date_key_count": duplicate_key_count,
        "national_province_conflict_count": with_rule.filter(F.col("aggregation_conflict")).count(),
        "negative_case_correction_count": result.filter(F.col("is_negative_case_correction")).count(),
        "negative_death_correction_count": result.filter(F.col("is_negative_death_correction")).count(),
        "unmapped_country_count": len(unmapped),
        "unmapped_countries": unmapped,
    }
    write_json(args.quality_output, quality)
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
