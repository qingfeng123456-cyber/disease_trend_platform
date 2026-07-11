from __future__ import annotations

import json

import pandas as pd

from scripts.build_local_serving_from_raw import (
    build_source_status,
    clean_china_cdc_metadata,
    clean_historical_weather,
)


def test_historical_weather_is_aggregated_by_supported_country_and_year(tmp_path):
    pd.DataFrame(
        [
            {"City": "New York", "Country": "United States", "Latitude": 40.7, "Longitude": -74.0},
            {"City": "Vancouver", "Country": "Canada", "Latitude": 49.2, "Longitude": -123.1},
        ]
    ).to_csv(tmp_path / "city_attributes.csv", index=False)
    dates = ["2012-01-01 00:00:00", "2012-06-01 00:00:00", "2013-01-01 00:00:00"]
    metrics = {
        "temperature.csv": [283.15, 285.15, 293.15],
        "humidity.csv": [50.0, 60.0, 70.0],
        "pressure.csv": [1000.0, 1010.0, 1020.0],
        "wind_speed.csv": [3.0, 4.0, 5.0],
    }
    for filename, values in metrics.items():
        pd.DataFrame({"datetime": dates, "New York": values, "Vancouver": [999.0, 999.0, 999.0]}).to_csv(
            tmp_path / filename,
            index=False,
        )

    cleaned, quality = clean_historical_weather(tmp_path, {"USA"})

    assert cleaned["location_code"].unique().tolist() == ["USA"]
    assert cleaned["year"].tolist() == [2012, 2013]
    assert cleaned.loc[cleaned["year"].eq(2012), "temperature_mean"].iloc[0] == 11.0
    assert cleaned.loc[cleaned["year"].eq(2013), "temperature_mean"].iloc[0] == 20.0
    assert quality["input_rows"] == 3
    assert quality["output_rows"] == 2


def test_china_cdc_metadata_keeps_raw_references_and_extracts_safe_summary(tmp_path):
    (tmp_path / "html").mkdir()
    (tmp_path / "attachments").mkdir()
    (tmp_path / "html" / "report.html").write_text("report", encoding="utf-8")
    (tmp_path / "attachments" / "report.pdf").write_bytes(b"%PDF test")
    record = {
        "page_url": "https://example.test/report.html",
        "title": "中国疾病预防控制中心",
        "anchor_title": "2026年第27周第916期中国流感监测周报",
        "published_date": "2026-07-09",
        "downloaded_at": "2026-07-10T00:00:00+00:00",
        "local_html_path": "html\\report.html",
        "attachment_urls": ["https://example.test/report.pdf"],
        "local_attachment_paths": ["attachments\\report.pdf"],
        "text_preview": "全国共报告7起流感样病例暴发疫情。南方省份哨点医院报告的ILI%为5.8%。",
    }
    duplicate = {**record, "downloaded_at": "2026-07-10T01:00:00+00:00"}
    (tmp_path / "page_metadata.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in [record, duplicate]),
        encoding="utf-8",
    )

    cleaned, quality = clean_china_cdc_metadata(tmp_path)

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["report_category"] == "Influenza surveillance"
    assert cleaned.iloc[0]["report_week"] == 27
    assert cleaned.iloc[0]["reported_ili_outbreaks"] == 7
    assert cleaned.iloc[0]["south_ili_percent"] == 5.8
    assert bool(cleaned.iloc[0]["attachments_complete"])
    assert quality["duplicate_url_rows"] == 1
    assert quality["local_attachment_missing_count"] == 0


def test_source_status_does_not_report_intentional_states_as_warnings():
    quality = {
        "owid": {"output_rows": 10},
        "kaggle_covid": {"output_rows": 10},
        "tuberculosis": {"output_rows": 10},
        "respiratory": {"output_rows": 10},
        "weather": {"output_rows": 10},
        "population": {"output_rows": 10},
        "china_cdc": {"input_rows": 27, "output_rows": 27},
        "who": {"configured_indicator_count": 0, "local_csv_count": 0},
        "historical_weather": {"input_rows": 45253, "output_rows": 6},
        "models": {},
    }

    items = build_source_status(quality, "2026-07-11T00:00:00+00:00")
    status_by_name = {item["name"]: item["status"] for item in items}

    assert status_by_name["China CDC cleaned report index"] == "info"
    assert status_by_name["WHO indicators"] == "not_configured"
    assert status_by_name["Kaggle 2012-2017 historical weather"] == "ok"
    assert all(item["status"] != "warn" for item in items)
