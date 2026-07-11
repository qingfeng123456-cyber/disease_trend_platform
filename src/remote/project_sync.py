from __future__ import annotations

import fnmatch
import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.common.paths import PROJECT_ROOT
from src.remote.ssh_client import SSHClient


DEFAULT_REQUIRED_PATHS = [
    "data/raw/kaggle/epidemic",
    "data/raw/kaggle/population",
    "data/raw/open_meteo",
    "config/country_name_mapping.csv",
    "config/weather_locations.csv",
]


@dataclass
class SyncStats:
    added_files: int = 0
    updated_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    uploaded_bytes: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added_files": self.added_files,
            "updated_files": self.updated_files,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "uploaded_bytes": self.uploaded_bytes,
            "errors": self.errors,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_relative(path: Path) -> str:
    return path.as_posix()


def should_exclude(relative_posix: str, patterns: Iterable[str]) -> bool:
    parts = relative_posix.split("/")
    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/").rstrip("/")
        if not normalized:
            continue
        if fnmatch.fnmatch(relative_posix, normalized) or fnmatch.fnmatch(posixpath.basename(relative_posix), normalized):
            return True
        if normalized in parts:
            return True
        if relative_posix == normalized or relative_posix.startswith(normalized + "/"):
            return True
    return False


def iter_project_files(
    root: Path = PROJECT_ROOT,
    *,
    exclude: Iterable[str] = (),
    upload_raw_data: bool = True,
) -> list[Path]:
    patterns = list(exclude)
    if not upload_raw_data:
        patterns.append("data/raw")
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = normalize_relative(path.relative_to(root))
        if should_exclude(relative, patterns):
            continue
        files.append(path)
    return sorted(files)


def remote_path_for(local_path: Path, remote_project_dir: str, root: Path = PROJECT_ROOT) -> str:
    relative = normalize_relative(local_path.relative_to(root))
    return posixpath.join(remote_project_dir.rstrip("/"), relative)


def remote_sha256(ssh: SSHClient, remote_path: str) -> str | None:
    quoted = "'" + remote_path.replace("'", "'\"'\"'") + "'"
    result = ssh.run(f"sha256sum {quoted}", check=False)
    if result.exit_code != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def file_needs_upload(
    ssh: SSHClient,
    local_path: Path,
    remote_path: str,
    *,
    checksum: bool = False,
    mtime_tolerance_seconds: int = 2,
) -> tuple[bool, bool]:
    """Return (needs_upload, existed_before)."""

    if not ssh.exists(remote_path):
        return True, False
    remote_stat = ssh.stat(remote_path)
    local_stat = local_path.stat()
    if checksum:
        return remote_sha256(ssh, remote_path) != sha256_file(local_path), True
    same_size = int(remote_stat.st_size) == int(local_stat.st_size)
    same_mtime = abs(int(remote_stat.st_mtime) - int(local_stat.st_mtime)) <= mtime_tolerance_seconds
    return not (same_size and same_mtime), True


def sync_project(
    ssh: SSHClient,
    *,
    remote_project_dir: str,
    local_root: Path = PROJECT_ROOT,
    exclude: Iterable[str] = (),
    upload_raw_data: bool = True,
    checksum: bool = False,
    dry_run: bool = False,
) -> SyncStats:
    stats = SyncStats()
    ssh.mkdir_p(remote_project_dir)
    files = iter_project_files(local_root, exclude=exclude, upload_raw_data=upload_raw_data)
    for local_path in files:
        remote_path = remote_path_for(local_path, remote_project_dir, local_root)
        try:
            needs_upload, existed = file_needs_upload(ssh, local_path, remote_path, checksum=checksum)
            if not needs_upload:
                stats.skipped_files += 1
                continue
            if dry_run:
                if existed:
                    stats.updated_files += 1
                else:
                    stats.added_files += 1
                stats.uploaded_bytes += local_path.stat().st_size
                continue
            ssh.upload_file(local_path, remote_path)
            # Keep remote mtime near local mtime for future size_mtime comparison.
            mtime = int(local_path.stat().st_mtime)
            quoted = "'" + remote_path.replace("'", "'\"'\"'") + "'"
            ssh.run(f"touch -m -d @{mtime} {quoted}", check=False)
            if existed:
                stats.updated_files += 1
            else:
                stats.added_files += 1
            stats.uploaded_bytes += local_path.stat().st_size
        except Exception as exc:  # noqa: BLE001 - keep syncing and report all failures
            stats.failed_files += 1
            stats.errors.append(f"{local_path}: {exc}")
    return stats


def check_required_local_paths(paths: Iterable[str] = DEFAULT_REQUIRED_PATHS) -> list[str]:
    missing = []
    for value in paths:
        if not (PROJECT_ROOT / value).exists():
            missing.append(value)
    return missing
