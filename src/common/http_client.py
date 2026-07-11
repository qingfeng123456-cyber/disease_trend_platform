from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from src.common.config import get_setting, load_settings


@dataclass(frozen=True)
class HttpClientConfig:
    timeout: int
    retries: int
    delay: float
    user_agent: str
    check_robots: bool = True


class HttpClient:
    """带 User-Agent、超时、重试、限速和 robots 检查的公开数据请求客户端。"""

    def __init__(self, config: HttpClientConfig | None = None):
        settings = load_settings()
        self.config = config or HttpClientConfig(
            timeout=int(get_setting(settings, "collectors.timeout", 60)),
            retries=int(get_setting(settings, "collectors.retry_count", 3)),
            delay=float(get_setting(settings, "collectors.request_interval", 1.5)),
            user_agent=str(get_setting(settings, "collectors.user_agent", "DiseaseTrendPlatform/1.0")),
        )
        self._robots_cache: dict[str, RobotFileParser] = {}

    def allowed_by_robots(self, url: str) -> bool:
        """检查 robots.txt；网络异常时保守放行 API/CSV 请求并记录在调用方日志中。"""
        if not self.config.check_robots:
            return True
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return True
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = self._robots_cache.get(robots_url)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
            except Exception:
                return True
            self._robots_cache[robots_url] = parser
        return parser.can_fetch(self.config.user_agent, url)

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        """执行 GET 请求，失败后指数退避重试。"""
        if not self.allowed_by_robots(url):
            raise RuntimeError(f"robots.txt 不允许采集: {url}")

        last_error: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.config.user_agent},
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.delay * attempt)
        raise RuntimeError(f"请求失败: {url}; 最后错误: {last_error}") from last_error


def save_bytes_with_metadata(
    content: bytes,
    output_path: Path,
    *,
    source_url: str,
    request_params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """保存原始文件和元信息，保证 raw 层可追溯。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    metadata = {
        "source_url": source_url,
        "request_params": request_params or {},
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        metadata.update(extra)
    output_path.with_suffix(output_path.suffix + ".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
