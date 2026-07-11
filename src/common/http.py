from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.http_client import HttpClient, save_bytes_with_metadata


def get_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 60,
    retries: int = 3,
    delay: float = 2.0,
) -> Any:
    client = HttpClient()
    object.__setattr__(client.config, "timeout", timeout)
    object.__setattr__(client.config, "retries", retries)
    object.__setattr__(client.config, "delay", delay)
    return client.get(url, params=params)
