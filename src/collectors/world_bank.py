from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.config import ensure_dir, load_settings
from src.common.http import get_with_retry

API = "https://api.worldbank.org/v2/country/all/indicator/{indicator}"
DEFAULT_INDICATORS = {
    "SP.POP.TOTL": "population",
    "SP.URB.TOTL.IN.ZS": "urban_population_percent",
    "NY.GDP.PCAP.CD": "gdp_per_capita_usd",
}


def fetch_indicator(indicator: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
    params = {
        "format": "json",
        "date": f"{start_year}:{end_year}",
        "per_page": 20000,
    }
    response = get_with_retry(API.format(indicator=indicator), params=params)
    payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise ValueError(f"World Bank 返回结构异常，指标={indicator}")
    return payload[1]


def collect(
    output_dir: str | Path | None = None,
    start_year: int = 2000,
    end_year: int = datetime.now().year,
) -> Path:
    settings = load_settings()
    target_dir = ensure_dir(output_dir or settings["paths"]["local_raw"]) / "world_bank"
    target_dir.mkdir(parents=True, exist_ok=True)

    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for indicator_code, output_name in DEFAULT_INDICATORS.items():
        rows = fetch_indicator(indicator_code, start_year, end_year)
        for row in rows:
            iso3 = row.get("countryiso3code")
            year_text = row.get("date")
            if not iso3 or not year_text or not str(year_text).isdigit():
                continue
            key = (iso3, int(year_text))
            record = by_key.setdefault(
                key,
                {
                    "iso_code": iso3,
                    "country_name": (row.get("country") or {}).get("value"),
                    "year": int(year_text),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            record[output_name] = row.get("value")

    output_path = target_dir / f"world_bank_{start_year}_{end_year}.csv"
    fieldnames = [
        "iso_code",
        "country_name",
        "year",
        *DEFAULT_INDICATORS.values(),
        "collected_at",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(by_key):
            writer.writerow(by_key[key])

    print(f"[World Bank] 已保存 {len(by_key)} 行: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    args = parser.parse_args()
    collect(args.output_dir, args.start_year, args.end_year)


if __name__ == "__main__":
    main()
