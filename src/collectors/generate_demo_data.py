from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.common.config import get_setting, load_settings
from src.common.paths import ensure_dir, project_path, safe_relative


@dataclass(frozen=True)
class Location:
    code: str
    name: str
    latitude: float
    longitude: float
    timezone: str


DISEASES = ["COVID-19", "Influenza"]
MODEL_NAMES = ["naive_last_value", "naive_rolling_7", "demo_trend_model"]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_locations() -> list[Location]:
    path = project_path("config", "locations.csv")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        return [
            Location(
                code=row["iso_code"].strip().upper(),
                name=row["name"].strip(),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                timezone=row.get("timezone", "UTC").strip() or "UTC",
            )
            for row in rows
        ]


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def minmax_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if math.isclose(lo, hi):
        return [0.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def metric_summary(actual: list[float], predicted: list[float]) -> dict[str, float]:
    pairs = [(a, p) for a, p in zip(actual, predicted) if a is not None and p is not None]
    if not pairs:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0, "mape": 0.0, "smape": 0.0}
    y = [float(a) for a, _ in pairs]
    pred = [float(p) for _, p in pairs]
    n = len(pairs)
    mae = sum(abs(p - a) for a, p in zip(y, pred)) / n
    rmse = math.sqrt(sum((p - a) ** 2 for a, p in zip(y, pred)) / n)
    mean_y = sum(y) / n
    ss_res = sum((a - p) ** 2 for a, p in zip(y, pred))
    ss_tot = sum((a - mean_y) ** 2 for a in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    nonzero = [(a, p) for a, p in zip(y, pred) if a != 0]
    mape = sum(abs((a - p) / a) for a, p in nonzero) / len(nonzero) if nonzero else 0.0
    smape = sum((2 * abs(p - a) / (abs(a) + abs(p))) if (abs(a) + abs(p)) else 0.0 for a, p in zip(y, pred)) / n
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "mape": round(mape, 4),
        "smape": round(smape, 4),
    }


def split_by_time(points: list[dict[str, Any]], train_ratio: float, validation_ratio: float) -> dict[str, str]:
    dates = sorted({point["date"] for point in points})
    if not dates:
        return {}
    train_idx = max(0, min(len(dates) - 1, int(len(dates) * train_ratio) - 1))
    valid_idx = max(train_idx + 1, min(len(dates) - 1, int(len(dates) * (train_ratio + validation_ratio)) - 1))
    return {
        "train_start": dates[0],
        "train_end": dates[train_idx],
        "validation_start": dates[min(train_idx + 1, len(dates) - 1)],
        "validation_end": dates[valid_idx],
        "test_start": dates[min(valid_idx + 1, len(dates) - 1)],
        "test_end": dates[-1],
    }


def risk_level(score: float) -> str:
    if score < 35:
        return "低风险"
    if score < 55:
        return "中风险"
    if score < 75:
        return "较高风险"
    return "高风险"


