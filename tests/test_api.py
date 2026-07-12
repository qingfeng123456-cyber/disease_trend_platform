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


def test_dashboard_contains_contextual_terminology_and_panel_notes():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="terminologyList"' in html
    assert 'id="terminologyDisclaimer"' in html
    assert 'id="trendPanelNote"' in html
    assert 'id="weatherPanelNote"' in html
    assert "MAE/RMSE 越低越好" in html
    assert "预测值减实际目标" in html
    assert "不代表感染人数或真实疾病负担占比" in html


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


def test_every_series_defaults_to_its_full_cleaned_date_range():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    for availability in options["availability"].values():
        for window in availability["location_date_ranges"].values():
            assert window["default_start"] == window["full_start"]
            assert window["default_end"] == window["full_end"]

    covid = options["availability"]["COVID-19"]
    window = covid["location_date_ranges"]["CHN"]

    assert window["last_nonzero_date"] <= window["full_end"]

    query = {
        "location": "CHN",
        "disease": "COVID-19",
        "model": "naive_last_value",
        "start_date": window["default_start"],
        "end_date": window["default_end"],
    }
    trend = unwrap(client.get("/api/trend", query_string=query))
    assert trend["points"]
    assert trend["points"][0]["date"] == window["default_start"]
    assert trend["points"][-1]["date"] == window["default_end"]
    assert any((point.get("actual") or 0) > 0 for point in trend["points"])
    assert any((point.get("rolling_7") or 0) > 0 for point in trend["points"])
    first_point = trend["points"][0]
    assert (
        date.fromisoformat(first_point["forecast_target_date"])
        - date.fromisoformat(first_point["date"])
    ).days == 7
    assert trend["reporting_profile"]["date_gap_count"] == 0
    assert isinstance(trend["reporting_profile"]["sparse_reporting"], bool)
    assert 0.0 <= trend["reporting_profile"]["zero_day_share"] <= 1.0

    overview = unwrap(client.get("/api/overview", query_string=query))
    assert overview["latest_date"] == window["default_end"]

    predictions = unwrap(client.get("/api/predictions", query_string=query))
    assert predictions["items"]
    assert any(abs(item.get("error") or 0) > 0 for item in predictions["items"])


def test_covid_china_weather_matches_within_full_default_period():
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
    assert weather["sample_size"] >= 366
    assert window["default_start"] <= weather["matched_date_range"]["start"]
    assert weather["matched_date_range"]["end"] <= window["default_end"]
    assert weather["message"] is None


def test_who_hiv_series_reaches_trend_and_prediction_apis():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    assert "HIV/AIDS" in options["diseases"]
    hiv_options = options["availability"]["HIV/AIDS"]
    assert hiv_options["frequency"] == "annual"
    assert hiv_options["metric"] == "new_infections"
    assert hiv_options["models"][:2] == ["naive_last_value", "moving_average"]
    assert "local_pytorch_lstm_hiv" in hiv_options["models"]

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


def test_who_indicator_summary_api_exposes_catalog_utilization():
    client = app.test_client()
    summary = unwrap(client.get("/api/who-indicators"))
    assert len(summary["items"]) >= 80
    death_rate = next(
        item for item in summary["items"] if item["indicator_code"] == "MDG_0000000017"
    )
    assert death_rate["duplicate_raw_rows"] == 4677
    assert death_rate["duplicate_content_conflict_groups"] == 0
    assert death_rate["selected_country_numeric_rows"] == 250
    mdr = next(item for item in summary["items"] if item["indicator_code"] == "TB_c_mdr_tsr")
    assert mdr["usage_class"] == "auxiliary_feature"


def test_model_coverage_api_explains_real_training_scope():
    client = app.test_client()
    coverage = unwrap(client.get("/api/model-coverage"))
    assert coverage["summary"]["gold_feature_rows"] > 0
    assert coverage["summary"]["all_diseases_share_one_learned_model"] is False
    assert coverage["summary"]["all_diseases_have_independent_lstm"] is True
    assert coverage["summary"]["disease_lstm_models_trained"] == 6
    gbdt = next(item for item in coverage["models"] if item["model"] == "local_sklearn_gbdt")
    assert gbdt["input_rows"] > 10000
    assert gbdt["uses_weather"] is True
    lstm = next(item for item in coverage["models"] if item["model"] == "local_pytorch_lstm")
    assert lstm["status"] == "trained"
    tuberculosis = next(item for item in coverage["per_disease"] if item["disease"] == "Tuberculosis")
    assert tuberculosis["learned_model_scope"] is True
    assert tuberculosis["disease_lstm_model"] == "local_pytorch_lstm_tuberculosis"


def test_every_disease_lstm_reaches_trend_predictions_and_metrics_apis():
    client = app.test_client()
    options = unwrap(client.get("/api/options"))
    for disease, availability in options["availability"].items():
        lstm_models = [model for model in availability["models"] if model.startswith("local_pytorch_lstm")]
        assert len(lstm_models) == 1, disease
        model = lstm_models[0]
        location = availability["locations"][0]["code"]
        trend = unwrap(
            client.get(
                "/api/trend",
                query_string={"disease": disease, "location": location, "model": model},
            )
        )
        assert trend["model"] == model
        assert any(point.get("prediction") is not None for point in trend["points"]), disease
        predictions = unwrap(
            client.get(
                "/api/predictions",
                query_string={"disease": disease, "location": location, "model": model},
            )
        )
        assert any(item.get("prediction") is not None for item in predictions["items"]), disease
        metrics = unwrap(client.get("/api/model-metrics", query_string={"disease": disease}))
        assert model in metrics["models"]
        assert any(item["model"] == model for item in metrics["comparison"]["items"])


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
