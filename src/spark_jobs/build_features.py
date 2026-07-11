from __future__ import annotations

import argparse

from pyspark.sql import functions as F
from pyspark.sql.window import Window

from src.spark_jobs.schemas import FEATURE_COLUMNS
from src.spark_jobs.spark_session import create_spark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epidemic", required=True)
    parser.add_argument("--weather", required=True)
    parser.add_argument("--population", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--horizon", type=int, default=7)
    args = parser.parse_args()

    spark = create_spark("build_features")
    epidemic = spark.read.parquet(args.epidemic)
    weather = spark.read.parquet(args.weather)
    population = spark.read.parquet(args.population)

    # 年度人口指标只允许使用当前年份及历史年份，禁止用未来年份填补过去。
    daily = epidemic.join(weather.drop("year"), ["location_code", "date"], "left").withColumn("year_key", F.year("date"))
    joined = (
        daily.join(
            population.select(
                F.col("location_code").alias("pop_location_code"),
                F.col("year").alias("pop_year"),
                "population",
                "urban_population_ratio",
                "gdp_per_capita",
            ),
            (daily.location_code == F.col("pop_location_code")) & (F.col("pop_year") <= daily.year_key),
            "left",
        )
    )
    pop_window = Window.partitionBy("location_code", "disease", "date").orderBy(F.col("pop_year").desc_nulls_last())
    joined = joined.withColumn("_pop_rn", F.row_number().over(pop_window)).filter(F.col("_pop_rn") == 1).drop("_pop_rn", "pop_location_code", "pop_year")

    ordered = Window.partitionBy("location_code", "disease").orderBy("date")
    roll3 = ordered.rowsBetween(-2, 0)
    roll7 = ordered.rowsBetween(-6, 0)
    roll14 = ordered.rowsBetween(-13, 0)

    features = (
        joined.withColumn("lag_1", F.lag("new_cases_smoothed", 1).over(ordered))
        .withColumn("lag_3", F.lag("new_cases_smoothed", 3).over(ordered))
        .withColumn("lag_7", F.lag("new_cases_smoothed", 7).over(ordered))
        .withColumn("lag_14", F.lag("new_cases_smoothed", 14).over(ordered))
        .withColumn("rolling_mean_3", F.avg("new_cases_clean").over(roll3))
        .withColumn("rolling_mean_7", F.avg("new_cases_clean").over(roll7))
        .withColumn("rolling_mean_14", F.avg("new_cases_clean").over(roll14))
        .withColumn("rolling_std_7", F.stddev_pop("new_cases_clean").over(roll7))
        .withColumn("rolling_std_14", F.stddev_pop("new_cases_clean").over(roll14))
        .withColumn("growth_rate_1", (F.col("new_cases_smoothed") - F.col("lag_1")) / F.greatest(F.abs(F.col("lag_1")), F.lit(1.0)))
        .withColumn("growth_rate_7", (F.col("rolling_mean_7") - F.col("lag_7")) / F.greatest(F.abs(F.col("lag_7")), F.lit(1.0)))
        .withColumn("cases_per_million", F.col("new_cases_clean") / F.col("population") * F.lit(1_000_000.0))
        .withColumn("deaths_per_million", F.col("new_deaths") / F.col("population") * F.lit(1_000_000.0))
        .withColumn("month", F.month("date"))
        .withColumn("day_of_week", F.dayofweek("date"))
        .withColumn("is_weekend", F.col("day_of_week").isin([1, 7]).cast("int"))
        .withColumn("target_t_plus_7", F.lead("new_cases_smoothed", args.horizon).over(ordered))
        .withColumn("target_log", F.log1p("target_t_plus_7"))
        .withColumn("year", F.year("date"))
    )

    leaked = [column for column in FEATURE_COLUMNS if column.startswith("target") or "plus_7" in column]
    if leaked:
        raise ValueError(f"特征列存在泄漏风险: {leaked}")
    required = ["lag_1", "lag_7", "rolling_mean_7", "target_t_plus_7", "population"]
    valid = features.dropna(subset=required)
    valid.write.mode("overwrite").partitionBy("year", "location_code").parquet(args.output)

    print(f"feature_rows={valid.count()}")
    valid.select(
        "location_code", "date", "new_cases_clean", "lag_7", "rolling_mean_7", "target_t_plus_7"
    ).show(20, truncate=False)
    spark.stop()


if __name__ == "__main__":
    main()
