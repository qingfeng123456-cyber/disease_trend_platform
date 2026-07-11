from __future__ import annotations

import argparse
import csv
from io import StringIO
from pathlib import Path

from src.collectors.base_collector import BaseCollector
from src.common.config import get_setting
from src.common.http_client import save_bytes_with_metadata


class OWIDCollector(BaseCollector):
    """采集 OWID 国家-日期级传染病数据目录中的 COVID-19 compact CSV。"""

    source_name = "owid"

    def collect(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        countries: list[str] | None = None,
    ) -> Path:
        url = str(get_setting(self.settings, "collectors.owid.url"))
        start_date = start_date or str(get_setting(self.settings, "collectors.start_date"))
        end_date = end_date or str(get_setting(self.settings, "collectors.end_date"))
        countries = countries or list(get_setting(self.settings, "collectors.countries", []))
        response = self.client.get(url)
        raw_path = self.output_dir / f"owid_compact_{self.stamp()}.csv"
        save_bytes_with_metadata(
            response.content,
            raw_path,
            source_url=url,
            extra={
                "content_type": response.headers.get("Content-Type"),
                "start_date": start_date,
                "end_date": end_date,
                "countries": countries,
            },
        )

        # 同步生成一个轻量字段报告，不假设公共字段永远存在。
        text = response.content.decode(response.encoding or "utf-8", errors="replace")
        reader = csv.DictReader(StringIO(text))
        available = reader.fieldnames or []
        required_candidates = [
            "date",
            "country",
            "location",
            "iso_code",
            "new_cases",
            "total_cases",
            "new_deaths",
            "total_deaths",
            "new_cases_smoothed",
            "population",
        ]
        report = {
            "source_url": url,
            "saved_file": raw_path.name,
            "available_columns": available,
            "expected_columns_present": [column for column in required_candidates if column in available],
            "collected_at": self.utc_now(),
        }
        self.write_json(raw_path.with_suffix(".columns.json"), report)
        self.logger.info("OWID 原始文件已保存: %s", raw_path)
        return raw_path


def collect(output_dir: str | Path | None = None) -> Path:
    return OWIDCollector(output_dir).collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--countries", nargs="*", default=None)
    args = parser.parse_args()
    OWIDCollector(args.output_dir).collect(
        start_date=args.start_date,
        end_date=args.end_date,
        countries=args.countries,
    )


if __name__ == "__main__":
    main()
