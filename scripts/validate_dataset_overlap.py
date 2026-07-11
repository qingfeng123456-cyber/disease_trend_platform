from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EPIDEMIC_PATH = Path("data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv")
POPULATION_PATH = Path("data/raw/kaggle/population/world-population-dataset/world_population.csv")
MAPPING_PATH = Path("config/country_name_mapping.csv")
WEATHER_ROOT = Path("data/raw/open_meteo")


def project_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_date(value: str) -> str | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def load_mapping(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {(row.get("epidemic_name") or "").strip(): row for row in rows}


def profile_epidemic(path: Path) -> dict[str, Any]:
    countries: set[str] = set()
    dates: set[str] = set()
    parse_errors = 0
    full_row_seen: set[tuple[str, ...]] = set()
    full_duplicate_rows = 0
    key_counts: Counter[tuple[str, str, str]] = Counter()
    country_date = defaultdict(lambda: {"rows": 0, "blank_province": 0, "nonblank_province": 0})

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        for row in reader:
            country = (row.get("Country/Region") or "").strip()
            province = (row.get("Province/State") or "").strip()
            parsed_date = parse_date(row.get("ObservationDate") or "")
            if parsed_date is None:
                parse_errors += 1
                continue
            countries.add(country)
            dates.add(parsed_date)
            if province:
                country_date[(country, parsed_date)]["nonblank_province"] += 1
            else:
                country_date[(country, parsed_date)]["blank_province"] += 1
            country_date[(country, parsed_date)]["rows"] += 1
            key_counts[(country, parsed_date, province)] += 1
            signature = tuple(row.get(column, "") for column in columns)
            if signature in full_row_seen:
                full_duplicate_rows += 1
            full_row_seen.add(signature)

    duplicate_country_date_province = {key: count for key, count in key_counts.items() if count > 1}
    blank_plus_province = {
        key: value
        for key, value in country_date.items()
        if value["blank_province"] > 0 and value["nonblank_province"] > 0
    }
    multi_province_dates = {
        key: value
        for key, value in country_date.items()
        if value["nonblank_province"] > 1
    }
    return {
        "countries": countries,
        "dates": dates,
        "date_range": [min(dates), max(dates)] if dates else [None, None],
        "date_count": len(dates),
        "date_parse_errors": parse_errors,
        "full_duplicate_rows": full_duplicate_rows,
        "duplicate_country_date_province_key_count": len(duplicate_country_date_province),
        "duplicate_country_date_province_examples": [
            {"country": k[0], "date": k[1], "province": k[2], "count": v}
            for k, v in list(duplicate_country_date_province.items())[:10]
        ],
        "country_date_with_multiple_province_rows": len(multi_province_dates),
        "country_date_with_blank_and_province_rows": len(blank_plus_province),
        "blank_plus_province_examples": [
            {
                "country": k[0],
                "date": k[1],
                "rows": v["rows"],
                "blank_province": v["blank_province"],
                "nonblank_province": v["nonblank_province"],
            }
            for k, v in list(blank_plus_province.items())[:10]
        ],
    }


def profile_population(path: Path) -> dict[str, Any]:
    codes: set[str] = set()
    duplicate_codes: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("CCA3") or "").strip().upper()
            if not code:
                continue
            if code in codes:
                duplicate_codes.add(code)
            codes.add(code)
    return {"codes": codes, "duplicate_codes": sorted(duplicate_codes)}


def profile_weather(root: Path) -> dict[str, Any]:
    files = sorted(root.glob("*/*.csv")) if root.exists() else []
    by_code: dict[str, set[str]] = defaultdict(set)
    rows_by_code: Counter[str] = Counter()
    duplicate_keys: Counter[tuple[str, str]] = Counter()
    parse_errors = 0
    fields_by_code: dict[str, list[str]] = {}
    ranges_by_code: dict[str, list[str | None]] = {}

    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            for row in reader:
                code = (row.get("location_code") or "").strip().upper()
                parsed_date = parse_date(row.get("date") or "")
                if not code or parsed_date is None:
                    parse_errors += 1
                    continue
                by_code[code].add(parsed_date)
                rows_by_code[code] += 1
                duplicate_keys[(code, parsed_date)] += 1
                fields_by_code.setdefault(code, fields)

    duplicate_count = sum(1 for count in duplicate_keys.values() if count > 1)
    for code, dates in by_code.items():
        ranges_by_code[code] = [min(dates), max(dates)] if dates else [None, None]
    return {
        "files": [str(path.relative_to(PROJECT_ROOT)).replace("\\", "/") for path in files],
        "codes": set(by_code),
        "dates_by_code": by_code,
        "rows_by_code": dict(rows_by_code),
        "fields_by_code": fields_by_code,
        "ranges_by_code": ranges_by_code,
        "duplicate_location_date_key_count": duplicate_count,
        "date_parse_errors": parse_errors,
    }


