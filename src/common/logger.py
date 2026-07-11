from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

import yaml

from src.common.paths import PROJECT_ROOT, ensure_dir


def setup_logging(config_path: str | Path | None = None) -> None:
    """初始化日志配置，采集、Spark、模型和 Web 共用同一套格式。"""
    ensure_dir("logs")
    path = Path(config_path) if config_path else PROJECT_ROOT / "config" / "logging.yaml"
    if path.exists():
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        logging.config.dictConfig(data)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        )


def get_logger(name: str) -> logging.Logger:
    """返回命名 logger，首次调用时自动加载配置。"""
    if not logging.getLogger().handlers:
        setup_logging()
    return logging.getLogger(name)
