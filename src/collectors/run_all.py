from __future__ import annotations

import argparse

from src.collectors.china_cdc_collector import ChinaCDCCollector
from src.collectors.generate_demo_data import main as generate_demo_main
from src.collectors.open_meteo_collector import OpenMeteoCollector
from src.collectors.owid_collector import OWIDCollector
from src.collectors.who_collector import WHOCollector
from src.collectors.world_bank_collector import WorldBankCollector

COLLECTORS = {
    "owid": lambda: OWIDCollector().collect(),
    "world_bank": lambda: WorldBankCollector().collect(),
    "open_meteo": lambda: OpenMeteoCollector().collect(),
    "who": lambda: WHOCollector().collect(),
    "china_cdc": lambda: ChinaCDCCollector().collect(),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=COLLECTORS.keys(),
        default=["owid", "world_bank", "open_meteo", "who", "china_cdc"],
    )
    parser.add_argument("--demo", action="store_true", help="先生成本地演示数据")
    args = parser.parse_args()

    if args.demo:
        print("\n========== 生成演示数据 ==========")
        generate_demo_main()

    for source in args.sources:
        print(f"\n========== 采集 {source} ==========")
        try:
            COLLECTORS[source]()
        except Exception as exc:
            print(f"[WARN] {source} 采集失败，真实错误: {exc}")


if __name__ == "__main__":
    main()
