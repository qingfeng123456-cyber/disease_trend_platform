from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.config import get_setting, load_settings
from src.common.http_client import HttpClient
from src.common.logger import get_logger
from src.common.paths import ensure_dir


class BaseCollector:
    source_name = "base"

    def __init__(self, output_dir: str | Path | None = None):
        self.settings = load_settings()
        raw_root = output_dir or get_setting(self.settings, "paths.raw", "data/raw")
        self.output_dir = ensure_dir(Path(raw_root) / self.source_name)
        self.client = HttpClient()
        self.logger = get_logger(f"collectors.{self.source_name}")

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path
