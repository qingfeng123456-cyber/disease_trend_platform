from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.open_meteo_collector import (  # noqa: E402
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    OpenMeteoCollector,
    _split_codes,
)
from src.common.paths import safe_relative  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download same-period daily weather data from Open-Meteo.")
    parser.add_argument("--locations-file", default=None, help="CSV path, defaults to config/weather_locations.csv.")
    parser.add_argument("--location-codes", nargs="*", default=None, help="ISO3 codes, e.g. CHN USA GBR.")
    parser.add_argument("--limit", type=int, default=None, help="Limit enabled locations after filtering.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-dir", default=None, help="Raw root directory; default is settings paths.raw.")
    args = parser.parse_args()

    collector = OpenMeteoCollector(args.output_dir)
    outputs = collector.collect(
        locations_file=args.locations_file,
        location_codes=_split_codes(args.location_codes),
        limit=args.limit,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(f"downloaded_files={len(outputs)}")
    for path in outputs:
        print(safe_relative(path))


if __name__ == "__main__":
    main()
