from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyspark.sql import functions as F

from src.spark_jobs.spark_session import create_spark


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--serving-dir", default="data/serving")
    parser.add_argument("--default-location", default="CHN")
    args = parser.parse_args()

    spark = create_spark("export_dashboard")
    features = spark.read.parquet(args.features)
    predictions = spark.read.parquet(args.predictions)
    out_dir = Path(args.serving_dir)

    latest_date = features.agg(F.max("date")).first()[0]
    latest = features.filter(F.col("date") == F.lit(latest_date))
    regions = latest.select("location_code").distinct().count()
    valid_records = features.count()

    overview = {
        "data_mode": "real_or_spark",
        "demo_mode": False,
        "last_update": spark.sql("select current_timestamp() as ts").first()["ts"].isoformat(),
        "latest_date": str(latest_date),
        "start_date": str(features.agg(F.min("date")).first()[0]),
        "end_date": str(latest_date),
        "regions": regions,
        "diseases": latest.select("disease").distinct().count(),
        "valid_records": valid_records,
        "current_total_cases": float(latest.agg(F.sum("total_cases")).first()[0] or 0),
        "current_total_deaths": float(latest.agg(F.sum("total_deaths")).first()[0] or 0),
        "current_new_cases": float(latest.agg(F.sum("new_cases_clean")).first()[0] or 0),
        "high_risk_regions": 0,
        "best_model": "Spark GBTRegressor",
        "best_model_mae": None,
        "data_completeness": 1.0,
        "disclaimer": "教学演示，不构成公共卫生决策或医疗建议。",
    }
    write_json(out_dir / "overview.json", overview)

    risk_base = (
        latest.withColumn(
            "forecast_per_million",
            F.col("rolling_mean_7") / F.col("population") * F.lit(1_000_000.0),
        )
        .select("location_code", "location", "latitude", "longitude", "disease", "forecast_per_million", "growth_rate_7", "quality_flag", "rolling_mean_7")
        .dropna(subset=["forecast_per_million"])
    )
    max_forecast = risk_base.agg(F.max("forecast_per_million")).first()[0] or 1.0
    risk = (
        risk_base.withColumn(
            "risk_score",
            F.round(
                F.lit(100.0)
                * (F.lit(0.60) * F.col("forecast_per_million") / F.lit(max_forecast)
                   + F.lit(0.40) * F.abs(F.coalesce("growth_rate_7", F.lit(0.0)))),
                2,
            ),
        )
        .withColumn(
            "risk_level",
            F.when(F.col("risk_score") < 35, "低风险")
            .when(F.col("risk_score") < 55, "中风险")
            .when(F.col("risk_score") < 75, "较高风险")
            .otherwise("高风险"),
        )
        .withColumnRenamed("rolling_mean_7", "forecast_cases")
        .orderBy(F.desc("risk_score"))
        .limit(200)
    )
    risk_rows = [row.asDict(recursive=True) for row in risk.collect()]
    write_json(out_dir / "risk_map.json", {"data_mode": "real_or_spark", "date": str(latest_date), "items": risk_rows})
    write_json(
        out_dir / "rankings.json",
        {
            "data_mode": "real_or_spark",
            "risk": risk_rows,
            "growth": sorted(risk_rows, key=lambda x: x.get("growth_rate_7") or 0, reverse=True),
            "forecast": sorted(risk_rows, key=lambda x: x.get("forecast_cases") or 0, reverse=True),
        },
    )

    trend_items = []
    for row in features.select("location_code", "location", "disease").distinct().limit(200).collect():
        code = row["location_code"]
        disease = row["disease"]
        hist = (
            features.filter((F.col("location_code") == code) & (F.col("disease") == disease))
            .select("date", "new_cases_clean", "rolling_mean_7", "growth_rate_7", "temperature_mean", "relative_humidity_mean", "precipitation_sum")
            .orderBy("date")
        )
        pred = (
            predictions.filter((F.col("location_code") == code) & (F.col("disease") == disease))
            .select("date", "prediction_cases", "actual_t_plus_7")
            .orderBy("date")
        )
        pred_map = {str(r["date"]): r.asDict() for r in pred.collect()}
        points = []
        for item in hist.collect():
            key = str(item["date"])
            p = pred_map.get(key, {})
            prediction = p.get("prediction_cases")
            points.append(
                {
                    "date": key,
                    "actual": item["new_cases_clean"],
                    "rolling_7": item["rolling_mean_7"],
                    "prediction": prediction,
                    "target_t_plus_7": p.get("actual_t_plus_7"),
                    "lower": max(0, prediction * 0.85) if prediction is not None else None,
                    "upper": prediction * 1.15 if prediction is not None else None,
                    "growth_rate_7": item["growth_rate_7"],
                    "temperature_mean": item["temperature_mean"],
                    "relative_humidity_mean": item["relative_humidity_mean"],
                    "precipitation_sum": item["precipitation_sum"],
                    "prediction_error": prediction - p.get("actual_t_plus_7") if prediction is not None and p.get("actual_t_plus_7") is not None else None,
                }
            )
        trend_items.append({"location_code": code, "location": row["location"], "disease": disease, "points": points[-730:]})
    write_json(out_dir / "trend.json", {"data_mode": "real_or_spark", "items": trend_items})

    options = {
        "data_mode": "real_or_spark",
        "locations": [row.asDict() for row in features.select(F.col("location_code").alias("code"), F.col("location").alias("name"), "latitude", "longitude").dropDuplicates(["code"]).collect()],
        "diseases": [r[0] for r in features.select("disease").distinct().collect()],
        "models": ["naive_last_value", "naive_rolling_7", "Spark GBTRegressor"],
        "date_range": {"start": overview["start_date"], "end": overview["end_date"]},
    }
    write_json(out_dir / "options.json", options)
    write_json(out_dir / "metadata.json", {"data_mode": "real_or_spark", "generated_at": overview["last_update"]})
    weather_sample = (
        features.select("date", "location_code", "location", "disease", "temperature_mean", "relative_humidity_mean", "precipitation_sum", "new_cases_smoothed")
        .orderBy("date")
        .limit(1200)
    )
    write_json(out_dir / "weather_correlation.json", {"data_mode": "real_or_spark", "items": [r.asDict(recursive=True) for r in weather_sample.collect()]})
    write_json(out_dir / "source_status.json", {"data_mode": "real_or_spark", "items": [{"name": "Spark features", "status": "ok", "updated_at": overview["last_update"], "rows": valid_records}]})
    write_json(out_dir / "disease_share.json", {"data_mode": "real_or_spark", "items": [r.asDict() for r in latest.groupBy("disease").agg(F.sum("total_cases").alias("total_cases")).collect()]})
    write_json(out_dir / "predictions.json", {"data_mode": "real_or_spark", "items": [r.asDict(recursive=True) for r in predictions.orderBy(F.desc("date")).limit(1200).collect()]})
    spark.stop()


if __name__ == "__main__":
    main()
