from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.remote.config import get_nested
from src.remote.remote_environment import RemoteEnvironment
from src.remote.ssh_client import SSHClient


HDFS_PROCESSES = {"NameNode", "DataNode"}
YARN_PROCESSES = {"ResourceManager", "NodeManager"}


@dataclass
class ClusterStatus:
    processes: set[str]
    hdfs_accessible: bool
    dfsadmin_report_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "processes": sorted(self.processes),
            "namenode_running": "NameNode" in self.processes,
            "datanode_running": "DataNode" in self.processes,
            "secondary_namenode_running": "SecondaryNameNode" in self.processes,
            "resourcemanager_running": "ResourceManager" in self.processes,
            "nodemanager_running": "NodeManager" in self.processes,
            "hdfs_accessible": self.hdfs_accessible,
            "dfsadmin_report_ok": self.dfsadmin_report_ok,
        }


def parse_jps(output: str) -> set[str]:
    processes: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            processes.add(parts[1])
    return processes


class ClusterManager:
    def __init__(self, ssh: SSHClient, env: RemoteEnvironment):
        self.ssh = ssh
        self.env = env

    def status(self) -> ClusterStatus:
        jps = self.ssh.run(self.env.bash_command("jps", cd_project=False), check=False)
        processes = parse_jps(jps.stdout)
        hdfs_ls = self.ssh.run(self.env.bash_command("hdfs dfs -ls /", cd_project=False), check=False)
        dfsadmin = self.ssh.run(self.env.bash_command("hdfs dfsadmin -report", cd_project=False), check=False)
        return ClusterStatus(processes, hdfs_ls.exit_code == 0, dfsadmin.exit_code == 0)

    def ensure_started(self, *, no_start_services: bool = False, with_yarn: bool = False) -> dict[str, Any]:
        before = self.status()
        actions: list[dict[str, Any]] = []

        if not before.hdfs_accessible and not no_start_services and get_nested(
            self.env.config, "bigdata.start_hdfs_when_missing", True
        ):
            result = self.ssh.run(self.env.bash_command("start-dfs.sh", cd_project=False), check=False)
            actions.append({"name": "start-dfs.sh", "exit_code": result.exit_code, "stderr": result.stderr})
            if result.exit_code != 0:
                raise RuntimeError(f"start-dfs.sh 失败: {result.stderr}")
        elif not before.hdfs_accessible and no_start_services:
            raise RuntimeError("HDFS 未运行，且指定了 --no-start-services。请先在 Ubuntu 启动 HDFS。")

        requested_yarn = with_yarn or bool(get_nested(self.env.config, "bigdata.start_yarn", False))
        if requested_yarn:
            current = self.status()
            if not YARN_PROCESSES.issubset(current.processes):
                result = self.ssh.run(self.env.bash_command("start-yarn.sh", cd_project=False), check=False)
                actions.append({"name": "start-yarn.sh", "exit_code": result.exit_code, "stderr": result.stderr})
                if result.exit_code != 0:
                    raise RuntimeError(f"start-yarn.sh 失败: {result.stderr}")
        else:
            actions.append({"name": "yarn", "exit_code": 0, "stderr": "local[*] 模式不要求 YARN，默认不启动。"})

        after = self.status()
        if not after.hdfs_accessible:
            raise RuntimeError("HDFS 仍不可访问。请检查 Safe Mode、NameNode/DataNode 状态和远程 stderr。")
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "before": before.to_dict(),
            "after": after.to_dict(),
            "actions": actions,
            "safeguard": "Never runs hdfs namenode -format.",
        }

    def init_hdfs_dirs(self) -> dict[str, Any]:
        result = self.ssh.run(self.env.bash_command("bash scripts/init_hdfs.sh"), check=True)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    def stop(self, *, with_yarn: bool = False) -> dict[str, Any]:
        command = "bash scripts/stop_bigdata_services.sh --with-yarn" if with_yarn else "bash scripts/stop_bigdata_services.sh"
        result = self.ssh.run(self.env.bash_command(command), check=False)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    def hdfs_tree(self, path: str) -> dict[str, Any]:
        result = self.ssh.run(self.env.bash_command(f"hdfs dfs -ls -R {path}", cd_project=False), check=False)
        return {"path": path, "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}


def status_to_json(status: dict[str, Any]) -> str:
    return json.dumps(status, ensure_ascii=False, indent=2)
