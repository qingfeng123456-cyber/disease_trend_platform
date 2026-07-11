from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.config import get_setting, load_settings


def hdfs_uri(path: str) -> str:
    if path.startswith("hdfs://"):
        return path
    return "hdfs:///" + path.lstrip("/")


def create_spark(
    app_name: str | None = None,
    *,
    config_path: str | Path | None = None,
    master: str | None = None,
    check_hdfs: bool = False,
):
    """Create a SparkSession for batch jobs only.

    Flask/API code must not create Spark sessions. These sessions are intended
    for `spark-submit` jobs in the Silver/Gold pipeline.
    """

    from pyspark.sql import SparkSession

    settings = load_settings(config_path)
    resolved_app_name = app_name or str(get_setting(settings, "spark.app_name", "disease-trend-platform"))
    resolved_master = master or str(get_setting(settings, "spark.master", "local[*]"))
    shuffle_partitions = str(get_setting(settings, "spark.shuffle_partitions", 8))

    builder = (
        SparkSession.builder.appName(resolved_app_name)
        .master(resolved_master)
        .config("spark.sql.shuffle.partitions", shuffle_partitions)
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
    )

    driver_memory = get_setting(settings, "spark.driver_memory")
    if driver_memory:
        builder = builder.config("spark.driver.memory", str(driver_memory))
    executor_memory = get_setting(settings, "spark.executor_memory")
    if executor_memory:
        builder = builder.config("spark.executor.memory", str(executor_memory))

    spark = builder.getOrCreate()
    log_level = str(get_setting(settings, "spark.log_level", "WARN"))
    spark.sparkContext.setLogLevel(log_level)

    hadoop_conf = spark.sparkContext._jsc.hadoopConfiguration()
    fs_default = hadoop_conf.get("fs.defaultFS")
    print(f"Spark version: {spark.version}")
    print(f"Spark master: {spark.sparkContext.master}")
    print(f"fs.defaultFS: {fs_default}")

    if check_hdfs:
        try:
            jvm = spark.sparkContext._jvm
            fs = jvm.org.apache.hadoop.fs.FileSystem.get(hadoop_conf)
            exists = fs.exists(jvm.org.apache.hadoop.fs.Path("/"))
            print(f"HDFS root readable: {exists}")
        except Exception as exc:  # pragma: no cover - exercised on Ubuntu with Hadoop
            raise RuntimeError(f"Spark 无法访问 HDFS: {exc}") from exc

    return spark


def resolve_hdfs_paths(settings: dict[str, Any]) -> dict[str, str]:
    raw_path = str(get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"))
    silver_path = str(get_setting(settings, "hdfs.silver_path", "/disease_platform/silver"))
    serving_path = str(get_setting(settings, "hdfs.serving_path", "/disease_platform/serving"))
    return {
        "epidemic_raw": hdfs_uri(f"{raw_path}/kaggle/epidemic/covid_19_data.csv"),
        "population_raw": hdfs_uri(f"{raw_path}/kaggle/population/world_population.csv"),
        "weather_raw": hdfs_uri(f"{raw_path}/open_meteo"),
        "epidemic_silver": hdfs_uri(f"{silver_path}/epidemic"),
        "population_silver": hdfs_uri(f"{silver_path}/population"),
        "weather_silver": hdfs_uri(f"{silver_path}/weather"),
        "serving": hdfs_uri(serving_path),
    }