def build_demo() -> dict[str, Any]:
    settings = load_settings()
    seed = int(get_setting(settings, "model.random_seed", 2026))
    rng = random.Random(seed)
    start = date.fromisoformat(str(get_setting(settings, "collectors.start_date", "2020-01-01")))
    end = date.fromisoformat(str(get_setting(settings, "collectors.end_date", "2025-12-31")))
    horizon = int(get_setting(settings, "model.forecast_horizon", 7))
    locations = read_locations()
    collected_at = datetime.now(timezone.utc).isoformat()

    epidemic_rows: list[dict[str, Any]] = []
    weather_rows: list[dict[str, Any]] = []
    population_rows: list[dict[str, Any]] = []
    trends: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rolling_state: dict[tuple[str, str], deque[float]] = defaultdict(lambda: deque(maxlen=14))
    cumulative_cases: dict[tuple[str, str], float] = defaultdict(float)
    cumulative_deaths: dict[tuple[str, str], float] = defaultdict(float)

    for loc_index, loc in enumerate(locations):
        population = int(12_000_000 + loc_index * 9_000_000 + rng.randint(0, 4_000_000))
        urban = round(48 + loc_index * 3.1 + rng.random() * 8, 2)
        gdp = round(7_500 + loc_index * 3_250 + rng.random() * 1200, 2)
        for year in range(start.year, end.year + 1):
            population_rows.append(
                {
                    "location_code": loc.code,
                    "location": loc.name,
                    "year": year,
                    "population": int(population * (1 + 0.006 * (year - start.year))),
                    "urban_population_ratio": min(95.0, round(urban + 0.35 * (year - start.year), 2)),
                    "gdp_per_capita": round(gdp * (1 + 0.025 * (year - start.year)), 2),
                    "source": "demo_generator",
                    "collected_at": collected_at,
                }
            )

        for current in daterange(start, end):
            day_index = (current - start).days
            annual = math.sin(2 * math.pi * (day_index / 365.25) + loc_index / 2)
            weekly = math.sin(2 * math.pi * (day_index / 7))
            temp_mean = 16 + 13 * annual - abs(loc.latitude) * 0.08 + rng.gauss(0, 1.2)
            humidity = max(25, min(96, 62 - 10 * annual + rng.gauss(0, 5)))
            precipitation = max(0, rng.gauss(2.5 + 2.5 * max(annual, 0), 2.2))
            wind = max(0, rng.gauss(16, 4))
            pressure = 1010 - loc.latitude * 0.08 + rng.gauss(0, 3)
            weather_rows.append(
                {
                    "date": current.isoformat(),
                    "location": loc.name,
                    "location_code": loc.code,
                    "latitude": loc.latitude,
                    "longitude": loc.longitude,
                    "temperature_mean": round(temp_mean, 2),
                    "temperature_max": round(temp_mean + 5.5 + rng.random() * 2, 2),
                    "temperature_min": round(temp_mean - 5.5 - rng.random() * 2, 2),
                    "precipitation_sum": round(precipitation, 2),
                    "relative_humidity_mean": round(humidity, 2),
                    "wind_speed_max": round(wind, 2),
                    "surface_pressure_mean": round(pressure, 2),
                    "source": "demo_generator",
                    "collected_at": collected_at,
                }
            )

            for disease_index, disease in enumerate(DISEASES):
                key = (loc.code, disease)
                disease_base = 160 if disease == "COVID-19" else 80
                loc_factor = 0.75 + loc_index * 0.18
                disease_phase = disease_index * 1.4
                wave1 = 1.8 * math.exp(-((day_index - 180) / 55) ** 2)
                wave2 = 1.2 * math.exp(-((day_index - 620) / 90) ** 2)
                wave3 = 1.0 * math.exp(-((day_index - 980) / 80) ** 2)
                seasonal = 1.0 + (0.25 if disease == "Influenza" else 0.15) * math.sin(
                    2 * math.pi * day_index / 365.25 + disease_phase
                )
                weather_effect = 1 + (0.012 * max(0, 18 - temp_mean) if disease == "Influenza" else 0.004 * humidity)
                expected = disease_base * loc_factor * seasonal * weather_effect * (1 + wave1 + wave2 + wave3)
                noisy = max(0.0, expected + rng.gauss(0, max(8, expected * 0.12)) + weekly * 5)
                is_negative = day_index % (211 + loc_index * 3 + disease_index) == 0 and day_index > 30
                raw_cases = -round(noisy * 0.18, 2) if is_negative else round(noisy, 2)
                clean_cases = max(raw_cases, 0.0)
                rolling_state[key].append(clean_cases)
                rolling_7_values = list(rolling_state[key])[-7:]
                rolling_14_values = list(rolling_state[key])[-14:]
                rolling_7 = sum(rolling_7_values) / len(rolling_7_values)
                rolling_14 = sum(rolling_14_values) / len(rolling_14_values)
                lag_7 = trends[key][-7]["new_cases_clean"] if len(trends[key]) >= 7 else None
                growth = ((rolling_7 - lag_7) / max(abs(lag_7), 1.0)) if lag_7 is not None else 0.0
                prediction = max(0.0, rolling_7 * (1 + max(min(growth, 0.8), -0.5) * 0.35))
                deaths = clean_cases * (0.006 if disease == "COVID-19" else 0.0015)
                cumulative_cases[key] += clean_cases
                cumulative_deaths[key] += deaths
                anomaly_score = 1 if abs(growth) > 0.6 or is_negative else 0
                record = {
                    "date": current.isoformat(),
                    "location": loc.name,
                    "location_code": loc.code,
                    "continent": "Demo",
                    "disease": disease,
                    "new_cases_raw": raw_cases,
                    "new_cases_clean": round(clean_cases, 2),
                    "new_cases_smoothed": round(rolling_7, 2),
                    "total_cases": round(cumulative_cases[key], 2),
                    "new_deaths": round(deaths, 2),
                    "total_deaths": round(cumulative_deaths[key], 2),
                    "population": population,
                    "is_negative_correction": is_negative,
                    "is_iqr_outlier": False,
                    "is_rolling_outlier": anomaly_score == 1,
                    "temperature_mean": round(temp_mean, 2),
                    "relative_humidity_mean": round(humidity, 2),
                    "precipitation_sum": round(precipitation, 2),
                    "growth_rate_7": round(growth, 5),
                    "cases_per_million": round(clean_cases / population * 1_000_000, 5),
                    "prediction_t_plus_7": round(prediction, 2),
                    "source": "demo_generator",
                    "collected_at": collected_at,
                    "data_mode": "demo",
                }
                epidemic_rows.append(record)
                trends[key].append(record)

    # 补充 t+7 标签和误差，标签必须来自未来第 7 天，不能进入输入特征。
    prediction_points: list[dict[str, Any]] = []
    for (code, disease), points in trends.items():
        for i, point in enumerate(points):
            target = points[i + horizon]["new_cases_smoothed"] if i + horizon < len(points) else None
            point["target_t_plus_7"] = target
            point["prediction_error"] = (
                round(point["prediction_t_plus_7"] - target, 2) if target is not None else None
            )
            if target is not None:
                prediction_points.append(
                    {
                        "date": point["date"],
                        "location_code": code,
                        "location": point["location"],
                        "disease": disease,
                        "actual_t_plus_7": target,
                        "prediction": point["prediction_t_plus_7"],
                        "naive_last_value": point["new_cases_smoothed"],
                        "naive_rolling_7": point["new_cases_smoothed"],
                        "error": point["prediction_error"],
                    }
                )

    latest_date = end.isoformat()
    latest_covid = [points[-1] for (code, disease), points in trends.items() if disease == "COVID-19"]
    case_levels = [p["cases_per_million"] for p in latest_covid]
    growth_levels = [max(p["growth_rate_7"], 0) for p in latest_covid]
    forecast_levels = [p["prediction_t_plus_7"] / p["population"] * 1_000_000 for p in latest_covid]
    anomaly_levels = [1.0 if p["is_rolling_outlier"] else 0.0 for p in latest_covid]
    normalized = list(zip(
        minmax_normalize(case_levels),
        minmax_normalize(growth_levels),
        minmax_normalize(forecast_levels),
        minmax_normalize(anomaly_levels),
    ))
    risk_items = []
    for point, parts in zip(latest_covid, normalized):
        score = round((0.40 * parts[0] + 0.25 * parts[1] + 0.20 * parts[2] + 0.15 * parts[3]) * 100, 2)
        risk_items.append(
            {
                "date": latest_date,
                "location": point["location"],
                "location_code": point["location_code"],
                "latitude": next(loc.latitude for loc in locations if loc.code == point["location_code"]),
                "longitude": next(loc.longitude for loc in locations if loc.code == point["location_code"]),
                "disease": point["disease"],
                "risk_score": score,
                "risk_level": risk_level(score),
                "recent_cases_per_million": point["cases_per_million"],
                "growth_rate_7": point["growth_rate_7"],
                "forecast_cases": point["prediction_t_plus_7"],
                "quality_flag": "demo",
            }
        )
    risk_items.sort(key=lambda x: x["risk_score"], reverse=True)

    test_start = split_by_time(prediction_points, 0.70, 0.15).get("test_start", start.isoformat())
    test_points = [p for p in prediction_points if p["date"] >= test_start]
    actual = [float(p["actual_t_plus_7"]) for p in test_points]
    demo_pred = [float(p["prediction"]) for p in test_points]
    naive_pred = [float(p["naive_rolling_7"]) for p in test_points]
    model_metrics = {
        "model": "demo_trend_model",
        "forecast_horizon": horizon,
        "data_mode": "demo",
        **split_by_time(prediction_points, 0.70, 0.15),
        **metric_summary(actual, demo_pred),
        "baseline_mae": metric_summary(actual, naive_pred)["mae"],
        "beats_baseline": metric_summary(actual, demo_pred)["mae"] <= metric_summary(actual, naive_pred)["mae"],
        "feature_list": [
            "lag_1",
            "lag_3",
            "lag_7",
            "rolling_mean_7",
            "growth_rate_7",
            "temperature_mean",
            "relative_humidity_mean",
            "population",
        ],
        "note": "固定随机种子的演示模型，仅用于课程链路展示。",
    }

    model_comparison = {
        "items": [
            {"model": "naive_rolling_7", **metric_summary(actual, naive_pred)},
            {"model": "demo_trend_model", **metric_summary(actual, demo_pred)},
        ],
        "best_model": "demo_trend_model" if model_metrics["beats_baseline"] else "naive_rolling_7",
        "data_mode": "demo",
    }

    high_risk_count = sum(1 for item in risk_items if item["risk_level"] == "高风险")
    current_total_cases = sum(p["total_cases"] for p in latest_covid)
    current_total_deaths = sum(p["total_deaths"] for p in latest_covid)
    overview = {
        "data_mode": "demo",
        "demo_mode": True,
        "last_update": collected_at,
        "latest_date": latest_date,
        "start_date": start.isoformat(),
        "end_date": latest_date,
        "regions": len(locations),
        "diseases": len(DISEASES),
        "valid_records": len(epidemic_rows),
        "current_total_cases": round(current_total_cases, 2),
        "current_total_deaths": round(current_total_deaths, 2),
        "current_new_cases": round(sum(p["new_cases_clean"] for p in latest_covid), 2),
        "high_risk_regions": high_risk_count,
        "best_model": model_comparison["best_model"],
        "best_model_mae": model_metrics["mae"],
        "data_completeness": 0.985,
        "disclaimer": "演示数据由固定随机种子生成，不代表真实疫情；风险等级不是官方公共卫生风险等级。",
    }

    missing_rates = {
        "new_cases_clean": 0.0,
        "temperature_mean": 0.0,
        "relative_humidity_mean": 0.0,
        "population": 0.0,
        "target_t_plus_7": round(horizon / max(len(list(daterange(start, end))), 1), 4),
    }
    quality_report = {
        "data_mode": "demo",
        "total_records": len(epidemic_rows),
        "date_range": {"start": start.isoformat(), "end": latest_date},
        "region_count": len(locations),
        "disease_count": len(DISEASES),
        "missing_rate_by_column": missing_rates,
        "duplicate_count": 0,
        "negative_correction_count": sum(1 for row in epidemic_rows if row["is_negative_correction"]),
        "outlier_count": sum(1 for row in epidemic_rows if row["is_rolling_outlier"]),
        "weather_unmatched_count": 0,
        "population_unmatched_count": 0,
        "records_by_source": {"demo_generator": len(epidemic_rows)},
        "latest_data_date": latest_date,
        "run_time": collected_at,
        "is_demo_data": True,
        "warnings": ["当前为演示数据，不能用于真实医疗或公共卫生决策。"],
    }

    trends_payload = {
        "data_mode": "demo",
        "items": [
            {
                "location_code": code,
                "location": points[0]["location"],
                "disease": disease,
                "points": [
                    {
                        "date": p["date"],
                        "actual": p["new_cases_clean"],
                        "rolling_7": p["new_cases_smoothed"],
                        "prediction": p["prediction_t_plus_7"],
                        "target_t_plus_7": p["target_t_plus_7"],
                        "lower": round(max(0, p["prediction_t_plus_7"] * 0.82), 2),
                        "upper": round(p["prediction_t_plus_7"] * 1.18, 2),
                        "growth_rate_7": p["growth_rate_7"],
                        "temperature_mean": p["temperature_mean"],
                        "relative_humidity_mean": p["relative_humidity_mean"],
                        "precipitation_sum": p["precipitation_sum"],
                        "prediction_error": p["prediction_error"],
                    }
                    for p in points
                ],
            }
            for (code, disease), points in sorted(trends.items())
        ],
    }
    rankings = {
        "data_mode": "demo",
        "risk": risk_items,
        "growth": sorted(risk_items, key=lambda x: x["growth_rate_7"], reverse=True),
        "forecast": sorted(risk_items, key=lambda x: x["forecast_cases"], reverse=True),
    }
    weather_correlation = {
        "data_mode": "demo",
        "items": [
            {
                "date": p["date"],
                "location_code": p["location_code"],
                "location": p["location"],
                "disease": p["disease"],
                "temperature_mean": p["temperature_mean"],
                "relative_humidity_mean": p["relative_humidity_mean"],
                "precipitation_sum": p["precipitation_sum"],
                "new_cases_smoothed": p["new_cases_smoothed"],
            }
            for p in epidemic_rows[:: max(1, len(epidemic_rows) // 1200)]
        ],
    }
    disease_share = []
    for disease in DISEASES:
        total = sum(points[-1]["total_cases"] for (code, item_disease), points in trends.items() if item_disease == disease)
        disease_share.append({"disease": disease, "total_cases": round(total, 2)})

    options = {
        "data_mode": "demo",
        "locations": [
            {"code": loc.code, "name": loc.name, "latitude": loc.latitude, "longitude": loc.longitude}
            for loc in locations
        ],
        "diseases": DISEASES,
        "models": MODEL_NAMES,
        "date_range": {"start": start.isoformat(), "end": latest_date},
    }
    source_status = {
        "data_mode": "demo",
        "items": [
            {"name": "Demo epidemic generator", "status": "ok", "updated_at": collected_at, "rows": len(epidemic_rows)},
            {"name": "Demo weather generator", "status": "ok", "updated_at": collected_at, "rows": len(weather_rows)},
            {"name": "Demo population generator", "status": "ok", "updated_at": collected_at, "rows": len(population_rows)},
            {"name": "Real collectors", "status": "pending", "updated_at": None, "rows": 0},
        ],
    }

    return {
        "epidemic_rows": epidemic_rows,
        "weather_rows": weather_rows,
        "population_rows": population_rows,
        "serving": {
            "metadata.json": {
                "data_mode": "demo",
                "generated_at": collected_at,
                "generator": "src.collectors.generate_demo_data",
                "paths_are_relative": True,
            },
            "overview.json": overview,
            "trend.json": trends_payload,
            "risk_map.json": {"data_mode": "demo", "date": latest_date, "items": risk_items},
            "rankings.json": rankings,
            "model_metrics.json": model_metrics,
            "model_comparison.json": model_comparison,
            "predictions.json": {"data_mode": "demo", "items": test_points[-1200:]},
            "data_quality_report.json": quality_report,
            "options.json": options,
            "source_status.json": source_status,
            "weather_correlation.json": weather_correlation,
            "disease_share.json": {"data_mode": "demo", "items": disease_share},
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    payload = build_demo()
    raw_dir = ensure_dir("data/raw/demo")
    demo_dir = ensure_dir("data/demo")
    serving_dir = ensure_dir("data/serving")

    write_csv(raw_dir / "epidemic_daily_demo.csv", payload["epidemic_rows"])
    write_csv(raw_dir / "weather_daily_demo.csv", payload["weather_rows"])
    write_csv(raw_dir / "population_yearly_demo.csv", payload["population_rows"])
    write_csv(demo_dir / "epidemic_daily_demo.csv", payload["epidemic_rows"])
    write_csv(demo_dir / "weather_daily_demo.csv", payload["weather_rows"])
    write_csv(demo_dir / "population_yearly_demo.csv", payload["population_rows"])

    for filename, data in payload["serving"].items():
        write_json(serving_dir / filename, data)

    manifest = {
        "generated_files": [
            safe_relative(raw_dir / "epidemic_daily_demo.csv"),
            safe_relative(raw_dir / "weather_daily_demo.csv"),
            safe_relative(raw_dir / "population_yearly_demo.csv"),
            *[safe_relative(serving_dir / name) for name in payload["serving"]],
        ]
    }
    write_json(serving_dir / "demo_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
