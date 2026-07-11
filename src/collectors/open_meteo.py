from __future__ import annotations

import argparse
import csv
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.common.config import PROJECT_ROOT, ensure_dir, load_settings
from src.common.http import get_with_retry

ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARIABLES = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
]


def _year_chunks(start_date: str, end_date: str):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, date(year, 1, 1))
        chunk_end = min(end, date(year, 12, 31))
        yield chunk_start.isoformat(), chunk_end.isoformat(), year


def collect(
    locations_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Path]:
    settings = load_settings()
    locations_path = Path(locations_file or PROJECT_ROOT / "config" / "locations.csv")
    locations = pd.read_csv(locations_path)

    start_date = start_date or settings["collection"]["weather_start_date"]
    end_date = end_date or settings["collection"]["weather_end_date"]
    target_dir = ensure_dir(output_dir or settings["paths"]["local_raw"]) / "open_meteo"
    target_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    for location in locations.to_dict(orient="records"):
        for chunk_start, chunk_end, year in _year_chunks(start_date, end_date):
            params = {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "start_date": chunk_start,
                "end_date": chunk_end,
                "daily": ",".join(DAILY_VARIABLES),
                "timezone": location["timezone"],
            }
            response = get_with_retry(
                ARCHIVE_API,
                params=params,
                timeout=settings["collection"]["request_timeout_seconds"],
                retries=settings["collection"]["retry_times"],
            )
            payload = response.json()
            daily = payload.get("daily") or {}
            dates = daily.get("time") or []
            if not dates:
                print(f"[Open-Meteo] 无数据: {location['iso_code']} {year}")
                continue

            output_path = target_dir / f"weather_{location['iso_code']}_{year}.csv"
            with output_path.open("w", encoding="utf-8-sig", newline="") as f:
                fieldnames = [
                    "iso_code",
                    "location_name",
                    "latitude",
                    "longitude",
                    "date",
                    *DAILY_VARIABLES,
                    "collected_at",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for i, day in enumerate(dates):
                    writer.writerow(
                        {
                            "iso_code": location["iso_code"],
                            "location_name": location["name"],
                            "latitude": location["latitude"],
                            "longitude": location["longitude"],
                            "date": day,
                            **{
                                variable: (daily.get(variable) or [None] * len(dates))[i]
                                for variable in DAILY_VARIABLES
                            },
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            outputs.append(output_path)
            print(f"[Open-Meteo] 已保存: {output_path}")
            time.sleep(float(settings["collection"]["polite_delay_seconds"]))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locations-file", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()
    collect(args.locations_file, args.output_dir, args.start_date, args.end_date)


if __name__ == "__main__":
    main()
