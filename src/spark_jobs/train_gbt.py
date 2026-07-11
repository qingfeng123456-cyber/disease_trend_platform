from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from pyspark.ml import Pipeline
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.feature import Imputer, OneHotEncoder, StringIndexer, VectorAssembler
from pyspark.ml.regression import GBTRegressor
from pyspark.sql import functions as F

from src.spark_jobs.schemas import FEATURE_COLUMNS
from src.spark_jobs.spark_session import create_spark

NUMERIC_FEATURES = FEATURE_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--prediction-output", required=True)
    parser.add_argument("--metrics-local", default="data/serving/model_metrics.json")
    parser.add_argument("--max-iter", type=int, default=60)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    spark = create_spark("train_gbt")
    data = spark.read.parquet(args.input).filter(F.col("target_log").isNotNull())

    bounds = data.agg(F.min("date").alias("min_date"), F.max("date").alias("max_date")).first()
    min_date, max_date = bounds["min_date"], bounds["max_date"]
    if min_date is None or max_date is None:
        raise ValueError("特征表没有有效日期")
    total_days = max((max_date - min_date).days, 1)
    train_cut = min_date + timedelta(days=int(total_days * 0.70))
    valid_cut = min_date + timedelta(days=int(total_days * 0.85))

    train = data.filter(F.col("date") <= F.lit(train_cut))
    valid = data.filter((F.col("date") > F.lit(train_cut)) & (F.col("date") <= F.lit(valid_cut)))
    test = data.filter(F.col("date") > F.lit(valid_cut))

    imputed_cols = [f"{c}_imp" for c in NUMERIC_FEATURES]
    location_indexer = StringIndexer(inputCol="location_code", outputCol="location_idx", handleInvalid="keep")
    location_encoder = OneHotEncoder(inputCols=["location_idx"], outputCols=["location_vec"], handleInvalid="keep")
    imputer = Imputer(inputCols=NUMERIC_FEATURES, outputCols=imputed_cols, strategy="median")
    assembler = VectorAssembler(inputCols=imputed_cols + ["location_vec"], outputCol="features")
    gbt = GBTRegressor(
        featuresCol="features",
        labelCol="target_log",
        predictionCol="prediction_log",
        maxIter=args.max_iter,
        maxDepth=args.max_depth,
        seed=args.seed,
    )
    pipeline = Pipeline(stages=[location_indexer, location_encoder, imputer, assembler, gbt])
    model = pipeline.fit(train)

    pred = (
        model.transform(test)
        .withColumn("prediction_cases", F.greatest(F.exp("prediction_log") - F.lit(1.0), F.lit(0.0)))
    )

    mae = RegressionEvaluator(
        labelCol="target_t_plus_7", predictionCol="prediction_cases", metricName="mae"
    ).evaluate(pred)
    rmse = RegressionEvaluator(
        labelCol="target_t_plus_7", predictionCol="prediction_cases", metricName="rmse"
    ).evaluate(pred)
    r2 = RegressionEvaluator(
        labelCol="target_t_plus_7", predictionCol="prediction_cases", metricName="r2"
    ).evaluate(pred)

    baseline = pred.withColumn("baseline_prediction", F.col("rolling_mean_7"))
    baseline_mae = RegressionEvaluator(
        labelCol="target_t_plus_7", predictionCol="baseline_prediction", metricName="mae"
    ).evaluate(baseline)
    extra = pred.select(
        F.avg(F.when(F.col("target_t_plus_7") != 0, F.abs((F.col("target_t_plus_7") - F.col("prediction_cases")) / F.col("target_t_plus_7")))).alias("mape"),
        F.avg(
            F.when(
                F.abs(F.col("target_t_plus_7")) + F.abs(F.col("prediction_cases")) > 0,
                F.lit(2.0) * F.abs(F.col("prediction_cases") - F.col("target_t_plus_7"))
                / (F.abs(F.col("target_t_plus_7")) + F.abs(F.col("prediction_cases"))),
            ).otherwise(F.lit(0.0))
        ).alias("smape"),
    ).first()

    model.write().overwrite().save(args.model_output)
    pred.select(
        "location_code",
        "location",
        "date",
        "disease",
        F.col("target_t_plus_7").alias("actual_t_plus_7"),
        "prediction_cases",
        "rolling_mean_7",
        "quality_flag",
    ).write.mode("overwrite").parquet(args.prediction_output)

    metrics = {
        "model": "Spark GBTRegressor",
        "train_end": str(train_cut),
        "validation_end": str(valid_cut),
        "test_end": str(max_date),
        "train_rows": train.count(),
        "validation_rows": valid.count(),
        "test_rows": test.count(),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "mape": float(extra["mape"] or 0.0),
        "smape": float(extra["smape"] or 0.0),
        "baseline_mae": baseline_mae,
        "beats_baseline": mae < baseline_mae,
        "feature_list": NUMERIC_FEATURES,
        "note": "教学模型；时间切分；不构成公共卫生决策依据。",
    }
    metrics_path = Path(args.metrics_local)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison = {
        "items": [
            {"model": "naive_rolling_7", "mae": baseline_mae, "rmse": None, "r2": None, "mape": None, "smape": None},
            {"model": "Spark GBTRegressor", "mae": mae, "rmse": rmse, "r2": r2, "mape": metrics["mape"], "smape": metrics["smape"]},
        ],
        "best_model": "Spark GBTRegressor" if mae < baseline_mae else "naive_rolling_7",
    }
    metrics_path.with_name("model_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
