from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - host dependency
    load_dotenv = None

from src.common.paths import project_path


SENSITIVE_KEYS = {"password", "passphrase", "key_passphrase", "remote_password", "remote_key_passphrase"}


def load_remote_config(config_path: str | Path, env_file: str | Path | None = None) -> dict[str, Any]:
    path = project_path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"远程配置文件不存在: {path}. 请复制 config/remote_cluster.example.yaml 为 config/remote_cluster.yaml 后填写。"
        )
    if env_file:
        env_path = project_path(env_file)
        if load_dotenv and env_path.exists():
            load_dotenv(env_path)

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"远程配置格式错误: {path}")

    remote = config.setdefault("remote", {})
    remote["password"] = os.environ.get("REMOTE_PASSWORD")
    remote["key_passphrase"] = os.environ.get("REMOTE_KEY_PASSPHRASE")
    return config


def sanitize_config(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                cleaned[key] = "***" if item else ""
            else:
                cleaned[key] = sanitize_config(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_config(item) for item in value]
    return value


def clone_without_secrets(config: dict[str, Any]) -> dict[str, Any]:
    return sanitize_config(deepcopy(config))


def get_nested(config: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
