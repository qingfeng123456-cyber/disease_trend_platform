from src.models.metrics import regression_metrics


def test_regression_metrics_handle_zero_actual():
    metrics = regression_metrics([0, 10, 20], [0, 12, 18])
    assert metrics["mae"] > 0
    assert metrics["mape"] >= 0
    assert metrics["smape"] >= 0
