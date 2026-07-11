from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from src.collectors.base_collector import BaseCollector
from src.common.config import get_setting


class WHOCollector(BaseCollector):
    """可扩展 WHO GHO OData 采集器，默认只在显式指定指标时运行。"""

    source_name = "who"

    def fetch_pages(self, indicator: str, *, page_size: int = 1000, max_pages: int = 20) -> list[dict[str, Any]]:
        base_url = str(get_setting(self.settings, "collectors.who.base_url", "https://ghoapi.azureedge.net/api"))
        rows: list[dict[str, Any]] = []
        for page in range(max_pages):
            params = {"$top": page_size, "$skip": page * page_size}
            response = self.client.get(f"{base_url}/{indicator}", params=params)
            payload = response.json()
            values = payload.get("value") or []
            rows.extend(values)
            if len(values) < page_size:
                break
        return rows

    @staticmethod
    def normalize(row: dict[str, Any], indicator: str) -> dict[str, Any]:
        return {
            "indicator": indicator,
            "location_code": row.get("SpatialDim"),
            "location": row.get("SpatialDimType"),
            "year": row.get("TimeDim"),
            "value": row.get("NumericValue") or row.get("Value"),
            "low": row.get("Low"),
            "high": row.get("High"),
            "raw_title": row.get("Title"),
        }

    def collect(self, *, indicators: list[str] | None = None, max_pages: int = 20) -> list[Path]:
        indicators = indicators or list(get_setting(self.settings, "collectors.who.indicators", []))
        if not indicators:
            self.logger.info("WHO 未配置指标，跳过。可使用 --indicators 指定。")
            return []
        outputs: list[Path] = []
        for indicator in indicators:
            rows = [self.normalize(row, indicator) for row in self.fetch_pages(indicator, max_pages=max_pages)]
            output_path = self.output_dir / f"who_{indicator}_{self.stamp()}.csv"
            with output_path.open("w", encoding="utf-8-sig", newline="") as f:
                fieldnames = ["indicator", "location_code", "location", "year", "value", "low", "high", "raw_title"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.write_json(
                output_path.with_suffix(output_path.suffix + ".meta.json"),
                {"indicator": indicator, "rows": len(rows), "collected_at": self.utc_now()},
            )
            outputs.append(output_path)
            self.logger.info("WHO 已保存 %s 行: %s", len(rows), output_path)
        return outputs


def collect(output_dir: str | Path | None = None) -> list[Path]:
    return WHOCollector(output_dir).collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--indicators", nargs="*", default=None)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    WHOCollector(args.output_dir).collect(indicators=args.indicators, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
