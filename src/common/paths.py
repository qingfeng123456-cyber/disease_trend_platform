from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_path(*parts: str | Path) -> Path:
    """返回项目内路径，避免业务代码依赖当前工作目录。"""
    path = Path(parts[0]) if parts else PROJECT_ROOT
    if len(parts) > 1:
        path = path.joinpath(*map(Path, parts[1:]))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def ensure_dir(path: str | Path) -> Path:
    """创建目录并返回绝对路径。"""
    resolved = project_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def safe_relative(path: str | Path) -> str:
    """对外展示相对路径，避免 API 暴露服务器绝对路径。"""
    resolved = project_path(path).resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return resolved.name


def serving_path(filename: str) -> Path:
    """返回 serving 层文件路径。"""
    return project_path("data", "serving", filename)
