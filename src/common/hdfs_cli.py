from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class HdfsCliError(RuntimeError):
    """Raised when an HDFS CLI command fails."""


@dataclass(frozen=True)
class HdfsCommandResult:
    stage: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class HdfsCli:
    """Small safe wrapper around `hdfs dfs`.

    It deliberately uses Hadoop's configured CLI instead of an extra Python HDFS
    dependency, so the same code works on the Ubuntu VM used for the course.
    """

    def __init__(self, executable: str = "hdfs", timeout: int = 120):
        self.executable = executable
        self.timeout = timeout

    def which(self) -> str | None:
        return shutil.which(self.executable)

    def require_available(self) -> None:
        if self.which() is None:
            raise HdfsCliError("未找到 hdfs 命令。请在安装并配置 Hadoop 的 Ubuntu 环境中运行。")

    def run(self, args: Iterable[str], *, stage: str, check: bool = True) -> HdfsCommandResult:
        self.require_available()
        command = [self.executable, *list(args)]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        result = HdfsCommandResult(
            stage=stage,
            args=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        if check and result.returncode != 0:
            raise HdfsCliError(
                f"HDFS 命令失败: {stage}; returncode={result.returncode}; "
                f"stdout={result.stdout}; stderr={result.stderr}"
            )
        return result

    def get_default_fs(self) -> str | None:
        result = self.run(["getconf", "-confKey", "fs.defaultFS"], stage="get fs.defaultFS", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def is_available(self) -> bool:
        if self.which() is None:
            return False
        result = self.run(["dfs", "-ls", "/"], stage="check HDFS root", check=False)
        return result.returncode == 0

    def mkdir(self, hdfs_path: str) -> None:
        self.run(["dfs", "-mkdir", "-p", hdfs_path], stage=f"mkdir {hdfs_path}")

    def exists(self, hdfs_path: str) -> bool:
        result = self.run(["dfs", "-test", "-e", hdfs_path], stage=f"exists {hdfs_path}", check=False)
        return result.returncode == 0

    def delete(self, hdfs_path: str, *, recursive: bool = False, skip_trash: bool = False) -> None:
        args = ["dfs", "-rm"]
        if recursive:
            args.append("-r")
        if skip_trash:
            args.append("-skipTrash")
        args.append(hdfs_path)
        self.run(args, stage=f"delete {hdfs_path}")

    def file_size(self, hdfs_path: str) -> int | None:
        result = self.run(["dfs", "-stat", "%b", hdfs_path], stage=f"size {hdfs_path}", check=False)
        if result.returncode != 0 or not result.stdout:
            return None
        try:
            return int(result.stdout.strip().splitlines()[-1])
        except ValueError as exc:
            raise HdfsCliError(f"无法解析 HDFS 文件大小: {hdfs_path}; stdout={result.stdout}") from exc

    def list(self, hdfs_path: str, *, recursive: bool = False) -> list[str]:
        args = ["dfs", "-ls"]
        if recursive:
            args.append("-R")
        args.append(hdfs_path)
        result = self.run(args, stage=f"list {hdfs_path}", check=False)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    def upload_file(self, local_path: str | Path, hdfs_path: str, *, overwrite: bool = False) -> None:
        local = Path(local_path)
        if not local.is_file():
            raise FileNotFoundError(f"本地文件不存在: {local}")
        parent = hdfs_path.rsplit("/", 1)[0] or "/"
        self.mkdir(parent)
        args = ["dfs", "-put"]
        if overwrite:
            args.append("-f")
        args.extend([str(local), hdfs_path])
        self.run(args, stage=f"upload file {local} -> {hdfs_path}")

    def upload_directory(self, local_dir: str | Path, hdfs_dir: str, *, overwrite: bool = False) -> None:
        local = Path(local_dir)
        if not local.is_dir():
            raise NotADirectoryError(f"本地目录不存在: {local}")
        self.mkdir(hdfs_dir)
        for path in sorted(p for p in local.rglob("*") if p.is_file()):
            relative = path.relative_to(local).as_posix()
            self.upload_file(path, f"{hdfs_dir.rstrip('/')}/{relative}", overwrite=overwrite)

    def download_file(self, hdfs_path: str, local_path: str | Path, *, overwrite: bool = False) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        args = ["dfs", "-get"]
        if overwrite:
            args.append("-f")
        args.extend([hdfs_path, str(local)])
        self.run(args, stage=f"download {hdfs_path} -> {local}")
