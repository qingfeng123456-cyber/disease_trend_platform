from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.models.metrics import regression_metrics


def run_baseline(input_csv: str | Path, output: str | Path, horizon: int = 7) -> dict:
    rows = list(csv.DictReader(Path(input_csv).open("r", encoding="utf-8-sig")))
    rows.sort(key=lambda row: (row.get("location_code", ""), row.get("disease", ""), row["date"]))
    actual, last_value, rolling = [], [], []
    for index, row in enumerate(rows):
        if index + horizon >= len(rows):
            continue
        same_series = (
            rows[index + horizon].get("location_code") == row.get("location_code")
            and rows[index + horizon].get("disease") == row.get("disease")
        )
        if not same_series:
            continue
        target = float(rows[index + horizon].get("new_cases_smoothed") or rows[index + horizon].get("new_cases_clean") or 0)
        current = float(row.get("new_cases_smoothed") or row.get("new_cases_clean") or 0)
        actual.append(target)
        last_value.append(current)
        rolling.append(current)
    result = {
        "horizon": horizon,
        "last_value": regression_metrics(actual, last_value),
        "rolling_7": regression_metrics(actual, rolling),
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/demo/epidemic_daily_demo.csv")
    parser.add_argument("--output", default="data/serving/naive_baseline_metrics.json")
    parser.add_argument("--horizon", type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(run_baseline(args.input, args.output, args.horizon), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
