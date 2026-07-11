from __future__ import annotations

import json
import posixpath
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.paths import project_path
from src.remote.config import get_nested
from src.remote.ssh_client import SSHClient


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def safe_export(name: str, value: str | None) -> str | None:
    if not value:
        return None
    return f"export {name}={shlex.quote(value)}"


@dataclass
class RemoteEnvironment:
    config: dict[str, Any]

    @property
    def project_dir(self) -> str:
        return str(get_nested(self.config, "remote.project_dir"))

    @property
    def conda_executable(self) -> str:
        return str(get_nested(self.config, "remote.conda_executable", "conda"))

    @property
    def conda_env(self) -> str:
        return str(get_nested(self.config, "remote.conda_env", "base"))

    @property
    def spark_master(self) -> str:
        return str(get_nested(self.config, "bigdata.spark_master", "local[*]"))

    def env_prefix(self) -> str:
        exports = [
            safe_export("JAVA_HOME", get_nested(self.config, "bigdata.java_home", "")),
            safe_export("HADOOP_HOME", get_nested(self.config, "bigdata.hadoop_home", "")),
            safe_export("SPARK_HOME", get_nested(self.config, "bigdata.spark_home", "")),
            safe_export("HADOOP_CONF_DIR", get_nested(self.config, "bigdata.hadoop_conf_dir", "")),
        ]
        path_parts = []
        for base in [
            get_nested(self.config, "bigdata.java_home", ""),
            get_nested(self.config, "bigdata.hadoop_home", ""),
            get_nested(self.config, "bigdata.spark_home", ""),
        ]:
            if base:
                path_parts.extend([posixpath.join(str(base), "bin"), posixpath.join(str(base), "sbin")])
        if path_parts:
            exports.append(f"export PATH={shlex.quote(':'.join(path_parts))}:$PATH")
        return "; ".join(item for item in exports if item)

    def bash_command(self, command: str, *, cd_project: bool = True) -> str:
        parts = [self.env_prefix()]
        if cd_project:
            parts.append(f"cd {shlex.quote(self.project_dir)}")
        parts.append(command)
        joined = "; ".join(part for part in parts if part)
        return f"bash -lc {shlex.quote(joined)}"

    def conda_run(self, command_parts: list[str], *, cd_project: bool = True) -> str:
        command = shell_join([self.conda_executable, "run", "-n", self.conda_env, *command_parts])
        return self.bash_command(command, cd_project=cd_project)

    def python(self, script_and_args: list[str], *, cd_project: bool = True) -> str:
        return self.conda_run(["python", *script_and_args], cd_project=cd_project)

    def detect_python_path(self, ssh: SSHClient) -> str:
        result = ssh.run(self.conda_run(["which", "python"]), check=True)
        return result.stdout.strip().splitlines()[-1]

    def spark_submit(self, script_and_args: list[str], ssh: SSHClient | None = None) -> str:
        python_path = ""
        if ssh is not None:
            try:
                python_path = self.detect_python_path(ssh)
            except Exception:
                python_path = ""
        exports = []
        if python_path:
            exports.append(f"export PYSPARK_PYTHON={shlex.quote(python_path)}")
            exports.append(f"export PYSPARK_DRIVER_PYTHON={shlex.quote(python_path)}")
        command = shell_join(["spark-submit", "--master", self.spark_master, *script_and_args])
        if exports:
            command = "; ".join(exports + [command])
        return self.bash_command(command, cd_project=True)


def check_remote_environment(ssh: SSHClient, env: RemoteEnvironment) -> dict[str, Any]:
    commands = {
        "python3": "python3 --version",
        "java": "java -version",
        "hadoop": "hadoop version",
        "spark_submit": "spark-submit --version",
        "hdfs_default_fs": "hdfs getconf -confKey fs.defaultFS",
        "jps": "jps",
        "hostname_ip": "hostname -I",
        "disk": "df -h",
        "memory": "free -h",
        "which_java": "command -v java",
        "which_hadoop": "command -v hadoop",
        "which_hdfs": "command -v hdfs",
        "which_spark_submit": "command -v spark-submit",
        "which_start_dfs": "command -v start-dfs.sh",
        "which_jps": "command -v jps",
    }
    report: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    for name, command in commands.items():
        result = ssh.run(env.bash_command(command, cd_project=False), check=False)
        report["checks"][name] = {
            "command": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "ok": result.exit_code == 0,
        }
    report["summary"] = {
        "hdfs_available": report["checks"]["hdfs_default_fs"]["ok"],
        "spark_submit_available": report["checks"]["which_spark_submit"]["ok"],
        "jps_available": report["checks"]["which_jps"]["ok"],
    }
    output = project_path("data", "serving", "remote_environment_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def remote_report_path(remote_project_dir: str, filename: str) -> str:
    return posixpath.join(remote_project_dir.rstrip("/"), "data", "serving", filename)
