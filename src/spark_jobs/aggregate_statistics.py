from __future__ import annotations

import argparse

from pyspark.sql import functions as F

from src.spark_jobs.spark_session import create_spark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spark = create_spark("aggregate_statistics")
    features = spark.read.parquet(args.features)
    stats = (
        features.groupBy("location_code", "location", "disease", "year")
        .agg(
            F.sum("new_cases_clean").alias("year_cases"),
            F.sum("new_deaths").alias("year_deaths"),
            F.avg("cases_per_million").alias("avg_cases_per_million"),
            F.avg("growth_rate_7").alias("avg_growth_rate_7"),
            F.avg("temperature_mean").alias("avg_temperature_mean"),
            F.max("date").alias("latest_date"),
        )
        .orderBy("location_code", "disease", "year")
    )
    stats.write.mode("overwrite").partitionBy("year").parquet(args.output)
    print(f"regional_statistics_rows={stats.count()}")
    spark.stop()


if __name__ == "__main__":
    main()
