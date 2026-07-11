from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.config import get_setting, load_settings  # noqa: E402
from src.common.hdfs_cli import HdfsCli, HdfsCliError  # noqa: E402
from src.common.paths import project_path, safe_relative  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hdfs_join(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    return "/" + "/".join(cleaned)


def discover_files(settings: dict[str, Any], dataset: str) -> list[dict[str, Any]]:
    raw_path = str(get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"))
    items: list[dict[str, Any]] = []

    if dataset in {"all", "epidemic"}:
        local = project_path(get_setting(settings, "paths.epidemic_raw"))
        items.append(
            {
                "dataset": "epidemic",
                "local_path": local,
                "hdfs_path": hdfs_join(raw_path, "kaggle", "epidemic", "covid_19_data.csv"),
            }
        )

    if dataset in {"all", "population"}:
        local = project_path(get_setting(settings, "paths.population_raw"))
        items.append(
            {
                "dataset": "population",
                "local_path": local,
                "hdfs_path": hdfs_join(raw_path, "kaggle", "population", "world_population.csv"),
            }
        )

    if dataset in {"all", "weather"}:
        weather_root = project_path(get_setting(settings, "paths.weather_raw"))
        if weather_root.exists():
            for path in sorted(p for p in weather_root.rglob("*") if p.is_file()):
                relative = path.relative_to(weather_root).as_posix()
                items.append(
                    {
                        "dataset": "weather",
                        "local_path": path,
                        "hdfs_path": hdfs_join(raw_path, "open_meteo", relative),
                    }
                )
        else:
            items.append(
                {
                    "dataset": "weather",
                    "local_path": weather_root,
                    "hdfs_path": hdfs_join(raw_path, "open_meteo"),
                }
            )
    return items


def base_manifest_record(item: dict[str, Any]) -> dict[str, Any]:
    local_path = Path(item["local_path"])
    exists = local_path.is_file()
    return {
        "dataset": item["dataset"],
        "local_path": safe_relative(local_path),
        "hdfs_path": item["hdfs_path"],
        "local_size": local_path.stat().st_size if exists else None,
        "hdfs_size": None,
        "sha256": sha256_file(local_path) if exists else None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "status": "planned",
        "error": None,
    }


def upload_item(hdfs: HdfsCli, item: dict[str, Any], *, dry_run: bool, force: bool, verify: bool) -> dict[str, Any]:
    record = base_manifest_record(item)
    local_path = Path(item["local_path"])
    hdfs_path = str(item["hdfs_path"])

    if not local_path.is_file():
        record["status"] = "missing_local"
        record["error"] = f"本地文件不存在: {local_path}"
        return record

    if dry_run:
        record["status"] = "dry_run"
        return record

    try:
        existing_size = hdfs.file_size(hdfs_path) if hdfs.exists(hdfs_path) else None
        record["hdfs_size"] = existing_size
        if existing_size == record["local_size"] and not force:
            record["status"] = "skipped_same_size"
            return record
        if existing_size is not None and existing_size != record["local_size"] and not force:
            record["status"] = "exists_size_mismatch"
            record["error"] = "HDFS 已存在同名文件但大小不同；如确认覆盖请使用 --force。"
            return record

        hdfs.upload_file(local_path, hdfs_path, overwrite=force)
        uploaded_size = hdfs.file_size(hdfs_path)
        record["hdfs_size"] = uploaded_size
        if verify and uploaded_size != record["local_size"]:
            record["status"] = "verify_failed"
            record["error"] = f"上传后大小不一致: local={record['local_size']}, hdfs={uploaded_size}"
        else:
            record["status"] = "uploaded"
    except (HdfsCliError, OSError) as exc:
        record["status"] = "error"
        record["error"] = str(exc)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload raw project data to HDFS raw layer.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--dataset", choices=["all", "epidemic", "population", "weather"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    settings = load_settings(project_path(args.config))
    items = discover_files(settings, args.dataset)
    hdfs = HdfsCli()
    manifest_path = project_path("data", "serving", "hdfs_upload_manifest.json")

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": args.dataset,
        "dry_run": args.dry_run,
        "force": args.force,
        "verify": args.verify,
        "records": [],
    }

    if not args.dry_run:
        try:
            if not hdfs.is_available():
                raise HdfsCliError("HDFS 不可访问。请在 Ubuntu 中先执行 start-dfs.sh，并确认 hdfs dfs -ls / 成功。")
            for hdfs_dir in [
                get_setting(settings, "hdfs.base_path", "/disease_platform"),
                get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"),
                hdfs_join(get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"), "kaggle", "epidemic"),
                hdfs_join(get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"), "kaggle", "population"),
                hdfs_join(get_setting(settings, "hdfs.raw_path", "/disease_platform/raw"), "open_meteo"),
            ]:
                hdfs.mkdir(str(hdfs_dir))
        except HdfsCliError as exc:
            manifest["records"] = [base_manifest_record(item) for item in items]
            for record in manifest["records"]:
                record["status"] = "error"
                record["error"] = str(exc)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            raise SystemExit(1) from exc

    for item in items:
        manifest["records"].append(upload_item(hdfs, item, dry_run=args.dry_run, force=args.force, verify=args.verify))

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if any(record["status"] in {"error", "missing_local", "exists_size_mismatch", "verify_failed"} for record in manifest["records"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
