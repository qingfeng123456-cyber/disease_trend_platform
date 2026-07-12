"""Frequency-aware PyTorch LSTM training for each real local disease series.

Each disease is trained independently at its native daily, weekly, or annual
frequency. Calendar gaps may be interpolated only inside an input window;
training targets always come from an observed future period.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.models.metrics import regression_metrics

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None


MODEL_NAME = "local_pytorch_lstm"
PYTORCH_INSTALL_COMMAND = (
    "conda run --no-capture-output -n intership python -m pip install "
    "torch --index-url https://download.pytorch.org/whl/cpu"
)


def pytorch_available() -> bool:
    return torch is not None


def require_pytorch() -> None:
    if not pytorch_available():
        raise RuntimeError(
            "PyTorch is not installed in the current environment, so LSTM was not trained.\n"
            f"Install the CPU build first:\n  {PYTORCH_INSTALL_COMMAND}"
        )


if nn is not None:

    class LSTMRegressor(nn.Module):
        def __init__(self, *, hidden_size: int, location_count: int, dropout: float = 0.1):
            super().__init__()
            embedding_size = min(8, max(2, math.ceil(math.log2(location_count + 1))))
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden_size, batch_first=True)
            self.location_embedding = nn.Embedding(location_count, embedding_size)
            self.head = nn.Sequential(
                nn.Linear(hidden_size + embedding_size, hidden_size),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_size, 1),
            )

        def forward(self, sequence, location_index):
            output, _ = self.lstm(sequence)
            location_vector = self.location_embedding(location_index)
            combined = torch.cat([output[:, -1, :], location_vector], dim=1)
            return self.head(combined)


@dataclass
class WindowBundle:
    x: np.ndarray
    location_indices: np.ndarray
    targets_scaled: np.ndarray
    targets_raw: np.ndarray
    baseline_raw: np.ndarray
    current_raw: np.ndarray
    row_indices: np.ndarray
    dates: np.ndarray
    train_mask: np.ndarray
    validation_mask: np.ndarray
    test_mask: np.ndarray
    location_to_index: dict[str, int]
    scaler: StandardScaler
    train_cut: pd.Timestamp
    validation_cut: pd.Timestamp
    min_date: pd.Timestamp
    max_date: pd.Timestamp
    calendar_rows_inserted: int
    input_values_imputed: int
    windows_skipped_nonfinite: int
    series_column: str


def _set_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def _duration(seconds: float) -> str:
    seconds = max(float(seconds), 0.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m{remainder:02d}s"


def _bar(current: int, total: int, width: int = 24) -> str:
    total = max(total, 1)
    done = min(width, int(width * current / total))
    return "=" * done + "." * (width - done)


def _frequency_rule(frequency: str) -> str:
    rules = {"daily": "D", "weekly": "W-SAT", "annual": "YE-DEC"}
    if frequency not in rules:
        raise ValueError(f"Unsupported LSTM frequency: {frequency}")
    return rules[frequency]


def _rolling_window(frequency: str) -> int:
    return {"daily": 7, "weekly": 4, "annual": 3}[frequency]


def prepare_windows(
    features: pd.DataFrame,
    *,
    window: int,
    disease: str = "COVID-19",
    frequency: str = "daily",
    horizon_steps: int | None = None,
    max_imputation_gap: int | None = None,
) -> WindowBundle:
    series_column = "new_cases_smoothed" if frequency == "daily" else "value"
    required = {
        "date",
        "location_code",
        "disease",
        "frequency",
        series_column,
        "rolling_mean_7",
        "target_t_plus_7",
    }
    missing = sorted(required - set(features.columns))
    if missing:
        raise ValueError(f"Gold feature table is missing required columns: {', '.join(missing)}")

    if window < 2:
        raise ValueError("LSTM window must be at least 2 periods.")
    horizon_steps = int(horizon_steps if horizon_steps is not None else (7 if frequency == "daily" else 1))
    max_imputation_gap = int(
        max_imputation_gap if max_imputation_gap is not None else {"daily": 3, "weekly": 2, "annual": 1}[frequency]
    )
    scope = features[
        features["disease"].eq(disease) & features["frequency"].eq(frequency)
    ].copy()
    if scope.empty:
        raise ValueError(f"No {disease} {frequency} rows are available for LSTM training.")
    scope["date"] = pd.to_datetime(scope["date"], errors="coerce")
    scope[series_column] = pd.to_numeric(scope[series_column], errors="coerce")
    scope["rolling_mean_7"] = pd.to_numeric(scope["rolling_mean_7"], errors="coerce")
    scope = scope.dropna(subset=["date", "location_code", series_column])
    scope = scope.sort_values(["location_code", "date"])
    locations = sorted(scope["location_code"].astype(str).unique().tolist())
    location_to_index = {code: index for index, code in enumerate(locations)}

    sequences_raw: list[np.ndarray] = []
    location_indices: list[int] = []
    targets_raw: list[float] = []
    baseline_raw: list[float] = []
    current_raw: list[float] = []
    row_indices: list[int] = []
    dates: list[np.datetime64] = []
    calendar_rows_inserted = 0
    input_values_imputed = 0
    windows_skipped_nonfinite = 0
    frequency_rule = _frequency_rule(frequency)
    rolling_window = _rolling_window(frequency)

    for code, group in scope.groupby("location_code", sort=False):
        group = group.sort_values("date").drop_duplicates("date", keep="last").copy()
        group["_feature_index"] = group.index.astype("int64")
        expected_dates = pd.date_range(group["date"].min(), group["date"].max(), freq=frequency_rule)
        regular = group.set_index("date").reindex(expected_dates)
        regular.index.name = "date"
        calendar_rows_inserted += int(regular["_feature_index"].isna().sum())
        observed = regular["_feature_index"].notna() & regular[series_column].notna()
        raw_values = pd.to_numeric(regular[series_column], errors="coerce").clip(lower=0)
        input_values = raw_values.interpolate(
            method="linear",
            limit=max_imputation_gap,
            limit_area="inside",
        )
        input_values_imputed += int((raw_values.isna() & input_values.notna()).sum())
        baseline_values = input_values.rolling(rolling_window, min_periods=1).mean()
        feature_indices = regular["_feature_index"].to_numpy(dtype=float)
        group_dates = regular.index.to_numpy(dtype="datetime64[ns]")
        values_array = input_values.to_numpy(dtype=np.float32)
        observed_array = observed.to_numpy(dtype=bool)
        baseline_array = baseline_values.to_numpy(dtype=np.float32)
        for position in range(window - 1, len(regular)):
            if not np.isfinite(feature_indices[position]):
                continue
            sequence = values_array[position - window + 1 : position + 1]
            if len(sequence) != window or not np.isfinite(sequence).all():
                windows_skipped_nonfinite += 1
                continue
            target_position = position + horizon_steps
            target_raw = np.nan
            if target_position < len(regular) and observed_array[target_position]:
                target_raw = float(values_array[target_position])
            sequences_raw.append(sequence[:, None])
            location_indices.append(location_to_index[str(code)])
            targets_raw.append(float(target_raw))
            baseline_raw.append(float(baseline_array[position]))
            current_raw.append(float(values_array[position]))
            row_indices.append(int(feature_indices[position]))
            dates.append(group_dates[position])

    if not sequences_raw:
        raise ValueError(f"No complete {disease} input windows are available; window={window}.")
    raw_x = np.asarray(sequences_raw, dtype=np.float32)
    location_array = np.asarray(location_indices, dtype=np.int64)
    target_raw_array = np.asarray(targets_raw, dtype=np.float32)
    baseline_array = np.asarray(baseline_raw, dtype=np.float32)
    current_array = np.asarray(current_raw, dtype=np.float32)
    row_index_array = np.asarray(row_indices, dtype=np.int64)
    date_array = np.asarray(dates, dtype="datetime64[ns]")
    finite_target = np.isfinite(target_raw_array)
    if finite_target.sum() < 6:
        raise ValueError(f"Only {int(finite_target.sum())} observed {disease} targets are available for LSTM training.")
    target_dates = date_array[finite_target]
    min_date = pd.Timestamp(target_dates.min())
    max_date = pd.Timestamp(target_dates.max())
    total_days = max((max_date - min_date).days, 1)
    train_cut = min_date + pd.Timedelta(days=int(total_days * 0.70))
    validation_cut = min_date + pd.Timedelta(days=int(total_days * 0.85))
    train_mask = finite_target & (date_array <= np.datetime64(train_cut))
    validation_mask = finite_target & (date_array > np.datetime64(train_cut)) & (date_array <= np.datetime64(validation_cut))
    test_mask = finite_target & (date_array > np.datetime64(validation_cut))
    if train_mask.sum() == 0 or validation_mask.sum() == 0 or test_mask.sum() == 0:
        raise ValueError(
            "The time split produced an empty LSTM partition: "
            f"train={train_mask.sum()}, validation={validation_mask.sum()}, test={test_mask.sum()}"
        )
    train_sequence_values = np.log1p(raw_x[train_mask].reshape(-1, 1))
    scaler = StandardScaler().fit(train_sequence_values)
    x = scaler.transform(np.log1p(raw_x).reshape(-1, 1)).reshape(raw_x.shape).astype(np.float32)
    target_scaled_array = np.full((len(target_raw_array), 1), np.nan, dtype=np.float32)
    target_scaled_array[finite_target] = scaler.transform(
        np.log1p(target_raw_array[finite_target].clip(min=0)).reshape(-1, 1)
    ).astype(np.float32)
    return WindowBundle(
        x=x,
        location_indices=location_array,
        targets_scaled=target_scaled_array,
        targets_raw=target_raw_array,
        baseline_raw=baseline_array,
        current_raw=current_array,
        row_indices=row_index_array,
        dates=date_array,
        train_mask=train_mask,
        validation_mask=validation_mask,
        test_mask=test_mask,
        location_to_index=location_to_index,
        scaler=scaler,
        train_cut=train_cut,
        validation_cut=validation_cut,
        min_date=min_date,
        max_date=max_date,
        calendar_rows_inserted=calendar_rows_inserted,
        input_values_imputed=input_values_imputed,
        windows_skipped_nonfinite=windows_skipped_nonfinite,
        series_column=series_column,
    )


def _make_loader(bundle: WindowBundle, mask: np.ndarray, *, batch_size: int, shuffle: bool):
    indices = np.flatnonzero(mask)
    dataset = TensorDataset(
        torch.from_numpy(bundle.x[indices]),
        torch.from_numpy(bundle.location_indices[indices]),
        torch.from_numpy(bundle.targets_scaled[indices]),
    )
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=0)


def _evaluate_loss(model, loader, loss_fn, device) -> float:
    model.eval()
    total_loss = 0.0
    total_rows = 0
    with torch.no_grad():
        for batch_x, batch_locations, batch_y in loader:
            batch_x = batch_x.to(device)
            batch_locations = batch_locations.to(device)
            batch_y = batch_y.to(device)
            prediction = model(batch_x, batch_locations)
            loss = loss_fn(prediction, batch_y)
            total_loss += float(loss.item()) * len(batch_x)
            total_rows += len(batch_x)
    return total_loss / max(total_rows, 1)


def _predict_scaled(model, x: np.ndarray, locations: np.ndarray, *, batch_size: int, device) -> np.ndarray:
    dataset = TensorDataset(torch.from_numpy(x), torch.from_numpy(locations))
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    predictions: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for batch_x, batch_locations in loader:
            prediction = model(batch_x.to(device), batch_locations.to(device)).cpu().numpy()
            predictions.append(prediction)
    return np.concatenate(predictions, axis=0)


def _inverse_scaled_predictions(values: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    predicted_log = scaler.inverse_transform(values)
    return np.expm1(predicted_log).clip(min=0).ravel()


def train_lstm_forecaster(
    features: pd.DataFrame,
    *,
    model_output: str | Path,
    disease: str = "COVID-19",
    frequency: str = "daily",
    model_name: str = MODEL_NAME,
    horizon_steps: int | None = None,
    max_imputation_gap: int | None = None,
    window: int = 28,
    epochs: int = 20,
    batch_size: int = 128,
    hidden_size: int = 32,
    learning_rate: float = 1e-3,
    patience: int = 5,
    seed: int = 2026,
    show_batch_progress: bool = True,
) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    require_pytorch()
    if epochs <= 0:
        raise ValueError("epochs must be greater than zero.")
    if patience < 0:
        raise ValueError("patience must be zero (disabled) or a positive number.")
    _set_seeds(seed)
    overall_started = time.perf_counter()
    horizon_steps = int(horizon_steps if horizon_steps is not None else (7 if frequency == "daily" else 1))
    prefix = f"[LSTM][{disease}]"
    print(f"{prefix} Preparing real {frequency} windows...", flush=True)
    bundle = prepare_windows(
        features,
        window=window,
        disease=disease,
        frequency=frequency,
        horizon_steps=horizon_steps,
        max_imputation_gap=max_imputation_gap,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(
        f"{prefix} Prepared "
        f"windows={len(bundle.x):,}, train={bundle.train_mask.sum():,}, "
        f"validation={bundle.validation_mask.sum():,}, test={bundle.test_mask.sum():,}, "
        f"locations={len(bundle.location_to_index)}, window={window}, device={device}",
        flush=True,
    )
    print(
        f"{prefix} Time split: train <= {bundle.train_cut.date()}, "
        f"validation <= {bundle.validation_cut.date()}, test <= {bundle.max_date.date()}",
        flush=True,
    )

    train_loader = _make_loader(bundle, bundle.train_mask, batch_size=batch_size, shuffle=True)
    validation_loader = _make_loader(bundle, bundle.validation_mask, batch_size=batch_size, shuffle=False)
    model = LSTMRegressor(
        hidden_size=hidden_size,
        location_count=len(bundle.location_to_index),
    ).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    train_batches_per_epoch = len(train_loader)
    early_stopping_enabled = patience > 0
    early_stopping_message = (
        f"enabled (patience={patience}); training may finish before {epochs} epochs"
        if early_stopping_enabled
        else f"disabled; all {epochs} epochs will run"
    )
    print(
        f"{prefix} Model parameters={parameter_count:,}, batches/epoch={train_batches_per_epoch:,}, "
        f"early stopping {early_stopping_message}.",
        flush=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.SmoothL1Loss()
    best_state = copy.deepcopy(model.state_dict())
    best_validation_loss = float("inf")
    best_validation_mae = float("inf")
    stale_epochs = 0
    epoch_durations: list[float] = []
    epochs_trained = 0
    best_epoch = 0
    early_stopped = False

    for epoch in range(1, epochs + 1):
        epoch_started = time.perf_counter()
        model.train()
        running_loss = 0.0
        seen_rows = 0
        total_batches = len(train_loader)
        batch_interval = max(1, total_batches // 4)
        for batch_number, (batch_x, batch_locations, batch_y) in enumerate(train_loader, start=1):
            batch_x = batch_x.to(device)
            batch_locations = batch_locations.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad(set_to_none=True)
            prediction = model(batch_x, batch_locations)
            loss = loss_fn(prediction, batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            running_loss += float(loss.item()) * len(batch_x)
            seen_rows += len(batch_x)
            if show_batch_progress and (batch_number % batch_interval == 0 or batch_number == total_batches):
                percent = int(batch_number / max(total_batches, 1) * 100)
                print(
                    f"  {prefix} [{_bar(batch_number, total_batches)}] epoch {epoch:02d}/{epochs:02d} "
                    f"batch {batch_number:03d}/{total_batches:03d} {percent:3d}% "
                    f"loss={running_loss / max(seen_rows, 1):.6f}",
                    flush=True,
                )

        train_loss = running_loss / max(seen_rows, 1)
        validation_loss = _evaluate_loss(model, validation_loader, loss_fn, device)
        validation_predictions_scaled = _predict_scaled(
            model,
            bundle.x[bundle.validation_mask],
            bundle.location_indices[bundle.validation_mask],
            batch_size=batch_size,
            device=device,
        )
        validation_predictions_raw = _inverse_scaled_predictions(
            validation_predictions_scaled,
            bundle.scaler,
        )
        validation_actual_raw = bundle.targets_raw[bundle.validation_mask]
        validation_mae = float(np.mean(np.abs(validation_predictions_raw - validation_actual_raw)))
        elapsed = time.perf_counter() - epoch_started
        epoch_durations.append(elapsed)
        eta = (sum(epoch_durations) / len(epoch_durations)) * (epochs - epoch)
        improved = validation_mae < best_validation_mae - 1e-6
        marker = " best" if improved else ""
        print(
            f"{prefix} Epoch {epoch:02d}/{epochs:02d} complete | "
            f"train_loss={train_loss:.6f} | val_loss={validation_loss:.6f} | val_mae={validation_mae:.4f} | "
            f"elapsed={_duration(elapsed)} | eta={_duration(eta)}{marker}",
            flush=True,
        )
        epochs_trained = epoch
        if improved:
            best_validation_loss = validation_loss
            best_validation_mae = validation_mae
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            stale_epochs = 0
        else:
            stale_epochs += 1
            if early_stopping_enabled and stale_epochs >= patience:
                early_stopped = True
                print(
                    f"{prefix} Early stopping after {epoch} epochs; validation MAE did not improve for {patience} epochs.",
                    flush=True,
                )
                break

    model.load_state_dict(best_state)
    print(f"{prefix} Generating predictions for all eligible windows...", flush=True)
    predicted_scaled = _predict_scaled(
        model,
        bundle.x,
        bundle.location_indices,
        batch_size=batch_size,
        device=device,
    )
    predicted_raw = _inverse_scaled_predictions(predicted_scaled, bundle.scaler)
    prediction_series = pd.Series(np.nan, index=features.index, dtype=float)
    prediction_series.loc[bundle.row_indices] = predicted_raw

    test_predictions = predicted_raw[bundle.test_mask]
    test_actual = bundle.targets_raw[bundle.test_mask]
    test_moving_average = bundle.baseline_raw[bundle.test_mask]
    test_naive = bundle.current_raw[bundle.test_mask]
    model_metrics = regression_metrics(test_actual.tolist(), test_predictions.tolist())
    moving_average_metrics = regression_metrics(test_actual.tolist(), test_moving_average.tolist())
    naive_metrics = regression_metrics(test_actual.tolist(), test_naive.tolist())
    baseline_metrics = {
        "naive_last_value": naive_metrics,
        "moving_average": moving_average_metrics,
    }
    best_baseline_name, best_baseline_metrics = min(
        baseline_metrics.items(),
        key=lambda item: float(item[1]["mae"]),
    )
    training_seconds = time.perf_counter() - overall_started
    model_path = Path(model_output)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_name": model_name,
            "disease": disease,
            "frequency": frequency,
            "state_dict": model.state_dict(),
            "window": window,
            "hidden_size": hidden_size,
            "epochs_requested": epochs,
            "epochs_trained": epochs_trained,
            "patience": patience,
            "early_stopped": early_stopped,
            "best_epoch": best_epoch,
            "best_validation_loss": best_validation_loss,
            "best_validation_mae": best_validation_mae,
            "model_selection_metric": "validation_mae_original_scale",
            "target_column": bundle.series_column,
            "location_to_index": bundle.location_to_index,
            "scaler_mean": bundle.scaler.mean_.tolist(),
            "scaler_scale": bundle.scaler.scale_.tolist(),
            "forecast_horizon_steps": horizon_steps,
            "trained_at": pd.Timestamp.utcnow().isoformat(),
        },
        model_path,
    )
    metrics = {
        "model": model_name,
        "disease": disease,
        "frequency": frequency,
        "status": "trained",
        "framework": "PyTorch",
        "device": str(device),
        "forecast_horizon": horizon_steps,
        "forecast_horizon_unit": {"daily": "day", "weekly": "week", "annual": "year"}[frequency],
        "window": window,
        "hidden_size": hidden_size,
        "epochs_requested": epochs,
        "epochs_trained": epochs_trained,
        "patience": patience,
        "early_stopping_enabled": early_stopping_enabled,
        "early_stopped": early_stopped,
        "best_epoch": best_epoch,
        "best_validation_loss": round(float(best_validation_loss), 8),
        "best_validation_mae": round(float(best_validation_mae), 8),
        "model_selection_metric": "validation_mae_original_scale",
        "training_loss": "SmoothL1Loss on standardized log1p target",
        "batch_size": batch_size,
        "train_batches_per_epoch": train_batches_per_epoch,
        "parameter_count": parameter_count,
        "total_windows": int(len(bundle.x)),
        "calendar_rows_inserted": bundle.calendar_rows_inserted,
        "input_values_imputed": bundle.input_values_imputed,
        "windows_skipped_nonfinite": bundle.windows_skipped_nonfinite,
        "location_count": len(bundle.location_to_index),
        "location_codes": sorted(bundle.location_to_index),
        "training_seconds": round(float(training_seconds), 3),
        "input_features": [f"previous {window} {frequency} {bundle.series_column} values", "location embedding"],
        "target_column": bundle.series_column,
        "uses_external_covariates": False,
        "train_start": bundle.min_date.date().isoformat(),
        "train_end": bundle.train_cut.date().isoformat(),
        "validation_end": bundle.validation_cut.date().isoformat(),
        "test_end": bundle.max_date.date().isoformat(),
        "train_rows": int(bundle.train_mask.sum()),
        "validation_rows": int(bundle.validation_mask.sum()),
        "test_rows": int(bundle.test_mask.sum()),
        **model_metrics,
        "baseline_metrics": baseline_metrics,
        "best_baseline": best_baseline_name,
        "baseline_mae": best_baseline_metrics["mae"],
        "beats_baseline": model_metrics["mae"] <= best_baseline_metrics["mae"],
        "model_path": str(model_path).replace("\\", "/"),
        "scope": f"{disease} {frequency} {bundle.series_column} target only",
        "note": (
            "Disease-specific native-frequency LSTM with location embedding and chronological split. "
            "Only bounded input gaps may be interpolated; future targets must be observed. "
            "The best checkpoint is selected by validation MAE on the original target scale."
        ),
    }
    split = np.full(len(bundle.row_indices), "forecast_only", dtype=object)
    split[bundle.train_mask] = "train"
    split[bundle.validation_mask] = "validation"
    split[bundle.test_mask] = "test"
    prediction_rows = pd.DataFrame(
        {
            "model": model_name,
            "disease": disease,
            "frequency": frequency,
            "feature_index": bundle.row_indices,
            "date": pd.to_datetime(bundle.dates),
            "location_index": bundle.location_indices,
            "actual_t_plus_7": bundle.targets_raw,
            "naive_last_value": bundle.current_raw,
            "moving_average": bundle.baseline_raw,
            "prediction": predicted_raw,
            "split": split,
        }
    )
    prediction_rows["location_code"] = prediction_rows["location_index"].map(
        {value: key for key, value in bundle.location_to_index.items()}
    )
    prediction_rows["error"] = prediction_rows["prediction"] - prediction_rows["actual_t_plus_7"]
    print(
        f"{prefix} Training complete in {_duration(time.perf_counter() - overall_started)} | "
        f"epochs={epochs_trained}/{epochs}, best_epoch={best_epoch} | "
        f"MAE={metrics['mae']:.4f} | RMSE={metrics['rmse']:.4f} | "
        f"baseline_MAE={metrics['baseline_mae']:.4f} | model={model_path}",
        flush=True,
    )
    return prediction_series, metrics, prediction_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Train one native-frequency disease LSTM on the real local Gold feature CSV.")
    parser.add_argument("--input", default="data/gold/local/forecast_features.csv")
    parser.add_argument("--model-output", default="data/models/local/local_pytorch_lstm.pt")
    parser.add_argument("--predictions-output", default="data/gold/local/lstm_predictions.csv")
    parser.add_argument("--metrics-output", default="data/serving/lstm_metrics.json")
    parser.add_argument("--disease", default="COVID-19")
    parser.add_argument("--frequency", choices=["daily", "weekly", "annual"], default="daily")
    parser.add_argument("--model-name", default=MODEL_NAME)
    parser.add_argument("--horizon-steps", type=int, default=None)
    parser.add_argument("--max-imputation-gap", type=int, default=None)
    parser.add_argument("--window", type=int, default=28)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument(
        "--patience",
        type=int,
        default=5,
        help="Stop after this many non-improving validation epochs; use 0 to disable early stopping.",
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--no-batch-progress", action="store_true")
    args = parser.parse_args()

    try:
        require_pytorch()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    features = pd.read_csv(args.input, parse_dates=["date"], low_memory=False)
    prediction_series, metrics, prediction_rows = train_lstm_forecaster(
        features,
        model_output=args.model_output,
        disease=args.disease,
        frequency=args.frequency,
        model_name=args.model_name,
        horizon_steps=args.horizon_steps,
        max_imputation_gap=args.max_imputation_gap,
        window=args.window,
        epochs=args.epochs,
        batch_size=args.batch_size,
        hidden_size=args.hidden_size,
        learning_rate=args.learning_rate,
        patience=args.patience,
        seed=args.seed,
        show_batch_progress=not args.no_batch_progress,
    )
    predictions_path = Path(args.predictions_output)
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_rows.to_csv(predictions_path, index=False, encoding="utf-8-sig")
    metrics_path = Path(args.metrics_output)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
