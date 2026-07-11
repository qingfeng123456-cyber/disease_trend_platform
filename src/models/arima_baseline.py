from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.metrics import mean_absolute_error, mean_squared_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="含 date,new_cases 的 CSV")
    parser.add_argument("--output", default="data/serving/arima_result.json")
    parser.add_argument("--horizon", type=int, default=14)
    args = parser.parse_args()

    df = pd.read_csv(args.input, parse_dates=["date"])
    value_col = "new_cases" if "new_cases" in df.columns else "new_cases_nonnegative"
    series = (
        df[["date", value_col]]
        .dropna()
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")[value_col]
        .clip(lower=0)
        .asfreq("D")
        .interpolate(limit=3)
        .fillna(0)
    )
    if len(series) < 120:
        result = {
            "model": "SARIMAX",
            "status": "skipped",
            "reason": "ARIMA 至少建议 120 天数据，当前样本不足。",
            "sample_size": int(len(series)),
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    test_size = max(args.horizon, int(len(series) * 0.15))
    train, test = series.iloc[:-test_size], series.iloc[-test_size:]
    model = SARIMAX(
        np.log1p(train),
        order=(2, 1, 2),
        seasonal_order=(1, 0, 1, 7),
        enforce_stationarity=False,
        enforce_invertibility=False,
    ).fit(disp=False)
    forecast_log = model.get_forecast(steps=len(test)).predicted_mean
    forecast = np.expm1(forecast_log).clip(lower=0)

    result = {
        "model": "SARIMAX(2,1,2)x(1,0,1,7)",
        "mae": float(mean_absolute_error(test, forecast)),
        "rmse": float(mean_squared_error(test, forecast) ** 0.5),
        "test_start": str(test.index.min().date()),
        "test_end": str(test.index.max().date()),
        "points": [
            {"date": str(d.date()), "actual": float(a), "prediction": float(p)}
            for d, a, p in zip(test.index, test.values, forecast.values)
        ],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "points"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
