import json

from src.common.cleaning import clean_new_cases, normalize_disease_name, parse_iso_date, standardize_location_code
from src.common.paths import project_path


def test_date_conversion():
    assert parse_iso_date("2025-12-31").isoformat() == "2025-12-31"


def test_location_code_standardization():
    assert standardize_location_code(" chn ") == "CHN"
    assert standardize_location_code("china") is None


def test_disease_alias_mapping():
    aliases = json.loads(project_path("config", "disease_aliases.json").read_text(encoding="utf-8"))
    assert normalize_disease_name("新冠肺炎", aliases) == "COVID-19"
    assert normalize_disease_name("流感", aliases) == "Influenza"


def test_negative_case_correction():
    raw, clean, flag = clean_new_cases("-12")
    assert raw == -12
    assert clean == 0
    assert flag is True
