from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


class WebHdfsError(RuntimeError):
    pass


class WebHdfsClient:
    """Minimal optional WebHDFS client.

    The default project path uses SFTP plus remote `hdfs dfs`. This class exists
    only for optional WebHDFS experiments and never submits Spark jobs.
    """

    def __init__(self, base_url: str, user: str | None = None, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.timeout = timeout

    def _url(self, hdfs_path: str, op: str) -> str:
        encoded = quote(hdfs_path.lstrip("/"))
        url = f"{self.base_url}/webhdfs/v1/{encoded}?op={op}"
        if self.user:
            url += f"&user.name={quote(self.user)}"
        return url

    def _request(self, method: str, hdfs_path: str, op: str, **kwargs) -> requests.Response:
        response = requests.request(
            method,
            self._url(hdfs_path, op),
            timeout=self.timeout,
            allow_redirects=True,
            **kwargs,
        )
        if response.status_code >= 400:
            raise WebHdfsError(f"WebHDFS {op} failed: {response.status_code} {response.text[:500]}")
        return response

    def get_file_status(self, hdfs_path: str) -> dict[str, Any]:
        return self._request("GET", hdfs_path, "GETFILESTATUS").json()["FileStatus"]

    def list_status(self, hdfs_path: str) -> list[dict[str, Any]]:
        return self._request("GET", hdfs_path, "LISTSTATUS").json()["FileStatuses"]["FileStatus"]

    def mkdirs(self, hdfs_path: str) -> bool:
        return bool(self._request("PUT", hdfs_path, "MKDIRS").json().get("boolean"))

    def create(self, local_path: str | Path, hdfs_path: str, overwrite: bool = False) -> None:
        url = self._url(hdfs_path, "CREATE") + f"&overwrite={'true' if overwrite else 'false'}"
        first = requests.put(url, timeout=self.timeout, allow_redirects=False)
        if first.status_code not in {201, 307}:
            raise WebHdfsError(f"WebHDFS CREATE failed: {first.status_code} {first.text[:500]}")
        upload_url = first.headers.get("Location", url)
        with Path(local_path).open("rb") as f:
            second = requests.put(upload_url, data=f, timeout=self.timeout, allow_redirects=True)
        if second.status_code >= 400:
            raise WebHdfsError(f"WebHDFS upload failed: {second.status_code} {second.text[:500]}")

    def open(self, hdfs_path: str) -> bytes:
        return self._request("GET", hdfs_path, "OPEN").content
