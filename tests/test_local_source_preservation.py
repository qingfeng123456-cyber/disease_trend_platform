from __future__ import annotations

import json

import pandas as pd

from scripts.build_local_serving_from_raw import (
    build_source_status,
    clean_china_cdc_metadata,
    clean_historical_weather,
    clean_who,
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
        "who": {"input_files": 105, "input_rows": 122169, "output_rows": 117492, "hiv_observation_rows": 96},
        "historical_weather": {"input_rows": 45253, "output_rows": 6},
        "models": {},
    }

    items = build_source_status(quality, "2026-07-11T00:00:00+00:00")
    status_by_name = {item["name"]: item["status"] for item in items}

    assert status_by_name["China CDC cleaned report index"] == "info"
    assert status_by_name["WHO GHO indicators and HIV annual series"] == "ok"
    assert status_by_name["Kaggle 2012-2017 historical weather"] == "ok"
    assert all(item["status"] != "warn" for item in items)


def test_who_cleaning_curates_hiv_and_keeps_false_matches_catalog_only(tmp_path):
    fields = [
        "source",
        "endpoint",
        "indicator_code",
        "indicator_name",
        "location_code",
        "location_name",
        "location_type",
        "year",
        "value",
        "numeric_value",
        "low",
        "high",
        "unit",
        "sex",
        "age",
        "publish_state",
        "raw_json",
    ]

    def row(code, name, year, value, record_id, *, low=None, high=None, dim1_type=None, dim1=None):
        raw = {
            "Id": record_id,
            "IndicatorCode": code,
            "SpatialDimType": "COUNTRY",
            "SpatialDim": "AUS",
            "TimeDim": year,
            "Dim1Type": dim1_type,
            "Dim1": dim1,
            "NumericValue": value,
        }
        return {
            "source": "WHO GHO OData",
            "endpoint": code,
            "indicator_code": code,
            "indicator_name": name,
            "location_code": "AUS",
            "location_name": None,
            "location_type": "COUNTRY",
            "year": year,
            "value": "No data" if value is None else value,
            "numeric_value": value,
            "low": low,
            "high": high,
            "unit": None,
            "sex": None,
            "age": None,
            "publish_state": None,
            "raw_json": json.dumps(raw),
        }

    def write_file(topic, code, rows):
        path = tmp_path / f"who_{topic}_{code}_20260711T000000Z.csv"
        pd.DataFrame(rows, columns=fields).to_csv(path, index=False, encoding="utf-8-sig")

    write_file(
        "hiv",
        "HIV_0000000026",
        [
            row("HIV_0000000026", "Number of new HIV infections", 2020, 100.0, 1, low=80.0, high=120.0),
            row("HIV_0000000026", "Number of new HIV infections", 2021, None, 2),
        ],
    )
    write_file(
        "hiv",
        "MDG_0000000029",
        [row("MDG_0000000029", "Prevalence of HIV among adults aged 15 to 49 (%)", 2020, 0.2, 3)],
    )
    write_file(
        "tuberculosis",
        "MDG_0000000017",
        [row("MDG_0000000017", "Deaths due to tuberculosis among HIV-negative people (per 100 000 population)", 2020, 0.3, 4)],
    )
    write_file(
        "tuberculosis",
        "TB_1",
        [row("TB_1", "Tuberculosis treatment coverage", 2020, 75.0, 5)],
    )
    write_file(
        "tuberculosis",
        "TB_c_newinc",
        [row("TB_c_newinc", "Tuberculosis - new and relapse cases", 2020, 1400.0, 6)],
    )
    write_file(
        "influenza",
        "EMFLIMITMAGNETIC",
        [row("EMFLIMITMAGNETIC", "Magnetic flux density (microT)", 2018, 50.0, 7, dim1_type="SEX", dim1="SEX_MLE")],
    )
    location_catalog = pd.DataFrame(
        [{"location_code": "AUS", "location": "Australia", "representative_city": "Canberra", "latitude": -35.28, "longitude": 149.13}]
    )

    catalog, hiv, tb_auxiliary, quality = clean_who(tmp_path, {"AUS"}, location_catalog)

    assert len(hiv) == 1
    assert hiv.iloc[0]["value"] == 100.0
    assert hiv.iloc[0]["hiv_prevalence_adults_percent"] == 0.2
    assert len(tb_auxiliary) == 1
    assert tb_auxiliary.iloc[0]["who_tb_new_relapse_cases"] == 1400.0
    false_match = catalog[catalog["indicator_code"].eq("EMFLIMITMAGNETIC")].iloc[0]
    assert false_match["usage_class"] == "keyword_false_positive"
    assert false_match["sex"] == "SEX_MLE"
    assert quality["primary_no_data_rows"] == 1
    assert quality["hiv_observation_rows"] == 1
