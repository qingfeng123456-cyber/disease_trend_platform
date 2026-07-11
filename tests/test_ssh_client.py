from __future__ import annotations

import pytest

from src.remote import ssh_client as ssh_mod
from src.remote.ssh_client import RemoteCommandError, SSHClient


class FakeRejectPolicy:
    pass


class FakeParamikoClient:
    last_kwargs = None

    def load_system_host_keys(self):
        self.loaded = True

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        FakeParamikoClient.last_kwargs = kwargs

    def close(self):
        self.closed = True


class FakeParamiko:
    SSHClient = FakeParamikoClient
    RejectPolicy = FakeRejectPolicy


def test_ssh_client_uses_password_auth_without_logging_secret(monkeypatch):
    monkeypatch.setattr(ssh_mod, "paramiko", FakeParamiko)
    client = SSHClient(
        host="192.168.1.100",
        port=22,
        username="student",
        auth_method="password",
        password="super-secret",
    )
    client.connect()

    assert FakeParamikoClient.last_kwargs["password"] == "super-secret"
    assert FakeParamikoClient.last_kwargs["hostname"] == "192.168.1.100"
    assert "super-secret" not in repr(client)


def test_remote_command_error_keeps_exit_code():
    error = RemoteCommandError("false", 1, "", "boom")
    assert error.exit_code == 1
    assert "boom" in str(error)


def test_password_auth_requires_password(monkeypatch):
    monkeypatch.setattr(ssh_mod, "paramiko", FakeParamiko)
    client = SSHClient(host="h", port=22, username="u", auth_method="password")
    with pytest.raises(Exception):
        client.connect()
