from __future__ import annotations

from src.common.paths import project_path


def test_epidemic_aggregation_rule_documented():
    text = project_path("docs", "epidemic_aggregation_rule.md").read_text(encoding="utf-8")
    assert "location_code + date" in text
    assert "Country/Region + Province/State + ObservationDate" in text
    assert "aggregation_conflict=true" in text
    assert "new_cases_clean = greatest(new_cases_raw, 0)" in text


def test_epidemic_clean_job_uses_confirmed_cumulative_fields():
    text = project_path("src", "spark_jobs", "clean_epidemic.py").read_text(encoding="utf-8")
    assert "Confirmed" in project_path("src", "spark_jobs", "schemas.py").read_text(encoding="utf-8")
    assert "total_cases_raw" in text
    assert "F.lag(\"total_cases\")" in text
    assert "is_negative_case_correction" in text
