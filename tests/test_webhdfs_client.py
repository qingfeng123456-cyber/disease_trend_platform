from __future__ import annotations

from pathlib import Path

import src.remote.webhdfs_client as mod
from src.remote.webhdfs_client import WebHdfsClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_webhdfs_get_file_status(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        return FakeResponse(payload={"FileStatus": {"length": 123}})

    monkeypatch.setattr(mod.requests, "request", fake_request)
    status = WebHdfsClient("http://nn:9870", user="student").get_file_status("/x/y.csv")

    assert status["length"] == 123
    assert "op=GETFILESTATUS" in captured["url"]
    assert "user.name=student" in captured["url"]


def test_webhdfs_create_follows_redirect(monkeypatch, tmp_path):
    calls = []
    local = tmp_path / "data.txt"
    local.write_text("hello", encoding="utf-8")

    def fake_put(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return FakeResponse(status_code=307, headers={"Location": "http://dn:9864/upload"})
        return FakeResponse(status_code=201)

    monkeypatch.setattr(mod.requests, "put", fake_put)
    WebHdfsClient("http://nn:9870").create(local, "/data.txt", overwrite=True)

    assert calls[0].startswith("http://nn:9870/webhdfs/v1/data.txt")
    assert calls[1] == "http://dn:9864/upload"
