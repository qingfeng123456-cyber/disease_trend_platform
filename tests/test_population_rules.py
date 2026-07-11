from __future__ import annotations

from src.common.paths import project_path


def test_population_clean_job_keeps_years_as_observed_not_future_fill():
    text = project_path("src", "spark_jobs", "clean_population.py").read_text(encoding="utf-8")
    assert "POPULATION_YEARS = [2022, 2020, 2015, 2010, 2000, 1990, 1980, 1970]" in text
    assert "No future-year fill is applied" in text
    assert "2022 Population" in project_path("src", "spark_jobs", "schemas.py").read_text(encoding="utf-8")


def test_population_raw_file_has_required_columns():
    header = project_path(
        "data", "raw", "kaggle", "population", "world-population-dataset", "world_population.csv"
    ).read_text(encoding="utf-8-sig").splitlines()[0]
    assert "CCA3" in header
    assert "Country/Territory" in header
    assert "2020 Population" in header
