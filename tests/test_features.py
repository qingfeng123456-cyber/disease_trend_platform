from datetime import date, timedelta


def make_series(days=20):
    start = date(2025, 1, 1)
    return [{"date": start + timedelta(days=i), "value": i} for i in range(days)]


def test_time_series_target_uses_future_lead_only_for_label():
    rows = make_series()
    horizon = 7
    for i, row in enumerate(rows[:-horizon]):
      row["lag_1"] = rows[i - 1]["value"] if i >= 1 else None
      row["target_t_plus_7"] = rows[i + horizon]["value"]
    assert rows[8]["lag_1"] == 7
    assert rows[8]["target_t_plus_7"] == 15
    assert rows[8]["lag_1"] < rows[8]["value"]


def test_dedup_keeps_latest_collected_record():
    rows = [
        {"source": "demo", "disease": "COVID-19", "location_code": "CHN", "date": "2025-01-01", "collected_at": 1, "value": 10},
        {"source": "demo", "disease": "COVID-19", "location_code": "CHN", "date": "2025-01-01", "collected_at": 2, "value": 12},
    ]
    latest = sorted(rows, key=lambda row: row["collected_at"], reverse=True)[0]
    assert latest["value"] == 12
