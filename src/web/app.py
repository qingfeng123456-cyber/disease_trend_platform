from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify, render_template, request

from src.common.config import get_setting, load_settings
from src.common.exceptions import DataNotReadyError, PlatformError, ValidationError
from src.common.logger import get_logger, setup_logging
from src.web.services.data_service import DataService

try:
    from flask_cors import CORS
except ImportError:  # pragma: no cover - CORS 是同源部署时的可选增强
    CORS = None

setup_logging()
logger = get_logger("web")

app = Flask(__name__)
if CORS is not None:
    CORS(app)
service = DataService()


def api_ok(data: Any, *, status_code: int = 200):
    payload = {"ok": True, "status": "ok", "data": data, "error": None}
    if isinstance(data, dict) and "status" in data:
        payload["status"] = data["status"]
    return jsonify(payload), status_code


def api_error(message: str, *, status_code: int = 400, code: str = "bad_request"):
    return jsonify({"ok": False, "status": "error", "data": None, "error": {"code": code, "message": message}}), status_code


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return api_ok(service.health())


@app.get("/api/overview")
def overview():
    return api_ok(
        service.overview(
            location=request.args.get("location") or request.args.get("iso"),
            disease=request.args.get("disease"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
    )


@app.get("/api/trend")
def trend():
    data = service.trend(
        location=request.args.get("location") or request.args.get("iso"),
        disease=request.args.get("disease"),
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        model=request.args.get("model"),
    )
    return api_ok(data)


@app.get("/api/risk-map")
def risk_map():
    return api_ok(service.risk_map(disease=request.args.get("disease")))


@app.get("/api/rankings")
def rankings():
    return api_ok(service.rankings(disease=request.args.get("disease")))


@app.get("/api/model-metrics")
def model_metrics():
    return api_ok(service.model_metrics())


@app.get("/api/data-quality")
def data_quality():
    return api_ok(service.data_quality())


@app.get("/api/options")
def options():
    return api_ok(service.options())


@app.get("/api/predictions")
def predictions():
    return api_ok(
        service.predictions(
            location=request.args.get("location") or request.args.get("iso"),
            disease=request.args.get("disease"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
            model=request.args.get("model"),
        )
    )


@app.get("/api/weather-correlation")
def weather_correlation():
    return api_ok(
        service.weather_correlation(
            location=request.args.get("location") or request.args.get("iso"),
            disease=request.args.get("disease"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
    )


@app.get("/api/disease-share")
def disease_share():
    return api_ok(service.disease_share())


@app.get("/api/source-status")
def source_status():
    return api_ok(service.source_status())


@app.errorhandler(ValidationError)
def handle_validation(error: ValidationError):
    logger.warning("参数错误: %s", error)
    return api_error(str(error), status_code=400, code="validation_error")


@app.errorhandler(DataNotReadyError)
def handle_data_not_ready(error: DataNotReadyError):
    logger.warning("数据未准备好: %s", error)
    return api_error(str(error), status_code=503, code="data_not_ready")


@app.errorhandler(PlatformError)
def handle_platform_error(error: PlatformError):
    logger.exception("平台异常: %s", error)
    return api_error(str(error), status_code=500, code="platform_error")


@app.errorhandler(Exception)
def handle_unknown(error: Exception):
    logger.exception("未处理异常: %s", error)
    return api_error("服务内部错误，请检查 logs/platform.log", status_code=500, code="internal_error")


def main():
    settings = load_settings()
    host = os.getenv("FLASK_HOST", str(get_setting(settings, "web.host", "0.0.0.0")))
    port = int(os.getenv("FLASK_PORT", str(get_setting(settings, "web.port", 5000))))
    debug = os.getenv("FLASK_DEBUG", "1" if get_setting(settings, "web.debug", False) else "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
