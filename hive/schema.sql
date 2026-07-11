CREATE DATABASE IF NOT EXISTS disease_platform;
USE disease_platform;

CREATE EXTERNAL TABLE IF NOT EXISTS epidemic_silver (
  date DATE,
  location STRING,
  continent STRING,
  disease STRING,
  new_cases_raw DOUBLE,
  new_cases_clean DOUBLE,
  total_cases DOUBLE,
  new_deaths DOUBLE,
  total_deaths DOUBLE,
  new_cases_smoothed DOUBLE,
  population DOUBLE,
  is_negative_correction BOOLEAN,
  is_iqr_outlier BOOLEAN,
  is_rolling_outlier BOOLEAN,
  source STRING,
  quality_flag STRING,
  collected_at TIMESTAMP
)
PARTITIONED BY (year INT, location_code STRING)
STORED AS PARQUET
LOCATION '/disease_platform/silver/epidemic_daily';

CREATE EXTERNAL TABLE IF NOT EXISTS weather_silver (
  date DATE,
  location STRING,
  latitude DOUBLE,
  longitude DOUBLE,
  temperature_mean DOUBLE,
  temperature_max DOUBLE,
  temperature_min DOUBLE,
  precipitation_sum DOUBLE,
  relative_humidity_mean DOUBLE,
  wind_speed_max DOUBLE,
  surface_pressure_mean DOUBLE,
  source STRING
)
PARTITIONED BY (year INT, location_code STRING)
STORED AS PARQUET
LOCATION '/disease_platform/silver/weather_daily';

CREATE EXTERNAL TABLE IF NOT EXISTS population_silver (
  location_code STRING,
  location STRING,
  population DOUBLE,
  urban_population_ratio DOUBLE,
  gdp_per_capita DOUBLE,
  source STRING
)
PARTITIONED BY (year INT)
STORED AS PARQUET
LOCATION '/disease_platform/silver/population_yearly';

CREATE EXTERNAL TABLE IF NOT EXISTS disease_features_gold
STORED AS PARQUET
LOCATION '/disease_platform/gold/forecast_features';

CREATE EXTERNAL TABLE IF NOT EXISTS regional_statistics_gold
STORED AS PARQUET
LOCATION '/disease_platform/gold/regional_statistics';

-- 创建/修改分区后可执行：
-- MSCK REPAIR TABLE epidemic_silver;
-- MSCK REPAIR TABLE weather_silver;
-- MSCK REPAIR TABLE population_silver;
