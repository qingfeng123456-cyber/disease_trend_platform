from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.config import load_settings  # noqa: E402
from src.common.hdfs_cli import HdfsCli, HdfsCliError  # noqa: E402
from src.common.paths import project_path  # noqa: E402
from src.spark_jobs.spark_session import resolve_hdfs_paths  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(command: list[str], name: str) -> dict[str, Any]:
    started_at = utc_now()
    env = os.environ.copy()
    env.setdefault("PYSPARK_PYTHON", sys.executable)
    env.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    ended_at = utc_now()
    return {
        "name": name,
        "command": command,
        "started_at": started_at,
        "ended_at": ended_at,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "success" if completed.returncode == 0 else "failed",
    }


def write_run_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Silver Spark cleaning pipeline with spark-submit.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--master", default="local[*]")
    parser.add_argument("--skip-epidemic", action="store_true")
    parser.add_argument("--skip-population", action="store_true")
    parser.add_argument("--skip-weather", action="store_true")
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    paths = resolve_hdfs_paths(settings)
    output_path = project_path("data", "serving", "silver_pipeline_run.json")
    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "config": args.config,
        "master": args.master,
        "dry_run": args.dry_run,
        "status": "planned",
        "steps": [],
        "error": None,
    }

    spark_submit = shutil.which("spark-submit")
    if spark_submit is None:
        if args.dry_run:
            spark_submit = "spark-submit"
        else:
            report["status"] = "failed"
            report["error"] = "未找到 spark-submit。请在安装 Spark 并配置 PATH 的 Ubuntu 环境中运行。"
            write_run_report(output_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(1)

    hdfs = HdfsCli()
    if not args.dry_run:
        try:
            if not hdfs.is_available():
                raise HdfsCliError("HDFS 不可访问。请先执行 start-dfs.sh，并确认 hdfs dfs -ls / 成功。")
            required_paths = [paths["epidemic_raw"], paths["population_raw"], paths["weather_raw"]]
            missing = [path for path in required_paths if not hdfs.exists(path.replace("hdfs://", ""))]
            if missing:
                raise HdfsCliError(f"HDFS raw 输入不存在: {missing}")
        except HdfsCliError as exc:
            report["status"] = "failed"
            report["error"] = str(exc)
            write_run_report(output_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(1) from exc

    jobs: list[tuple[str, str]] = []
    if not args.skip_epidemic:
        jobs.append(("clean_epidemic", "src/spark_jobs/clean_epidemic.py"))
    if not args.skip_population:
        jobs.append(("clean_population", "src/spark_jobs/clean_population.py"))
    if not args.skip_weather:
        jobs.append(("clean_weather", "src/spark_jobs/clean_weather.py"))
    if not args.skip_quality:
        jobs.append(("data_quality_report", "src/spark_jobs/data_quality_report.py"))

    for name, script in jobs:
        command = [
            spark_submit,
            "--master",
            args.master,
            script,
            "--config",
            args.config,
            "--master",
            args.master,
        ]
        if args.dry_run:
            report["steps"].append(
                {
                    "name": name,
                    "command": command,
                    "started_at": None,
                    "ended_at": None,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                    "status": "dry_run",
                }
            )
            continue
        step = run_step(command, name)
        report["steps"].append(step)
        write_run_report(output_path, report)
        if step["returncode"] != 0:
            report["status"] = "failed"
            report["error"] = f"作业失败: {name}"
            write_run_report(output_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(step["returncode"])

    report["status"] = "dry_run" if args.dry_run else "success"
    write_run_report(output_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
