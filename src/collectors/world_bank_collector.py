from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from src.collectors.base_collector import BaseCollector
from src.common.config import get_setting

API = "https://api.worldbank.org/v2/country/all/indicator/{indicator}"


class WorldBankCollector(BaseCollector):
    """采集 World Bank 年度人口、城市化和 GDP 指标。"""

    source_name = "world_bank"

    def fetch_indicator(self, indicator: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
        params = {"format": "json", "date": f"{start_year}:{end_year}", "per_page": 20000}
        response = self.client.get(API.format(indicator=indicator), params=params)
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            raise RuntimeError(f"World Bank 返回结构异常: {indicator}")
        return payload[1]

    def collect(self, *, start_year: int | None = None, end_year: int | None = None) -> Path:
        indicators = dict(get_setting(self.settings, "collectors.world_bank.indicators", {}))
        start_year = start_year or int(get_setting(self.settings, "collectors.world_bank.start_year", 2020))
        end_year = end_year or int(get_setting(self.settings, "collectors.world_bank.end_year", 2025))
        by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for indicator_code, output_name in indicators.items():
            for row in self.fetch_indicator(indicator_code, start_year, end_year):
                code = row.get("countryiso3code")
                year_text = row.get("date")
                if not code or not str(year_text).isdigit():
                    continue
                key = (code, int(year_text))
                record = by_key.setdefault(
                    key,
                    {
                        "location_code": code,
                        "location": (row.get("country") or {}).get("value"),
                        "year": int(year_text),
                        "source": "World Bank",
                        "collected_at": self.utc_now(),
                    },
                )
                record[str(output_name)] = row.get("value")
        output_path = self.output_dir / f"world_bank_{start_year}_{end_year}.csv"
        fieldnames = ["location_code", "location", "year", *indicators.values(), "source", "collected_at"]
        with output_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for key in sorted(by_key):
                writer.writerow(by_key[key])
        self.write_json(
            output_path.with_suffix(output_path.suffix + ".meta.json"),
            {"indicators": indicators, "start_year": start_year, "end_year": end_year, "collected_at": self.utc_now()},
        )
        self.logger.info("World Bank 已保存 %s 行: %s", len(by_key), output_path)
        return output_path


def collect(output_dir: str | Path | None = None) -> Path:
    return WorldBankCollector(output_dir).collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    args = parser.parse_args()
    WorldBankCollector(args.output_dir).collect(start_year=args.start_year, end_year=args.end_year)


if __name__ == "__main__":
    main()
