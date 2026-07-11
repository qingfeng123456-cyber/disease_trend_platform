from datetime import date

from src.web.app import app
from src.web.services.data_service import DataService
from src.common.exceptions import DataNotReadyError


def unwrap(response):
    payload = response.get_json()
    assert payload["ok"] is True
    return payload["data"]


def test_health():
    client = app.test_client()
    data = unwrap(client.get("/api/health"))
    assert data["status"] == "ok"
    assert "data_mode" in data


def test_overview_has_disclaimer():
    client = app.test_client()
    data = unwrap(client.get("/api/overview"))
    assert "disclaimer" in data
    assert isinstance(data["demo_mode"], bool)


def test_trend_api():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    disease = options["diseases"][0]
    availability = options.get("availability", {}).get(disease, {})
    locations = availability.get("locations") or options["locations"]
    models = availability.get("models") or options["models"]
    location = locations[0]["code"]
    model = models[0]
    data = unwrap(client.get(f"/api/trend?location={location}&disease={disease}&model={model}"))
    assert data["location_code"] == location
    assert data["points"]
    assert {"date", "actual", "rolling_7", "prediction"}.issubset(data["points"][0])


def test_weather_correlation_can_filter_current_series():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    disease = options["diseases"][0]
    availability = options.get("availability", {}).get(disease, {})
    locations = availability.get("locations") or options["locations"]
    location = locations[0]["code"]
    data = unwrap(client.get(f"/api/weather-correlation?location={location}&disease={disease}"))
    assert "items" in data
    assert data["location_code"] == location
    assert data["disease"] == disease


def test_covid_china_uses_effective_default_window():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    covid = options["availability"]["COVID-19"]
    window = covid["location_date_ranges"]["CHN"]

    assert window["full_start"] < window["default_start"]
    assert window["default_end"] < window["full_end"]
    assert window["last_nonzero_date"] <= window["default_end"]
    assert (date.fromisoformat(window["default_end"]) - date.fromisoformat(window["default_start"])).days <= 365

    query = {
        "location": "CHN",
        "disease": "COVID-19",
        "model": "naive_last_value",
        "start_date": window["default_start"],
        "end_date": window["default_end"],
    }
    trend = unwrap(client.get("/api/trend", query_string=query))
    assert trend["points"]
    assert trend["points"][-1]["date"] == window["default_end"]
    assert any((point.get("actual") or 0) > 0 for point in trend["points"])
    assert any((point.get("rolling_7") or 0) > 0 for point in trend["points"])

    overview = unwrap(client.get("/api/overview", query_string=query))
    assert overview["latest_date"] == window["default_end"]
    assert overview["current_rolling_value"] > 0

    predictions = unwrap(client.get("/api/predictions", query_string=query))
    assert predictions["items"]
    assert any(abs(item.get("error") or 0) > 0 for item in predictions["items"])


def test_covid_china_weather_matches_effective_default_period():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    window = options["availability"]["COVID-19"]["location_date_ranges"]["CHN"]
    weather = unwrap(
        client.get(
            "/api/weather-correlation",
            query_string={
                "location": "CHN",
                "disease": "COVID-19",
                "start_date": window["default_start"],
                "end_date": window["default_end"],
            },
        )
    )

    assert weather["fallback_used"] is False
    assert weather["items"]
    assert weather["sample_size"] == 366
    assert weather["matched_date_range"] == {
        "start": window["default_start"],
        "end": window["default_end"],
    }
    assert weather["message"] is None


def test_who_hiv_series_reaches_trend_and_prediction_apis():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    assert "HIV/AIDS" in options["diseases"]
    hiv_options = options["availability"]["HIV/AIDS"]
    assert hiv_options["frequency"] == "annual"
    assert hiv_options["metric"] == "new_infections"
    assert hiv_options["models"] == ["naive_last_value", "moving_average"]

    trend = unwrap(
        client.get(
            "/api/trend",
            query_string={"location": "BRA", "disease": "HIV/AIDS", "model": "moving_average"},
        )
    )
    assert trend["points"]
    assert trend["metric_label"] == "年度新增 HIV 感染数"
    assert {"who_estimate_low", "who_estimate_high", "hiv_prevalence_adults_percent"}.issubset(
        trend["points"][0]
    )

    predictions = unwrap(
        client.get(
            "/api/predictions",
            query_string={"location": "BRA", "disease": "HIV/AIDS", "model": "moving_average"},
        )
    )
    assert predictions["items"]

    sources = unwrap(client.get("/api/source-status"))
    who = next(item for item in sources["items"] if item["name"].startswith("WHO GHO"))
    assert who["status"] == "ok"


def test_trend_validation_error():
    client = app.test_client()
    response = client.get("/api/trend?location=BAD&disease=COVID-19&model=demo_trend_model")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"


def test_missing_serving_file_error(tmp_path):
    service = DataService(serving_dir=tmp_path)
    try:
        service.overview()
    except DataNotReadyError as exc:
        assert "overview.json" in str(exc)
    else:
        raise AssertionError("expected DataNotReadyError")
