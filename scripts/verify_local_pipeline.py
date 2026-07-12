from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.web.app import app  # noqa: E402


class Verification:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, passed: bool, detail: str, **data: Any) -> None:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {detail}", flush=True)
        self.checks.append({"name": name, "passed": passed, "detail": detail, **data})

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [item for item in self.checks if not item["passed"]]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def api_data(client, path: str) -> tuple[bool, Any, str]:
    response = client.get(path)
    payload = response.get_json(silent=True)
    if response.status_code != 200:
        return False, payload, f"HTTP {response.status_code}"
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False, payload, "response envelope is not ok"
    return True, payload.get("data"), "HTTP 200 and ok=true"


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.35)
        return connection.connect_ex((host, port)) == 0


def verify_files(result: Verification) -> None:
    required = [
        ROOT / "data/silver/local/epidemic_observations_clean.csv",
        ROOT / "data/silver/local/weather_daily_clean.csv",
        ROOT / "data/silver/local/historical_weather_daily_clean.csv",
        ROOT / "data/silver/local/historical_weather_annual_clean.csv",
        ROOT / "data/gold/local/forecast_features.csv",
        ROOT / "data/models/local/local_sklearn_gbdt.joblib",
        ROOT / "data/serving/options.json",
        ROOT / "data/serving/trend.json",
        ROOT / "data/serving/model_metrics.json",
        ROOT / "data/serving/model_data_coverage.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists() or path.stat().st_size == 0]
    result.add("required outputs", not missing, "all required local pipeline outputs exist" if not missing else f"missing: {missing}")

    daily_path = ROOT / "data/silver/local/historical_weather_daily_clean.csv"
    annual_path = ROOT / "data/silver/local/historical_weather_annual_clean.csv"
    if daily_path.exists() and annual_path.exists():
        daily = pd.read_csv(daily_path, parse_dates=["date"])
        annual = pd.read_csv(annual_path, parse_dates=["date"])
        daily_unique = daily[["location_code", "date"]].drop_duplicates().shape[0]
        daily_ok = len(daily) == daily_unique and len(daily) > len(annual)
        result.add(
            "historical weather granularity",
            daily_ok,
            f"daily={len(daily):,}, unique country-days={daily_unique:,}, annual={len(annual):,}",
        )

    metrics_path = ROOT / "data/serving/model_metrics.json"
    if metrics_path.exists():
        metrics = read_json(metrics_path)
        available = metrics.get("available_models", [])
        artifacts = {"local_sklearn_gbdt": ROOT / "data/models/local/local_sklearn_gbdt.joblib"}
        for model_name, details in metrics.get("models", {}).items():
            if details.get("status") != "trained" or not str(model_name).startswith("local_pytorch_lstm"):
                continue
            model_path = Path(str(details.get("model_path", "")))
            artifacts[model_name] = model_path if model_path.is_absolute() else ROOT / model_path
        missing_models = [name for name, path in artifacts.items() if not path.exists() or path.stat().st_size == 0]
        result.add(
            "model artifacts",
            not missing_models,
            f"available={','.join(available)}" if not missing_models else f"missing artifacts: {missing_models}",
        )


def verify_api(result: Verification) -> None:
    client = app.test_client()
    endpoints = [
        "/api/health",
        "/api/overview",
        "/api/options",
        "/api/risk-map",
        "/api/rankings",
        "/api/model-metrics",
        "/api/data-quality",
        "/api/disease-share",
        "/api/source-status",
        "/api/who-indicators",
        "/api/model-coverage",
    ]
    for endpoint in endpoints:
        ok, data, detail = api_data(client, endpoint)
        result.add(f"API {endpoint}", ok and data is not None, detail)

    ok, options, _ = api_data(client, "/api/options")
    if not ok or not isinstance(options, dict):
        return
    availability = options.get("availability", {})
    for disease, disease_options in availability.items():
        locations = disease_options.get("locations", [])
        ranges = disease_options.get("location_date_ranges", {})
        defaults_ok = bool(ranges) and all(
            window.get("default_start") == window.get("full_start")
            and window.get("default_end") == window.get("full_end")
            for window in ranges.values()
        )
        result.add(f"full default range {disease}", defaults_ok, f"series={len(ranges)}")
        if not locations:
            result.add(f"filtered API {disease}", False, "no locations")
            continue
        location = locations[0]["code"]
        window = ranges[location]
        model = (disease_options.get("models") or ["moving_average"])[0]
        query = urlencode(
            {
                "disease": disease,
                "location": location,
                "model": model,
                "start_date": window["default_start"],
                "end_date": window["default_end"],
            }
        )
        trend_ok, trend, trend_detail = api_data(client, f"/api/trend?{query}")
        points = trend.get("points", []) if isinstance(trend, dict) else []
        range_ok = bool(points) and points[0].get("date") == window["full_start"] and points[-1].get("date") == window["full_end"]
        result.add(
            f"trend range {disease}/{location}",
            trend_ok and range_ok,
            f"{trend_detail}; points={len(points):,}",
        )
        for endpoint in ["overview", "predictions", "weather-correlation"]:
            endpoint_ok, _, endpoint_detail = api_data(client, f"/api/{endpoint}?{query}")
            result.add(f"filtered API {endpoint} {disease}/{location}", endpoint_ok, endpoint_detail)

        lstm_models = [
            candidate
            for candidate in disease_options.get("models", [])
            if str(candidate).startswith("local_pytorch_lstm")
        ]
        if len(lstm_models) != 1:
            result.add(f"disease LSTM {disease}", False, f"expected one model, found {lstm_models}")
            continue
        lstm_query = urlencode(
            {
                "disease": disease,
                "location": location,
                "model": lstm_models[0],
                "start_date": window["default_start"],
                "end_date": window["default_end"],
            }
        )
        lstm_trend_ok, lstm_trend, _ = api_data(client, f"/api/trend?{lstm_query}")
        lstm_points = lstm_trend.get("points", []) if isinstance(lstm_trend, dict) else []
        prediction_count = sum(point.get("prediction") is not None for point in lstm_points)
        lstm_predictions_ok, lstm_predictions, _ = api_data(client, f"/api/predictions?{lstm_query}")
        exported_prediction_count = sum(
            item.get("prediction") is not None
            for item in (lstm_predictions.get("items", []) if isinstance(lstm_predictions, dict) else [])
        )
        metrics_ok, disease_metrics, _ = api_data(
            client,
            f"/api/model-metrics?{urlencode({'disease': disease})}",
        )
        model_in_metrics = lstm_models[0] in (disease_metrics.get("models", {}) if isinstance(disease_metrics, dict) else {})
        result.add(
            f"disease LSTM {disease}",
            lstm_trend_ok and lstm_predictions_ok and metrics_ok and model_in_metrics and prediction_count > 0 and exported_prediction_count > 0,
            f"model={lstm_models[0]}, trend predictions={prediction_count:,}, evaluated predictions={exported_prediction_count:,}",
        )

    coverage_ok, coverage, _ = api_data(client, "/api/model-coverage")
    if coverage_ok and isinstance(coverage, dict):
        models = {item.get("model"): item for item in coverage.get("models", [])}
        gbdt = models.get("local_sklearn_gbdt", {})
        summary = coverage.get("summary", {})
        coverage_valid = (
            gbdt.get("input_rows", 0) > 10000
            and gbdt.get("uses_weather") is True
            and summary.get("all_diseases_have_independent_lstm") is True
            and summary.get("disease_lstm_models_trained") == 6
        )
        result.add(
            "learned model data coverage",
            coverage_valid,
            f"GBDT rows={gbdt.get('input_rows', 0):,}; disease LSTMs={summary.get('disease_lstm_models_trained')}/6",
        )


def verify_ports(result: Verification) -> list[dict[str, Any]]:
    ports = [
        (5000, "Flask web", True),
        (9870, "HDFS NameNode UI", False),
        (8088, "YARN ResourceManager UI", False),
        (8080, "Spark master/UI", False),
        (7077, "Spark standalone master", False),
    ]
    states = []
    for port, name, local_runtime_port in ports:
        opened = port_open("127.0.0.1", port)
        states.append({"host": "127.0.0.1", "port": port, "name": name, "open": opened, "required_by_local_pipeline": local_runtime_port})
        requirement = "required only while the web server is running" if local_runtime_port else "optional in pandas local mode"
        print(f"[INFO] port {port} {name}: {'open' if opened else 'closed'} ({requirement})", flush=True)
    return states


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local Silver/Gold/model/serving outputs and Flask API contracts.")
    parser.add_argument("--output", default="data/serving/local_pipeline_verification.json")
    args = parser.parse_args()

    print("[VERIFY] Checking local pipeline files, models, APIs, and ports...", flush=True)
    result = Verification()
    verify_files(result)
    verify_api(result)
    ports = verify_ports(result)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "real_local_multi_source",
        "passed": not result.failures,
        "check_count": len(result.checks),
        "failure_count": len(result.failures),
        "checks": result.checks,
        "ports": ports,
        "port_note": "The pandas local pipeline does not require HDFS, YARN, or Spark ports; Flask uses TCP 5000 when running.",
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[VERIFY] Report: {output.relative_to(ROOT)}", flush=True)
    if result.failures:
        print(f"[VERIFY] FAILED: {len(result.failures)} checks failed.", flush=True)
        raise SystemExit(1)
    print(f"[VERIFY] PASSED: {len(result.checks)} checks.", flush=True)


if __name__ == "__main__":
    main()
