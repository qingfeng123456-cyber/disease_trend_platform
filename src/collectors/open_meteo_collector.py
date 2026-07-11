from __future__ import annotations

import argparse
import csv
import json
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from src.collectors.base_collector import BaseCollector
from src.common.config import get_setting
from src.common.http_client import HttpClient, HttpClientConfig
from src.common.paths import project_path, safe_relative

ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_START_DATE = "2020-01-22"
DEFAULT_END_DATE = "2021-05-29"

DAILY_VARIABLE_MAP = OrderedDict(
    [
        ("temperature_2m_mean", "temperature_mean"),
        ("temperature_2m_max", "temperature_max"),
        ("temperature_2m_min", "temperature_min"),
        ("precipitation_sum", "precipitation_sum"),
        ("relative_humidity_2m_mean", "relative_humidity_mean"),
        ("wind_speed_10m_max", "wind_speed_max"),
    ]
)


def _is_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _split_codes(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    codes: set[str] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip().upper()
            if part:
                codes.add(part)
    return codes or None


class OpenMeteoCollector(BaseCollector):
    """Collect same-period daily weather data from the Open-Meteo archive API."""

    source_name = "open_meteo"

    def __init__(self, output_dir: str | Path | None = None):
        super().__init__(output_dir)
        self.client = HttpClient(
            HttpClientConfig(
                timeout=int(get_setting(self.settings, "collectors.timeout", 60)),
                retries=int(get_setting(self.settings, "collectors.retry_count", 3)),
                delay=float(get_setting(self.settings, "collectors.request_interval", 1.5)),
                user_agent=str(get_setting(self.settings, "collectors.user_agent", "DiseaseTrendPlatform/1.0")),
                check_robots=False,
            )
        )

    @staticmethod
    def year_chunks(start_date: str, end_date: str):
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if start > end:
            raise ValueError(f"start_date must be before end_date: {start_date} > {end_date}")
        for year in range(start.year, end.year + 1):
            yield max(start, date(year, 1, 1)).isoformat(), min(end, date(year, 12, 31)).isoformat(), year

    def read_locations(
        self,
        locations_file: str | Path | None = None,
        *,
        location_codes: set[str] | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, str]]:
        path = Path(locations_file) if locations_file else project_path("config", "weather_locations.csv")
        if not path.is_absolute():
            path = project_path(path)
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        selected: list[dict[str, str]] = []
        for row in rows:
            code = (row.get("location_code") or "").strip().upper()
            if not code:
                continue
            if location_codes and code not in location_codes:
                continue
            if not include_disabled and not _is_enabled(row.get("enabled")):
                continue
            row["location_code"] = code
            selected.append(row)
        return selected

    def is_complete(self, path: Path, params: dict[str, Any]) -> bool:
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        if not path.exists() or not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return meta.get("request_params") == params and int(meta.get("record_count") or 0) > 0

    def collect(
        self,
        *,
        locations_file: str | Path | None = None,
        location_codes: set[str] | None = None,
        limit: int | None = None,
        start_date: str = DEFAULT_START_DATE,
        end_date: str = DEFAULT_END_DATE,
    ) -> list[Path]:
        api = str(get_setting(self.settings, "collectors.open_meteo.archive_api", ARCHIVE_API))
        delay = float(get_setting(self.settings, "collectors.request_interval", 1.5))
        locations = self.read_locations(locations_file, location_codes=location_codes)
        if limit is not None:
            locations = locations[:limit]

        outputs: list[Path] = []
        for location in locations:
            code = location["location_code"]
            city = (location.get("representative_city") or "").strip()
            timezone = (location.get("timezone") or "UTC").strip() or "UTC"
            location_dir = self.output_dir / code
            location_dir.mkdir(parents=True, exist_ok=True)

            for chunk_start, chunk_end, year in self.year_chunks(start_date, end_date):
                params = {
                    "latitude": (location.get("latitude") or "").strip(),
                    "longitude": (location.get("longitude") or "").strip(),
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "daily": ",".join(DAILY_VARIABLE_MAP.keys()),
                    "timezone": timezone,
                }
                output_path = location_dir / f"open_meteo_{code}_{year}.csv"
                if self.is_complete(output_path, params):
                    self.logger.info("Open-Meteo complete file exists: %s", output_path)
                    outputs.append(output_path)
                    continue

                response = self.client.get(api, params=params)
                request_url = f"{api}?{urlencode(params)}"
                payload = response.json()
                daily = payload.get("daily") or {}
                daily_units = payload.get("daily_units") or {}
                days = daily.get("time") or []
                if not days:
                    self.logger.warning("Open-Meteo returned no daily data: %s %s", code, year)
                    continue

                now = self.utc_now()
                fieldnames = [
                    "date",
                    "location",
                    "location_code",
                    "representative_city",
                    "latitude",
                    "longitude",
                    "temperature_mean",
                    "temperature_max",
                    "temperature_min",
                    "precipitation_sum",
                    "relative_humidity_mean",
                    "wind_speed_max",
                    "source",
                    "source_timezone",
                    "downloaded_at",
                ]
                with output_path.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for i, day in enumerate(days):
                        row = {
                            "date": day,
                            "location": (location.get("location") or "").strip(),
                            "location_code": code,
                            "representative_city": city,
                            "latitude": params["latitude"],
                            "longitude": params["longitude"],
                            "source": "Open-Meteo archive API",
                            "source_timezone": timezone,
                            "downloaded_at": now,
                        }
                        for api_field, output_field in DAILY_VARIABLE_MAP.items():
                            values = daily.get(api_field) or [None] * len(days)
                            row[output_field] = values[i] if i < len(values) else None
                        writer.writerow(row)

                units = {
                    DAILY_VARIABLE_MAP.get(field, field): unit
                    for field, unit in daily_units.items()
                    if field != "time"
                }
                self.write_json(
                    output_path.with_suffix(output_path.suffix + ".meta.json"),
                    {
                        "source": "Open-Meteo archive API",
                        "source_url": api,
                        "request_url": request_url,
                        "request_params": params,
                        "downloaded_at": now,
                        "location": (location.get("location") or "").strip(),
                        "location_code": code,
                        "representative_city": city,
                        "latitude": params["latitude"],
                        "longitude": params["longitude"],
                        "start_date": chunk_start,
                        "end_date": chunk_end,
                        "record_count": len(days),
                        "fields": fieldnames,
                        "units": units,
                    },
                )
                outputs.append(output_path)
                self.logger.info("Open-Meteo saved: %s", safe_relative(output_path))
                time.sleep(delay)
        return outputs


def collect(output_dir: str | Path | None = None) -> list[Path]:
    return OpenMeteoCollector(output_dir).collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--locations-file", default=None)
    parser.add_argument("--location-codes", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    args = parser.parse_args()
    outputs = OpenMeteoCollector(args.output_dir).collect(
        locations_file=args.locations_file,
        location_codes=_split_codes(args.location_codes),
        limit=args.limit,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    for path in outputs:
        print(safe_relative(path))


if __name__ == "__main__":
    main()
