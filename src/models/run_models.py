from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.collectors.generate_demo_data import main as generate_demo_data
from src.models.naive_baseline import run_baseline


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the real local clean-feature-train-serving pipeline. Demo mode must be requested explicitly."
    )
    parser.add_argument("--demo", action="store_true", help="Explicitly generate demo data and run only the demo baseline.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--lstm", action="store_true")
    parser.add_argument("--lstm-epochs", type=int, default=20)
    parser.add_argument("--lstm-window", type=int, default=28)
    parser.add_argument("--lstm-batch-size", type=int, default=128)
    parser.add_argument("--lstm-no-batch-progress", action="store_true")
    args = parser.parse_args()

    if args.demo:
        generate_demo_data()
        result = run_baseline(
            PROJECT_ROOT / "data" / "demo" / "epidemic_daily_demo.csv",
            PROJECT_ROOT / "data" / "serving" / "naive_baseline_metrics.json",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "build_local_serving_from_raw.py"),
        "--config",
        args.config,
    ]
    if args.lstm:
        command.extend(
            [
                "--lstm",
                "--lstm-epochs",
                str(args.lstm_epochs),
                "--lstm-window",
                str(args.lstm_window),
                "--lstm-batch-size",
                str(args.lstm_batch_size),
            ]
        )
        if args.lstm_no_batch_progress:
            command.append("--lstm-no-batch-progress")
    print("[MODEL RUNNER] Starting the real raw -> Silver -> Gold -> model -> serving pipeline.", flush=True)
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
