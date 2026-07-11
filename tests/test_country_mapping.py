from __future__ import annotations

import csv

from src.common.paths import project_path


def load_mapping():
    path = project_path("config", "country_name_mapping.csv")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return {row["epidemic_name"]: row for row in csv.DictReader(f)}


def test_key_country_mappings_exist():
    mapping = load_mapping()
    assert mapping["US"]["location_code"] == "USA"
    assert mapping["Mainland China"]["location_code"] == "CHN"
    assert mapping["UK"]["location_code"] == "GBR"
    assert mapping["South Korea"]["location_code"] == "KOR"
    assert mapping["West Bank and Gaza"]["location_code"] == "PSE"


def test_unmapped_or_non_country_rows_are_not_silent_drops():
    mapping = load_mapping()
    for name in ["Diamond Princess", "MS Zaandam", "Others", "Kosovo"]:
        assert name in mapping
        assert mapping[name]["enabled"].lower() == "false"
        assert mapping[name]["notes"]
