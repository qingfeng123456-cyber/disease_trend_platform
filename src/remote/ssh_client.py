from __future__ import annotations

import io
import posixpath
import socket
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:  # Paramiko is a Windows host dependency; tests can monkeypatch this symbol.
    import paramiko
except ImportError:  # pragma: no cover - depends on host environment
    paramiko = None  # type: ignore[assignment]


OutputCallback = Callable[[str, str], None]


class RemoteCommandError(RuntimeError):
    def __init__(self, command: str, exit_code: int | None, stdout: str, stderr: str):
        super().__init__(f"远程命令失败: exit_code={exit_code}; command={command}; stderr={stderr.strip()}")
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class RemoteConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteCommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class FingerprintConfirmPolicy:  # Paramiko base is attached dynamically to support missing dependency in tests.
    """Missing-host-key policy that prints the fingerprint before accepting."""

    def missing_host_key(self, client, hostname, key):  # noqa: ANN001
        fingerprint = ":".join(f"{byte:02x}" for byte in key.get_fingerprint())
        print(
            f"[SECURITY] Unknown SSH host key for {hostname}. Fingerprint: {fingerprint}. "
            "Only continue if this is your Ubuntu VM."
        )
        client.get_host_keys().add(hostname, key.get_name(), key)


class SSHClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        auth_method: str = "password",
        password: str | None = None,
        key_file: str | None = None,
        key_passphrase: str | None = None,
        allow_unknown_host: bool = False,
        connect_timeout: int = 20,
        command_timeout: int = 1800,
    ):
        self.host = host
        self.port = int(port)
        self.username = username
        self.auth_method = auth_method
        self.password = password
        self.key_file = key_file
        self.key_passphrase = key_passphrase
        self.allow_unknown_host = allow_unknown_host
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._client = None
        self._sftp = None

    def __enter__(self) -> "SSHClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def _require_paramiko(self):
        if paramiko is None:  # pragma: no cover - depends on host environment
            raise RemoteConnectionError("缺少 paramiko。请在 Windows Conda 环境执行: pip install -r requirements-host.txt")
        return paramiko

    def connect(self) -> None:
        pm = self._require_paramiko()
        client = pm.SSHClient()
        client.load_system_host_keys()
        if self.allow_unknown_host:
            client.set_missing_host_key_policy(FingerprintConfirmPolicy())
        else:
            client.set_missing_host_key_policy(pm.RejectPolicy())

        kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.connect_timeout,
            "banner_timeout": self.connect_timeout,
            "auth_timeout": self.connect_timeout,
            "look_for_keys": False,
        }
        if self.auth_method == "key":
            if not self.key_file:
                raise RemoteConnectionError("auth_method=key 但未配置 key_file。")
            kwargs["key_filename"] = self.key_file
            if self.key_passphrase:
                kwargs["passphrase"] = self.key_passphrase
        else:
            if self.password is None:
                raise RemoteConnectionError("auth_method=password 但未提供 REMOTE_PASSWORD。")
            kwargs["password"] = self.password

        try:
            client.connect(**kwargs)
        except (OSError, socket.timeout, Exception) as exc:  # Paramiko raises several subclasses.
            raise RemoteConnectionError(f"SSH 连接失败: host={self.host}, port={self.port}, user={self.username}; {exc}") from exc
        self._client = client

    @property
    def client(self):
        if self._client is None:
            raise RemoteConnectionError("SSH 尚未连接。")
        return self._client

    @property
    def sftp(self):
        if self._sftp is None:
            self._sftp = self.client.open_sftp()
        return self._sftp

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    def run(
        self,
        command: str,
        *,
        timeout: int | None = None,
        check: bool = True,
        output_callback: OutputCallback | None = None,
    ) -> RemoteCommandResult:
        start = time.monotonic()
        channel = self.client.get_transport().open_session()
        channel.set_combine_stderr(False)
        channel.exec_command(command)
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        stdout_pending = ""
        stderr_pending = ""
        deadline = start + float(timeout or self.command_timeout)

        try:
            while True:
                if time.monotonic() > deadline:
                    channel.close()
                    raise RemoteCommandError(command, None, stdout_buffer.getvalue(), "远程命令超时。")

                if channel.recv_ready():
                    data = channel.recv(4096).decode("utf-8", errors="replace")
                    stdout_buffer.write(data)
                    stdout_pending = self._emit_lines(stdout_pending + data, "stdout", output_callback)
                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                    stderr_buffer.write(data)
                    stderr_pending = self._emit_lines(stderr_pending + data, "stderr", output_callback)

                if channel.exit_status_ready():
                    while channel.recv_ready():
                        data = channel.recv(4096).decode("utf-8", errors="replace")
                        stdout_buffer.write(data)
                        stdout_pending = self._emit_lines(stdout_pending + data, "stdout", output_callback)
                    while channel.recv_stderr_ready():
                        data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                        stderr_buffer.write(data)
                        stderr_pending = self._emit_lines(stderr_pending + data, "stderr", output_callback)
                    if stdout_pending and output_callback:
                        output_callback(stdout_pending, "stdout")
                    if stderr_pending and output_callback:
                        output_callback(stderr_pending, "stderr")
                    exit_code = channel.recv_exit_status()
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            channel.close()
            raise
        finally:
            channel.close()

        duration = time.monotonic() - start
        result = RemoteCommandResult(command, exit_code, stdout_buffer.getvalue(), stderr_buffer.getvalue(), duration)
        if check and exit_code != 0:
            raise RemoteCommandError(command, exit_code, result.stdout, result.stderr)
        return result

    @staticmethod
    def _emit_lines(buffer: str, stream: str, callback: OutputCallback | None) -> str:
        if "\n" not in buffer:
            return buffer
        *lines, remainder = buffer.split("\n")
        if callback:
            for line in lines:
                callback(line, stream)
        return remainder

    def exists(self, remote_path: str) -> bool:
        try:
            self.sftp.stat(remote_path)
            return True
        except OSError:
            return False

    def is_dir(self, remote_path: str) -> bool:
        try:
            return stat.S_ISDIR(self.sftp.stat(remote_path).st_mode)
        except OSError:
            return False

    def mkdir_p(self, remote_dir: str) -> None:
        if remote_dir in {"", "/"}:
            return
        parts = remote_dir.strip("/").split("/")
        current = "/"
        for part in parts:
            current = posixpath.join(current, part)
            if not self.exists(current):
                self.sftp.mkdir(current)

    def upload_file(self, local_path: str | Path, remote_path: str) -> None:
        local = Path(local_path)
        self.mkdir_p(posixpath.dirname(remote_path))
        self.sftp.put(str(local), remote_path)

    def download_file(self, remote_path: str, local_path: str | Path) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        self.sftp.get(remote_path, str(local))

    def stat(self, remote_path: str):
        return self.sftp.stat(remote_path)

    def listdir(self, remote_path: str) -> list[str]:
        return self.sftp.listdir(remote_path)
