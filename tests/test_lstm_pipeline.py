from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.models.lstm_optional import PYTORCH_INSTALL_COMMAND, prepare_windows, pytorch_available, require_pytorch
from src.web.services.data_service import DataService


def make_features() -> pd.DataFrame:
    rows = []
    for location_index, code in enumerate(["CHN", "USA"]):
        dates = pd.date_range("2020-01-01", periods=180, freq="D")
        values = np.arange(len(dates), dtype=float) + location_index * 10
        for index, (day, value) in enumerate(zip(dates, values)):
            rows.append(
                {
                    "date": day,
                    "location_code": code,
                    "disease": "COVID-19",
                    "frequency": "daily",
                    "new_cases_smoothed": value,
                    "rolling_mean_7": value,
                    "target_t_plus_7": values[index + 7] if index + 7 < len(values) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def test_prepare_lstm_windows_uses_chronological_partitions():
    bundle = prepare_windows(make_features(), window=28)
    assert bundle.x.shape[1:] == (28, 1)
    assert len(bundle.location_to_index) == 2
    assert bundle.train_mask.sum() > 0
    assert bundle.validation_mask.sum() > 0
    assert bundle.test_mask.sum() > 0
    assert bundle.dates[bundle.train_mask].max() <= np.datetime64(bundle.train_cut)
    assert bundle.dates[bundle.validation_mask].min() > np.datetime64(bundle.train_cut)
    assert bundle.dates[bundle.test_mask].min() > np.datetime64(bundle.validation_cut)


def test_prepare_weekly_windows_regularizes_input_gap_without_creating_target_label():
    dates = pd.date_range("2023-01-07", periods=60, freq="W-SAT")
    rows = []
    for index, day in enumerate(dates):
        if index == 20:
            continue
        rows.append(
            {
                "date": day,
                "location_code": "USA",
                "disease": "Influenza",
                "frequency": "weekly",
                "value": float(index + 1),
                "new_cases_smoothed": float(index + 1),
                "rolling_mean_7": float(index + 1),
                "target_t_plus_7": np.nan,
            }
        )
    bundle = prepare_windows(
        pd.DataFrame(rows),
        disease="Influenza",
        frequency="weekly",
        window=8,
        horizon_steps=1,
        max_imputation_gap=1,
    )
    assert bundle.calendar_rows_inserted == 1
    assert bundle.input_values_imputed == 1
    assert bundle.train_mask.sum() > 0
    assert bundle.validation_mask.sum() > 0
    assert bundle.test_mask.sum() > 0


def test_prepare_weekly_windows_targets_native_observations_not_rolling_mean():
    dates = pd.date_range("2023-01-07", periods=60, freq="W-SAT")
    frame = pd.DataFrame(
        {
            "date": dates,
            "location_code": "USA",
            "disease": "Influenza",
            "frequency": "weekly",
            "value": np.arange(1, 61, dtype=float),
            "new_cases_smoothed": np.arange(1001, 1061, dtype=float),
            "rolling_mean_7": np.arange(2001, 2061, dtype=float),
            "target_t_plus_7": np.nan,
        }
    )
    bundle = prepare_windows(
        frame,
        disease="Influenza",
        frequency="weekly",
        window=8,
        horizon_steps=1,
    )
    assert bundle.series_column == "value"
    assert bundle.current_raw.max() <= 60
    assert bundle.targets_raw[np.isfinite(bundle.targets_raw)].max() <= 60


def test_missing_pytorch_error_contains_install_command():
    if pytorch_available():
        require_pytorch()
        return
    with pytest.raises(RuntimeError, match="PyTorch is not installed") as exc_info:
        require_pytorch()
    assert PYTORCH_INSTALL_COMMAND in str(exc_info.value)


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_data_service_selects_requested_trained_model(tmp_path):
    write_json(
        tmp_path / "options.json",
        {
            "locations": [{"code": "CHN", "name": "China"}],
            "diseases": ["COVID-19"],
            "models": ["moving_average", "local_sklearn_gbdt", "local_pytorch_lstm"],
            "default_model": "local_pytorch_lstm",
        },
    )
    write_json(
        tmp_path / "trend.json",
        {
            "data_mode": "test",
            "items": [
                {
                    "location_code": "CHN",
                    "location": "China",
                    "disease": "COVID-19",
                    "frequency": "daily",
                    "metric": "new_cases",
                    "metric_label": "daily cases",
                    "rolling_label": "7-day mean",
                    "forecast_horizon_label": "t+7",
                    "points": [
                        {
                            "date": "2025-01-01",
                            "actual": 10.0,
                            "rolling_7": 11.0,
                            "prediction_local_sklearn_gbdt": 12.0,
                            "prediction_local_pytorch_lstm": 13.0,
                        }
                    ],
                }
            ],
        },
    )
    write_json(
        tmp_path / "predictions.json",
        {
            "items": [
                {
                    "date": "2025-01-01",
                    "location_code": "CHN",
                    "disease": "COVID-19",
                    "actual_t_plus_7": 14.0,
                    "prediction_local_sklearn_gbdt": 12.0,
                    "prediction_local_pytorch_lstm": 13.0,
                }
            ]
        },
    )

    service = DataService(serving_dir=tmp_path, cache_seconds=1)
    trend = service.trend(location="CHN", disease="COVID-19", model="local_pytorch_lstm")
    assert trend["model"] == "local_pytorch_lstm"
    assert trend["points"][0]["prediction"] == 13.0
    predictions = service.predictions(location="CHN", disease="COVID-19", model="local_pytorch_lstm")
    assert predictions["items"][0]["prediction"] == 13.0
    assert predictions["items"][0]["error"] == -1.0
