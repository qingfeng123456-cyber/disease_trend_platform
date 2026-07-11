from __future__ import annotations

from pathlib import Path

from src.remote.project_sync import remote_path_for, should_exclude


def test_remote_path_uses_posix_separators_with_chinese_and_spaces(tmp_path):
    root = tmp_path / "项目 根目录"
    local = root / "data" / "raw" / "测试 文件.csv"
    local.parent.mkdir(parents=True)
    local.write_text("x", encoding="utf-8")

    remote = remote_path_for(local, "/home/student/disease_trend_platform", root)
    assert remote == "/home/student/disease_trend_platform/data/raw/测试 文件.csv"
    assert "\\" not in remote


def test_sync_exclude_rules_match_dirs_and_globs():
    patterns = [".git", ".idea", "__pycache__", "*.pyc", "data/silver"]
    assert should_exclude(".git/config", patterns)
    assert should_exclude("src/__pycache__/x.pyc", patterns)
    assert should_exclude("src/mod.pyc", patterns)
    assert should_exclude("data/silver/epidemic/part.parquet", patterns)
    assert not should_exclude("data/raw/open_meteo/CHN/file.csv", patterns)
