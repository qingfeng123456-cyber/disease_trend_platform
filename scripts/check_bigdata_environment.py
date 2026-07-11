from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.paths import project_path  # noqa: E402


def run_command(args: list[str], timeout: int = 30) -> dict[str, Any]:
    executable = shutil.which(args[0])
    if executable is None:
        return {
            "command": args,
            "available": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"未找到命令: {args[0]}",
        }
    completed = subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": args,
        "available": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def first_line(value: str) -> str:
    return value.splitlines()[0] if value else ""


def command_ok(result: dict[str, Any]) -> bool:
    return bool(result["available"]) and result["returncode"] == 0


def main() -> None:
    checks: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "executable": sys.executable,
            "version": sys.version.replace("\n", " "),
        },
    }

    commands = {
        "java": ["java", "-version"],
        "hadoop": ["hadoop", "version"],
        "hdfs": ["hdfs", "version"],
        "spark_submit": ["spark-submit", "--version"],
        "jps": ["jps"],
        "fs_default_fs": ["hdfs", "getconf", "-confKey", "fs.defaultFS"],
        "hdfs_root": ["hdfs", "dfs", "-ls", "/"],
    }
    for name, command in commands.items():
        checks[name] = run_command(command)

    jps_output = checks["jps"]["stdout"] if command_ok(checks["jps"]) else ""
    running_processes = set()
    for line in jps_output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            running_processes.add(parts[1])

    hdfs_accessible = command_ok(checks["hdfs_root"])
    checks["services"] = {
        "namenode_running": "NameNode" in running_processes,
        "datanode_running": "DataNode" in running_processes,
        "resourcemanager_running": "ResourceManager" in running_processes,
        "nodemanager_running": "NodeManager" in running_processes,
        "hdfs_accessible": hdfs_accessible,
        "fs_default_fs": checks["fs_default_fs"]["stdout"] if command_ok(checks["fs_default_fs"]) else None,
    }

    checks["advice"] = []
    if not command_ok(checks["hdfs"]):
        checks["advice"].append("未检测到 hdfs 命令：请在安装 Hadoop 且配置 PATH 的 Ubuntu 中运行 HDFS 步骤。")
    elif not hdfs_accessible:
        checks["advice"].append("HDFS 当前不可访问。如 Hadoop 已安装，请先执行 start-dfs.sh。")
    if command_ok(checks["hdfs"]) and not checks["services"]["namenode_running"]:
        checks["advice"].append("NameNode 未在 jps 中出现。如未启动 HDFS，请执行 start-dfs.sh。")
    if command_ok(checks["hdfs"]) and not checks["services"]["datanode_running"]:
        checks["advice"].append("DataNode 未在 jps 中出现。如未启动 HDFS，请执行 start-dfs.sh。")
    if command_ok(checks["spark_submit"]):
        checks["advice"].append("使用 Spark local[*] 模式时，不需要提前启动 Spark 服务；spark-submit 会在任务运行时启动 Spark 作业。")
    if command_ok(checks["spark_submit"]) and not checks["services"]["resourcemanager_running"]:
        checks["advice"].append("如准备使用 YARN 模式，再执行 start-yarn.sh；local[*] 模式不需要 YARN。")
    checks["forbidden_operations"] = ["绝不自动执行 hdfs namenode -format。"]

    report_path = project_path("data", "serving", "bigdata_environment_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")

    print("大数据环境检查报告")
    print(f"- 操作系统: {checks['os']['system']} {checks['os']['release']}")
    print(f"- Python: {checks['python']['version'].split()[0]}")
    for key in ["java", "hadoop", "hdfs", "spark_submit", "jps"]:
        result = checks[key]
        status = "可用" if command_ok(result) else "不可用"
        detail = first_line(result["stdout"] or result["stderr"])
        print(f"- {key}: {status} {detail}")
    print(f"- fs.defaultFS: {checks['services']['fs_default_fs']}")
    print(f"- NameNode: {checks['services']['namenode_running']}")
    print(f"- DataNode: {checks['services']['datanode_running']}")
    print(f"- ResourceManager: {checks['services']['resourcemanager_running']}")
    print(f"- NodeManager: {checks['services']['nodemanager_running']}")
    print(f"- HDFS 可访问: {checks['services']['hdfs_accessible']}")
    for item in checks["advice"]:
        print(f"- 提示: {item}")
    print(f"- JSON 报告: {report_path}")


if __name__ == "__main__":
    main()
