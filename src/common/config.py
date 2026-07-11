from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: str | Path | None = None) -> None:
    """加载简单 .env 文件，已存在的环境变量优先级更高。"""
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    """读取 YAML 配置，并返回字典。"""
    load_env_file()
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "settings.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误: {config_path}")
    return data


def get_setting(settings: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """按 a.b.c 形式读取配置，缺失时返回 default。"""
    current: Any = settings
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def require_keys(settings: dict[str, Any], keys: Iterable[str]) -> None:
    """校验配置项存在，方便启动时尽早暴露配置错误。"""
    missing = [key for key in keys if get_setting(settings, key) is None]
    if missing:
        raise KeyError(f"缺少必要配置项: {', '.join(missing)}")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p