def summarize(args: argparse.Namespace) -> dict[str, Any]:
    epidemic_path = project_path(args.epidemic)
    population_path = project_path(args.population)
    mapping_path = project_path(args.mapping)
    weather_root = project_path(args.weather_root)

    epidemic = profile_epidemic(epidemic_path)
    population = profile_population(population_path)
    weather = profile_weather(weather_root)
    mapping = load_mapping(mapping_path)

    epidemic_countries = epidemic["countries"]
    mapped_rows = [mapping.get(country) for country in epidemic_countries if mapping.get(country)]
    mapped_population_rows = [
        row
        for row in mapped_rows
        if (row.get("location_code") or "").strip().upper() in population["codes"] and parse_bool(row.get("enabled"))
    ]
    unmapped_countries = sorted(
        country
        for country in epidemic_countries
        if not mapping.get(country)
        or not (mapping[country].get("location_code") or "").strip()
        or not parse_bool(mapping[country].get("enabled"))
    )
    mapped_codes = {
        (row.get("location_code") or "").strip().upper()
        for row in mapped_population_rows
        if (row.get("location_code") or "").strip()
    }
    weather_codes = weather["codes"]
    weather_enabled_codes = set()
    with project_path(args.weather_locations).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if parse_bool(row.get("enabled")):
                code = (row.get("location_code") or "").strip().upper()
                if code:
                    weather_enabled_codes.add(code)

    common_weather_codes = sorted(weather_codes & mapped_codes)
    population_intersection_count = len(mapped_codes & population["codes"])
    per_country_common_dates: dict[str, Any] = {}
    all_common_dates: set[str] = set()
    for code in common_weather_codes:
        common_dates = epidemic["dates"] & weather["dates_by_code"].get(code, set())
        all_common_dates |= common_dates
        per_country_common_dates[code] = {
            "common_date_count": len(common_dates),
            "common_date_range": [min(common_dates), max(common_dates)] if common_dates else [None, None],
            "weather_rows": weather["rows_by_code"].get(code, 0),
            "weather_date_range": weather["ranges_by_code"].get(code, [None, None]),
        }

    weather_population_ok = all(code in population["codes"] for code in common_weather_codes)
    date_parse_ok = epidemic["date_parse_errors"] == 0 and weather["date_parse_errors"] == 0
    minimum_common_days = max(
        [item["common_date_count"] for item in per_country_common_dates.values()] or [0]
    )
    meets_minimum = (
        len(common_weather_codes) >= 3
        and minimum_common_days >= 300
        and weather_population_ok
        and date_parse_ok
        and weather["duplicate_location_date_key_count"] == 0
        and not population["duplicate_codes"]
    )

    return {
        "epidemic": {
            "path": str(epidemic_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "country_count": len(epidemic_countries),
            "date_range": epidemic["date_range"],
            "date_count": epidemic["date_count"],
            "date_parse_errors": epidemic["date_parse_errors"],
            "full_duplicate_rows": epidemic["full_duplicate_rows"],
            "duplicate_country_date_province_key_count": epidemic["duplicate_country_date_province_key_count"],
            "duplicate_country_date_province_examples": epidemic["duplicate_country_date_province_examples"],
            "country_date_with_multiple_province_rows": epidemic["country_date_with_multiple_province_rows"],
            "country_date_with_blank_and_province_rows": epidemic["country_date_with_blank_and_province_rows"],
            "blank_plus_province_examples": epidemic["blank_plus_province_examples"],
            "requires_province_dedup_before_country_aggregation": True,
        },
        "population": {
            "path": str(population_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "country_code_count": len(population["codes"]),
            "duplicate_codes": population["duplicate_codes"],
        },
        "weather": {
            "root": str(weather_root.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "files": weather["files"],
            "country_code_count": len(weather_codes),
            "country_codes": sorted(weather_codes),
            "fields_by_code": weather["fields_by_code"],
            "rows_by_code": weather["rows_by_code"],
            "ranges_by_code": weather["ranges_by_code"],
            "duplicate_location_date_key_count": weather["duplicate_location_date_key_count"],
            "date_parse_errors": weather["date_parse_errors"],
        },
        "overlap": {
            "epidemic_population_country_intersection_count": population_intersection_count,
            "epidemic_weather_country_intersection_count": len(common_weather_codes),
            "epidemic_weather_country_codes": common_weather_codes,
            "epidemic_weather_date_intersection_range": [min(all_common_dates), max(all_common_dates)]
            if all_common_dates
            else [None, None],
            "max_common_date_count": minimum_common_days,
            "per_country_common_dates": per_country_common_dates,
            "missing_weather_country_codes": sorted(weather_enabled_codes - weather_codes),
        },
        "mapping": {
            "mapping_rows_for_epidemic_countries": len(mapped_rows),
            "mapped_population_country_count": len(mapped_population_rows),
            "mapping_success_rate": round(len(mapped_population_rows) / len(epidemic_countries), 6)
            if epidemic_countries
            else 0.0,
            "unmapped_or_disabled_countries": unmapped_countries,
        },
        "quality_gate": {
            "at_least_3_weather_countries": len(common_weather_codes) >= 3,
            "at_least_300_common_dates": minimum_common_days >= 300,
            "weather_population_mapping_ok": weather_population_ok,
            "date_fields_parse_ok": date_parse_ok,
            "weather_and_population_primary_keys_ok": weather["duplicate_location_date_key_count"] == 0
            and not population["duplicate_codes"],
            "raw_epidemic_requires_dedup_before_cleaning": epidemic["duplicate_country_date_province_key_count"] > 0,
            "can_enter_spark_cleaning_stage": meets_minimum,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate epidemic, population, and weather overlap.")
    parser.add_argument("--epidemic", default=str(EPIDEMIC_PATH))
    parser.add_argument("--population", default=str(POPULATION_PATH))
    parser.add_argument("--mapping", default=str(MAPPING_PATH))
    parser.add_argument("--weather-root", default=str(WEATHER_ROOT))
    parser.add_argument("--weather-locations", default="config/weather_locations.csv")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    result = summarize(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output_json:
        output_path = project_path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
