from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.common.config import PROJECT_ROOT, ensure_dir, load_settings
from src.common.http import get_with_retry, save_bytes_with_metadata

# OWID 旧 GitHub 仓库已停止维护，使用其当前数据目录地址。
OWID_COMPACT_CSV = (
    "https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv"
)


def collect(output_dir: str | Path | None = None) -> Path:
    settings = load_settings()
    target_dir = ensure_dir(output_dir or settings["paths"]["local_raw"])
    target_dir = target_dir / "owid"
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = target_dir / f"owid_covid_compact_{stamp}.csv"

    response = get_with_retry(
        OWID_COMPACT_CSV,
        timeout=settings["collection"]["request_timeout_seconds"],
        retries=settings["collection"]["retry_times"],
    )
    save_bytes_with_metadata(
        response.content,
        output_path,
        source_url=OWID_COMPACT_CSV,
        extra={"content_type": response.headers.get("Content-Type")},
    )
    print(f"[OWID] 已保存: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    collect(args.output_dir)


if __name__ == "__main__":
    main()
