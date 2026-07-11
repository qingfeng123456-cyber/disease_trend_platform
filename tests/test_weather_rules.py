from __future__ import annotations

import csv

from src.common.paths import project_path


def test_weather_locations_have_required_enabled_test_countries():
    path = project_path("config", "weather_locations.csv")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = {row["location_code"]: row for row in csv.DictReader(f)}

    for code in ["CHN", "USA", "GBR"]:
        assert code in rows
        assert rows[code]["enabled"].lower() == "true"
        assert rows[code]["representative_city"]
        assert rows[code]["latitude"]
        assert rows[code]["longitude"]


def test_weather_clean_job_reads_only_open_meteo_csv_pattern():
    text = project_path("src", "spark_jobs", "clean_weather.py").read_text(encoding="utf-8")
    assert "/*/*.csv" in text
    assert "representative_city_notice" in text
    assert "temperature_unit" in text


def test_open_meteo_sample_files_exist_after_small_validation():
    assert project_path("data", "raw", "open_meteo", "CHN", "open_meteo_CHN_2020.csv").exists()
    assert project_path("data", "raw", "open_meteo", "USA", "open_meteo_USA_2020.csv").exists()
    assert project_path("data", "raw", "open_meteo", "GBR", "open_meteo_GBR_2020.csv").exists()
