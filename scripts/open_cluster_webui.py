from __future__ import annotations

import argparse
import socket
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.remote.config import get_nested, load_remote_config  # noqa: E402


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Hadoop/Spark web UIs from Windows.")
    parser.add_argument("--config", default="config/remote_cluster.yaml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--include-spark-application", action="store_true")
    args = parser.parse_args()

    config = load_remote_config(args.config, args.env_file)
    host = str(get_nested(config, "remote.host"))
    ports = {
        "NameNode": int(get_nested(config, "web_ui.namenode_port", 9870)),
        "YARN": int(get_nested(config, "web_ui.yarn_port", 8088)),
        "Spark Master": int(get_nested(config, "web_ui.spark_master_port", 8080)),
    }
    if args.include_spark_application:
        ports["Spark Application"] = int(get_nested(config, "web_ui.spark_application_port", 4040))

    for name, port in ports.items():
        url = f"http://{host}:{port}"
        if port_open(host, port):
            opened = webbrowser.open(url)
            print(f"[OK] {name}: {url}; browser_open={opened}")
        else:
            print(f"[WARN] {name} port not reachable: {url}")
            print("       请检查虚拟机网络模式、防火墙、端口映射，或服务是否正在运行。")
            print(f"       SSH tunnel example: ssh -L {port}:localhost:{port} <user>@{host}")


if __name__ == "__main__":
    main()
