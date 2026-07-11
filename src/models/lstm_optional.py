"""Optional PyTorch LSTM for the real local COVID-19 Gold feature table.

The model uses the previous ``window`` daily smoothed case values to predict
the t+7 target already created by the local feature pipeline. Data is split by
date before windows are assigned to train, validation, and test sets.
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


def prepare_windows(features: pd.DataFrame, *, window: int) -> WindowBundle:
    required = {
        "date",
        "location_code",
        "disease",
        "frequency",
        "new_cases_smoothed",
        "rolling_mean_7",
        "target_t_plus_7",
    }
    missing = sorted(required - set(features.columns))
    if missing:
        raise ValueError(f"Gold feature table is missing required columns: {', '.join(missing)}")

    scope = features[
        features["disease"].eq("COVID-19") & features["frequency"].eq("daily")
    ].copy()
    scope["date"] = pd.to_datetime(scope["date"], errors="coerce")
    scope["new_cases_smoothed"] = pd.to_numeric(scope["new_cases_smoothed"], errors="coerce")
    scope["target_t_plus_7"] = pd.to_numeric(scope["target_t_plus_7"], errors="coerce")
    scope["rolling_mean_7"] = pd.to_numeric(scope["rolling_mean_7"], errors="coerce")
    scope = scope.dropna(subset=["date", "location_code", "new_cases_smoothed"])
    scope = scope.sort_values(["location_code", "date"])

    target_rows = scope.dropna(subset=["target_t_plus_7"])
    if target_rows.empty:
        raise ValueError("No valid COVID-19 t+7 targets are available for LSTM training.")
    min_date = target_rows["date"].min()
    max_date = target_rows["date"].max()
    total_days = max((max_date - min_date).days, 1)
    train_cut = min_date + pd.Timedelta(days=int(total_days * 0.70))
    validation_cut = min_date + pd.Timedelta(days=int(total_days * 0.85))

    train_values = scope.loc[scope["date"] <= train_cut, "new_cases_smoothed"].clip(lower=0)
    if len(train_values) <= window:
        raise ValueError(f"Only {len(train_values)} training values are available; window={window} is too large.")
    scaler = StandardScaler().fit(np.log1p(train_values.to_numpy(dtype=np.float32)).reshape(-1, 1))
    locations = sorted(scope["location_code"].astype(str).unique().tolist())
    location_to_index = {code: index for index, code in enumerate(locations)}

    sequences: list[np.ndarray] = []
    location_indices: list[int] = []
    targets_scaled: list[float] = []
    targets_raw: list[float] = []
    baseline_raw: list[float] = []
    row_indices: list[int] = []
    dates: list[np.datetime64] = []

    for code, group in scope.groupby("location_code", sort=False):
        group = group.sort_values("date")
        values_raw = group["new_cases_smoothed"].clip(lower=0).to_numpy(dtype=np.float32)
        values_scaled = scaler.transform(np.log1p(values_raw).reshape(-1, 1)).astype(np.float32).ravel()
        target_values = group["target_t_plus_7"].to_numpy(dtype=np.float32)
        baseline_values = group["rolling_mean_7"].to_numpy(dtype=np.float32)
        group_indices = group.index.to_numpy(dtype=np.int64)
        group_dates = group["date"].to_numpy(dtype="datetime64[ns]")
        for position in range(window - 1, len(group)):
            target_raw = target_values[position]
            target_scaled = np.nan
            if np.isfinite(target_raw):
                target_scaled = float(
                    scaler.transform(np.log1p(np.asarray([[max(float(target_raw), 0.0)]], dtype=np.float32)))[0, 0]
                )
            sequences.append(values_scaled[position - window + 1 : position + 1, None])
            location_indices.append(location_to_index[str(code)])
            targets_scaled.append(target_scaled)
            targets_raw.append(float(target_raw))
            baseline_raw.append(float(baseline_values[position]))
            row_indices.append(int(group_indices[position]))
            dates.append(group_dates[position])

    x = np.asarray(sequences, dtype=np.float32)
    location_array = np.asarray(location_indices, dtype=np.int64)
    target_scaled_array = np.asarray(targets_scaled, dtype=np.float32).reshape(-1, 1)
    target_raw_array = np.asarray(targets_raw, dtype=np.float32)
    baseline_array = np.asarray(baseline_raw, dtype=np.float32)
    row_index_array = np.asarray(row_indices, dtype=np.int64)
    date_array = np.asarray(dates, dtype="datetime64[ns]")
    finite_target = np.isfinite(target_raw_array) & np.isfinite(target_scaled_array.ravel())
    train_mask = finite_target & (date_array <= np.datetime64(train_cut))
    validation_mask = finite_target & (date_array > np.datetime64(train_cut)) & (date_array <= np.datetime64(validation_cut))
    test_mask = finite_target & (date_array > np.datetime64(validation_cut))
    if train_mask.sum() == 0 or validation_mask.sum() == 0 or test_mask.sum() == 0:
        raise ValueError(
            "The time split produced an empty LSTM partition: "
            f"train={train_mask.sum()}, validation={validation_mask.sum()}, test={test_mask.sum()}"
        )
    return WindowBundle(
        x=x,
        location_indices=location_array,
        targets_scaled=target_scaled_array,
        targets_raw=target_raw_array,
        baseline_raw=baseline_array,
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


def train_lstm_forecaster(
    features: pd.DataFrame,
    *,
    model_output: str | Path,
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
    _set_seeds(seed)
    overall_started = time.perf_counter()
    print("[LSTM] Preparing real COVID-19 daily windows...", flush=True)
    bundle = prepare_windows(features, window=window)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(
        "[LSTM] Prepared "
        f"windows={len(bundle.x):,}, train={bundle.train_mask.sum():,}, "
        f"validation={bundle.validation_mask.sum():,}, test={bundle.test_mask.sum():,}, "
        f"locations={len(bundle.location_to_index)}, window={window}, device={device}",
        flush=True,
    )
    print(
        f"[LSTM] Time split: train <= {bundle.train_cut.date()}, "
        f"validation <= {bundle.validation_cut.date()}, test <= {bundle.max_date.date()}",
        flush=True,
    )

    train_loader = _make_loader(bundle, bundle.train_mask, batch_size=batch_size, shuffle=True)
    validation_loader = _make_loader(bundle, bundle.validation_mask, batch_size=batch_size, shuffle=False)
    model = LSTMRegressor(
        hidden_size=hidden_size,
        location_count=len(bundle.location_to_index),
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.SmoothL1Loss()
    best_state = copy.deepcopy(model.state_dict())
    best_validation_loss = float("inf")
    stale_epochs = 0
    epoch_durations: list[float] = []
    epochs_trained = 0

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
                    f"  [{_bar(batch_number, total_batches)}] epoch {epoch:02d}/{epochs:02d} "
                    f"batch {batch_number:03d}/{total_batches:03d} {percent:3d}% "
                    f"loss={running_loss / max(seen_rows, 1):.6f}",
                    flush=True,
                )

        train_loss = running_loss / max(seen_rows, 1)
        validation_loss = _evaluate_loss(model, validation_loader, loss_fn, device)
        elapsed = time.perf_counter() - epoch_started
        epoch_durations.append(elapsed)
        eta = (sum(epoch_durations) / len(epoch_durations)) * (epochs - epoch)
        improved = validation_loss < best_validation_loss - 1e-6
        marker = " best" if improved else ""
        print(
            f"[LSTM] Epoch {epoch:02d}/{epochs:02d} complete | "
            f"train_loss={train_loss:.6f} | val_loss={validation_loss:.6f} | "
            f"elapsed={_duration(elapsed)} | eta={_duration(eta)}{marker}",
            flush=True,
        )
        epochs_trained = epoch
        if improved:
            best_validation_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                print(
                    f"[LSTM] Early stopping after {epoch} epochs; validation loss did not improve for {patience} epochs.",
                    flush=True,
                )
                break

    model.load_state_dict(best_state)
    print("[LSTM] Generating predictions for all eligible windows...", flush=True)
    predicted_scaled = _predict_scaled(
        model,
        bundle.x,
        bundle.location_indices,
        batch_size=batch_size,
        device=device,
    )
    predicted_log = bundle.scaler.inverse_transform(predicted_scaled)
    predicted_raw = np.expm1(predicted_log).clip(min=0).ravel()
    prediction_series = pd.Series(np.nan, index=features.index, dtype=float)
    prediction_series.loc[bundle.row_indices] = predicted_raw

    test_predictions = predicted_raw[bundle.test_mask]
    test_actual = bundle.targets_raw[bundle.test_mask]
    test_baseline = bundle.baseline_raw[bundle.test_mask]
    model_metrics = regression_metrics(test_actual.tolist(), test_predictions.tolist())
    baseline_metrics = regression_metrics(test_actual.tolist(), test_baseline.tolist())
    model_path = Path(model_output)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_name": MODEL_NAME,
            "state_dict": model.state_dict(),
            "window": window,
            "hidden_size": hidden_size,
            "location_to_index": bundle.location_to_index,
            "scaler_mean": bundle.scaler.mean_.tolist(),
            "scaler_scale": bundle.scaler.scale_.tolist(),
            "forecast_horizon_days": 7,
            "trained_at": pd.Timestamp.utcnow().isoformat(),
        },
        model_path,
    )
    metrics = {
        "model": MODEL_NAME,
        "status": "trained",
        "framework": "PyTorch",
        "device": str(device),
        "forecast_horizon": 7,
        "window": window,
        "hidden_size": hidden_size,
        "epochs_requested": epochs,
        "epochs_trained": epochs_trained,
        "batch_size": batch_size,
        "train_start": bundle.min_date.date().isoformat(),
        "train_end": bundle.train_cut.date().isoformat(),
        "validation_end": bundle.validation_cut.date().isoformat(),
        "test_end": bundle.max_date.date().isoformat(),
        "train_rows": int(bundle.train_mask.sum()),
        "validation_rows": int(bundle.validation_mask.sum()),
        "test_rows": int(bundle.test_mask.sum()),
        **model_metrics,
        "baseline_mae": baseline_metrics["mae"],
        "beats_baseline": model_metrics["mae"] <= baseline_metrics["mae"],
        "model_path": str(model_path).replace("\\", "/"),
        "scope": "COVID-19 daily smoothed cases only",
        "note": "Past-window LSTM with location embedding; chronological split; no random split leakage.",
    }
    prediction_rows = pd.DataFrame(
        {
            "feature_index": bundle.row_indices,
            "date": pd.to_datetime(bundle.dates),
            "location_index": bundle.location_indices,
            "actual_t_plus_7": bundle.targets_raw,
            "moving_average": bundle.baseline_raw,
            "prediction": predicted_raw,
        }
    )
    prediction_rows["location_code"] = prediction_rows["location_index"].map(
        {value: key for key, value in bundle.location_to_index.items()}
    )
    prediction_rows["error"] = prediction_rows["prediction"] - prediction_rows["actual_t_plus_7"]
    print(
        f"[LSTM] Training complete in {_duration(time.perf_counter() - overall_started)} | "
        f"MAE={metrics['mae']:.4f} | RMSE={metrics['rmse']:.4f} | "
        f"baseline_MAE={metrics['baseline_mae']:.4f} | model={model_path}",
        flush=True,
    )
    return prediction_series, metrics, prediction_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the optional PyTorch LSTM on the real local Gold feature CSV.")
    parser.add_argument("--input", default="data/gold/local/forecast_features.csv")
    parser.add_argument("--model-output", default="data/models/local/local_pytorch_lstm.pt")
    parser.add_argument("--predictions-output", default="data/gold/local/lstm_predictions.csv")
    parser.add_argument("--metrics-output", default="data/serving/lstm_metrics.json")
    parser.add_argument("--window", type=int, default=28)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=5)
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
