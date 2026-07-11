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
