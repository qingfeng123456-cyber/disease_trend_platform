from __future__ import annotations

import subprocess

from src.common.hdfs_cli import HdfsCli


class DummyCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_hdfs_cli_uses_argument_list(monkeypatch):
    captured = {}

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hdfs")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyCompleted(stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = HdfsCli().run(["dfs", "-ls", "/disease_platform"], stage="list")

    assert result.stdout == "ok"
    assert captured["args"] == ["hdfs", "dfs", "-ls", "/disease_platform"]
    assert captured["kwargs"]["shell"] is False if "shell" in captured["kwargs"] else True
    assert captured["kwargs"]["capture_output"] is True


def test_hdfs_exists_returns_false_on_nonzero(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hdfs")
    monkeypatch.setattr(subprocess, "run", lambda *_, **__: DummyCompleted(returncode=1, stderr="missing"))

    assert HdfsCli().exists("/not_found") is False
