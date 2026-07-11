from __future__ import annotations

import argparse
import json
import logging
import posixpath
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.paths import project_path  # noqa: E402
from src.remote.cluster_manager import ClusterManager  # noqa: E402
from src.remote.config import clone_without_secrets, get_nested, load_remote_config  # noqa: E402
from src.remote.project_sync import check_required_local_paths, sync_project  # noqa: E402
from src.remote.remote_environment import RemoteEnvironment, check_remote_environment, remote_report_path  # noqa: E402
from src.remote.ssh_client import RemoteCommandError, SSHClient  # noqa: E402


REPORTS = [
    "hdfs_upload_manifest.json",
    "silver_pipeline_run.json",
    "silver_data_quality_report.json",
    "bigdata_environment_report.json",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logger() -> logging.Logger:
    log_dir = project_path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("remote_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_dir / "remote_pipeline.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def write_report(report: dict[str, Any]) -> None:
    output = project_path("data", "serving", "remote", "remote_pipeline_run.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def make_step(report: dict[str, Any], name: str, command: str | None = None) -> dict[str, Any]:
    step = {
        "name": name,
        "command": command,
        "started_at": utc_now(),
        "finished_at": None,
        "exit_code": None,
        "duration_seconds": None,
        "status": "running",
        "error": None,
    }
    report["steps"].append(step)
    write_report(report)
    return step


def finish_step(step: dict[str, Any], *, status: str, exit_code: int = 0, error: str | None = None) -> None:
    finished = datetime.now(timezone.utc)
    started = datetime.fromisoformat(step["started_at"])
    step["finished_at"] = finished.isoformat()
    step["duration_seconds"] = round((finished - started).total_seconds(), 3)
    step["exit_code"] = exit_code
    step["status"] = status
    step["error"] = error


def remote_output(line: str, stream: str) -> None:
    prefix = "[REMOTE]" if stream == "stdout" else "[REMOTE-ERR]"
    print(f"{prefix} {line}")


def connect_ssh(config: dict[str, Any]) -> SSHClient:
    remote = config["remote"]
    return SSHClient(
        host=remote["host"],
        port=int(remote.get("port", 22)),
        username=remote["username"],
        auth_method=remote.get("auth_method", "password"),
        password=remote.get("password"),
        key_file=remote.get("key_file") or None,
        key_passphrase=remote.get("key_passphrase") or None,
        allow_unknown_host=bool(remote.get("allow_unknown_host", False)),
        connect_timeout=int(remote.get("connect_timeout", 20)),
        command_timeout=int(remote.get("command_timeout", 1800)),
    )


def dry_run_plan(config: dict[str, Any], command: str, args: argparse.Namespace) -> dict[str, Any]:
    remote_dir = get_nested(config, "remote.project_dir")
    steps = ["load_config", "check_local_project"]
    if command in {"sync", "all"}:
        steps.append("sync_project_to_remote")
    if command in {"status", "all"}:
        steps.append("check_remote_environment")
    if command in {"start", "all"} and not args.no_start_services:
        steps.append("start_or_check_hdfs")
    if command in {"upload", "all"} and not args.no_upload_raw:
        steps.append("init_hdfs_and_upload_raw")
    if command in {"silver", "all"}:
        steps.append("run_remote_silver_pipeline")
    if command in {"download", "all"} and not args.no_download:
        steps.append("download_reports")
    return {
        "remote_project_dir": remote_dir,
        "steps": steps,
        "note": "dry-run only; no SSH connection is opened.",
    }


def run_remote_command(
    ssh: SSHClient,
    report: dict[str, Any],
    name: str,
    command: str,
    *,
    check: bool = True,
) -> None:
    step = make_step(report, name, command)
    try:
        result = ssh.run(command, check=check, output_callback=remote_output)
        finish_step(step, status="success", exit_code=result.exit_code)
    except RemoteCommandError as exc:
        finish_step(step, status="failed", exit_code=exc.exit_code or -1, error=str(exc))
        raise
    finally:
        write_report(report)


def run_sync(ssh: SSHClient, env: RemoteEnvironment, config: dict[str, Any], args: argparse.Namespace, report: dict[str, Any]) -> None:
    sync_cfg = config.get("sync", {})
    step = make_step(report, "sync_project", "SFTP project sync")
    try:
        stats = sync_project(
            ssh,
            remote_project_dir=env.project_dir,
            exclude=sync_cfg.get("exclude", []),
            upload_raw_data=bool(sync_cfg.get("upload_raw_data", True)) and not args.no_upload_raw,
            checksum=args.checksum,
            dry_run=args.dry_run,
        )
        step["sync_stats"] = stats.to_dict()
        report["uploaded_files"] = stats.added_files + stats.updated_files
        finish_step(step, status="success")
    except Exception as exc:
        finish_step(step, status="failed", exit_code=-1, error=str(exc))
        raise
    finally:
        write_report(report)


def run_status(ssh: SSHClient, env: RemoteEnvironment, report: dict[str, Any]) -> None:
    step = make_step(report, "remote_environment", "remote environment checks")
    try:
        env_report = check_remote_environment(ssh, env)
        step["environment_summary"] = env_report.get("summary", {})
        finish_step(step, status="success")
    except Exception as exc:
        finish_step(step, status="failed", exit_code=-1, error=str(exc))
        raise
    finally:
        write_report(report)


def run_start(ssh: SSHClient, env: RemoteEnvironment, args: argparse.Namespace, report: dict[str, Any]) -> ClusterManager:
    manager = ClusterManager(ssh, env)
    step = make_step(report, "start_or_check_services", "jps/start-dfs.sh/hdfs dfsadmin -report")
    try:
        status = manager.ensure_started(no_start_services=args.no_start_services, with_yarn=args.with_yarn)
        step["cluster_status"] = status
        finish_step(step, status="success")
    except Exception as exc:
        finish_step(step, status="failed", exit_code=-1, error=str(exc))
        raise
    finally:
        write_report(report)
    return manager


def run_upload(ssh: SSHClient, env: RemoteEnvironment, args: argparse.Namespace, report: dict[str, Any]) -> None:
    init_command = env.bash_command("bash scripts/init_hdfs.sh")
    run_remote_command(ssh, report, "init_hdfs", init_command)
    upload_args = ["scripts/upload_raw_to_hdfs.py", "--config", "config/settings.yaml", "--dataset", "all", "--verify"]
    if args.force:
        upload_args.append("--force")
    if args.dry_run:
        upload_args.append("--dry-run")
    run_remote_command(ssh, report, "upload_raw_to_hdfs", env.python(upload_args))


def run_remote_bigdata_environment_script(ssh: SSHClient, env: RemoteEnvironment, report: dict[str, Any]) -> None:
    run_remote_command(
        ssh,
        report,
        "remote_bigdata_environment_report",
        env.python(["scripts/check_bigdata_environment.py"]),
        check=False,
    )


def run_silver(ssh: SSHClient, env: RemoteEnvironment, report: dict[str, Any]) -> None:
    silver_command = env.python(
        [
            "scripts/run_silver_pipeline.py",
            "--config",
            "config/settings.yaml",
            "--master",
            env.spark_master,
        ]
    )
    run_remote_command(ssh, report, "run_silver_pipeline", silver_command)


def run_download(ssh: SSHClient, env: RemoteEnvironment, report: dict[str, Any]) -> None:
    local_dir = project_path("data", "serving", "remote")
    local_dir.mkdir(parents=True, exist_ok=True)
    step = make_step(report, "download_reports", "SFTP reports back to Windows")
    downloaded = []
    errors = []
    for filename in REPORTS:
        remote_path = remote_report_path(env.project_dir, filename)
        local_path = local_dir / filename
        try:
            if ssh.exists(remote_path):
                ssh.download_file(remote_path, local_path)
                downloaded.append(filename)
            else:
                errors.append(f"missing remote report: {remote_path}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{filename}: {exc}")
    step["downloaded_files"] = downloaded
    step["download_errors"] = errors
    report["downloaded_files"] = downloaded
    finish_step(step, status="success" if not errors else "partial", error="; ".join(errors) if errors else None)
    write_report(report)


def run_hdfs_checks(ssh: SSHClient, env: RemoteEnvironment, report: dict[str, Any]) -> None:
    raw_path = get_nested(env.config, "hdfs.raw_path", "/disease_platform/raw")
    silver_path = get_nested(env.config, "hdfs.silver_path", "/disease_platform/silver")
    for name, path in [("hdfs_raw_status", raw_path), ("hdfs_silver_status", silver_path)]:
        command = env.bash_command(f"hdfs dfs -ls -R {path}", cd_project=False)
        step = make_step(report, name, command)
        result = ssh.run(command, check=False, output_callback=remote_output)
        step["stdout_tail"] = result.stdout[-4000:]
        report[name] = {"exit_code": result.exit_code, "ok": result.exit_code == 0}
        finish_step(step, status="success" if result.exit_code == 0 else "failed", exit_code=result.exit_code)
        write_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Windows host controller for the Ubuntu raw-to-silver pipeline.")
    parser.add_argument("command", choices=["status", "sync", "start", "upload", "silver", "download", "all"])
    parser.add_argument("--config", default="config/remote_cluster.yaml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--checksum", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-start-services", action="store_true")
    parser.add_argument("--no-upload-raw", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--with-yarn", action="store_true")
    args = parser.parse_args()

    logger = setup_logger()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": utc_now(),
        "finished_at": None,
        "remote_host": None,
        "remote_project_dir": None,
        "steps": [],
        "uploaded_files": 0,
        "downloaded_files": [],
        "hdfs_raw_status": None,
        "hdfs_silver_status": None,
        "spark_job_status": None,
        "status": "running",
        "error": None,
    }
    write_report(report)

    try:
        config = load_remote_config(args.config, args.env_file)
        report["remote_host"] = get_nested(config, "remote.host")
        report["remote_project_dir"] = get_nested(config, "remote.project_dir")
        logger.info("loaded remote config: %s", json.dumps(clone_without_secrets(config), ensure_ascii=False))

        missing = check_required_local_paths()
        if missing:
            raise FileNotFoundError(f"本地缺少必要数据或配置: {missing}")

        if args.dry_run:
            step = make_step(report, "dry_run_plan", "no SSH connection")
            step["plan"] = dry_run_plan(config, args.command, args)
            finish_step(step, status="success")
            report["status"] = "dry_run"
            return

        env = RemoteEnvironment(config)
        with connect_ssh(config) as ssh:
            ssh.mkdir_p(env.project_dir)
            if args.command in {"status", "all"}:
                run_status(ssh, env, report)
            if args.command in {"sync", "all"}:
                run_sync(ssh, env, config, args, report)
            if args.command == "all":
                run_remote_bigdata_environment_script(ssh, env, report)
            if args.command in {"start", "all"}:
                run_start(ssh, env, args, report)
            if args.command in {"upload", "all"} and not args.no_upload_raw:
                run_upload(ssh, env, args, report)
                run_hdfs_checks(ssh, env, report)
            if args.command in {"silver", "all"}:
                run_silver(ssh, env, report)
                report["spark_job_status"] = "submitted"
                run_hdfs_checks(ssh, env, report)
            if args.command in {"download", "all"} and not args.no_download:
                run_download(ssh, env, report)
        report["status"] = "success"
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["error"] = str(exc)
        logger.exception("remote pipeline failed")
        print(f"[ERROR] {exc}")
        raise SystemExit(1) from exc
    finally:
        report["finished_at"] = utc_now()
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
