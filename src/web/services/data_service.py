from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.common.config import get_setting, load_settings
from src.common.exceptions import DataNotReadyError, ValidationError
from src.common.paths import project_path, safe_relative

@dataclass
class CacheEntry:
    mtime: float
    loaded_at: float
    data: Any


class DataService:
    """Flask 请求期间只读取 serving 层文件，不启动 Spark 作业。"""

    def __init__(self, serving_dir: str | Path | None = None, cache_seconds: int | None = None):
        settings = load_settings()
        configured = serving_dir or os.getenv("SERVING_DIR") or get_setting(settings, "paths.serving", "data/serving")
        self.serving_dir = project_path(configured)
        self.cache_seconds = int(cache_seconds or get_setting(settings, "web.cache_seconds", 30))
        self.default_location = str(get_setting(settings, "web.default_location", "CHN")).upper()
        self.default_disease = str(get_setting(settings, "web.default_disease", "COVID-19"))
        self.version = str(get_setting(settings, "project.version", "1.0.0"))
        self._cache: dict[str, CacheEntry] = {}

    def _read_json(self, filename: str, *, required: bool = True) -> Any:
        path = self.serving_dir / filename
        if not path.exists():
            if required:
                raise DataNotReadyError(
                    f"缺少 serving 文件 {filename}，请先运行 python -m src.collectors.generate_demo_data "
                    "或 Spark 导出作业。"
                )
            return None
        stat = path.stat()
        cached = self._cache.get(filename)
        now = time.time()
        if cached and cached.mtime == stat.st_mtime and now - cached.loaded_at <= self.cache_seconds:
            return cached.data
        data = json.loads(path.read_text(encoding="utf-8"))
        self._cache[filename] = CacheEntry(stat.st_mtime, now, data)
        return data

    def metadata(self) -> dict[str, Any]:
        return self._read_json("metadata.json", required=False) or {"data_mode": "unknown"}

    def health(self) -> dict[str, Any]:
        overview = self._read_json("overview.json", required=False) or {}
        metadata = self.metadata()
        return {
            "status": "ok",
            "data_mode": overview.get("data_mode") or metadata.get("data_mode") or "unknown",
            "last_update": overview.get("last_update") or metadata.get("generated_at"),
            "version": self.version,
            "serving_dir": safe_relative(self.serving_dir),
        }

    def overview(
        self,
        *,
        location: str | None = None,
        disease: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        payload = self._read_json("overview.json")
        if not location and not disease:
            return payload
        options = self.options()
        location_code = self._normalize_location(location or self.default_location, options)
        disease_name = self._normalize_disease(disease or self.default_disease, options)
        summary = next(
            (
                item
                for item in payload.get("series", [])
                if item.get("location_code") == location_code and item.get("disease") == disease_name
            ),
            None,
        )
        if summary is None:
            return payload
        start = self._parse_optional_date(start_date, "start_date")
        end = self._parse_optional_date(end_date, "end_date")
        if start and end and start > end:
            raise ValidationError("start_date 不能晚于 end_date")
        selected_points: list[dict[str, Any]] = []
        if start or end:
            trend_payload = self._read_json("trend.json")
            series = next(
                (
                    item
                    for item in trend_payload.get("items", [])
                    if item.get("location_code") == location_code and item.get("disease") == disease_name
                ),
                None,
            )
            if series:
                for point in series.get("points", []):
                    point_date = date.fromisoformat(point["date"])
                    if start and point_date < start:
                        continue
                    if end and point_date > end:
                        continue
                    selected_points.append(point)
        latest_point = selected_points[-1] if selected_points else None
        first_point = selected_points[0] if selected_points else None
        risk_items = self.risk_map(disease=disease_name).get("items", [])
        disease_metrics = self.model_metrics(disease=disease_name)
        risk_comparable = len(risk_items) >= 2 and any(
            bool(item.get("risk_comparable", True)) for item in risk_items
        )
        reporting_points = selected_points
        last_nonzero_point = next(
            (
                point
                for point in reversed(reporting_points)
                if isinstance(point.get("actual"), (int, float))
                and not math.isclose(float(point["actual"]), 0.0, abs_tol=1e-12)
            ),
            None,
        )
        trailing_zero_periods = 0
        for point in reversed(reporting_points):
            value = point.get("actual")
            if not isinstance(value, (int, float)) or not math.isclose(float(value), 0.0, abs_tol=1e-12):
                break
            trailing_zero_periods += 1
        if not reporting_points:
            trailing_zero_periods = int(summary.get("trailing_zero_periods") or 0)
        frequency = str(summary.get("frequency") or "daily")
        stale_threshold = {"daily": 28, "weekly": 8, "annual": 2}.get(frequency, 8)
        return {
            **payload,
            "selected_location_code": location_code,
            "selected_location": summary.get("location"),
            "selected_disease": disease_name,
            "selected_metric": summary.get("metric"),
            "selected_metric_label": summary.get("metric_label"),
            "selected_frequency": summary.get("frequency"),
            "selected_rolling_label": summary.get("rolling_label"),
            "latest_date": latest_point.get("date") if latest_point else summary.get("latest_date"),
            "start_date": first_point.get("date") if first_point else summary.get("start_date"),
            "end_date": latest_point.get("date") if latest_point else summary.get("end_date"),
            "current_total_cases": latest_point.get("total_cases") if latest_point else summary.get("current_total_cases"),
            "current_total_deaths": latest_point.get("total_deaths") if latest_point else summary.get("current_total_deaths"),
            "current_new_cases": latest_point.get("actual") if latest_point else summary.get("current_value"),
            "current_rolling_value": latest_point.get("rolling_7") if latest_point else summary.get("current_rolling_value"),
            "last_nonzero_date": (
                last_nonzero_point.get("date") if last_nonzero_point else summary.get("last_nonzero_date")
            ),
            "last_nonzero_value": (
                last_nonzero_point.get("actual") if last_nonzero_point else summary.get("last_nonzero_value")
            ),
            "trailing_zero_periods": trailing_zero_periods,
            "reporting_stale": trailing_zero_periods >= stale_threshold,
            "high_risk_regions": (
                sum(1 for item in risk_items if item.get("risk_level") == "高风险")
                if risk_comparable
                else None
            ),
            "risk_comparable": risk_comparable,
            "risk_comparison_regions": len(risk_items),
            "best_model": disease_metrics.get("best_model"),
            "best_model_mae": disease_metrics.get("mae"),
        }

    def options(self) -> dict[str, Any]:
        return self._read_json("options.json")

    def source_status(self) -> dict[str, Any]:
        return self._read_json("source_status.json")

    def who_indicators(self) -> dict[str, Any]:
        return self._read_json("who_indicator_summary.json")

    def model_coverage(self) -> dict[str, Any]:
        return self._read_json("model_data_coverage.json")

    def risk_map(self, *, disease: str | None = None) -> dict[str, Any]:
        payload = self._read_json("risk_map.json")
        if not disease:
            return payload
        disease_name = self._normalize_disease(disease, self.options())
        return {**payload, "items": [item for item in payload.get("items", []) if item.get("disease") == disease_name]}

    def rankings(self, *, disease: str | None = None) -> dict[str, Any]:
        payload = self._read_json("rankings.json")
        if not disease:
            return payload
        disease_name = self._normalize_disease(disease, self.options())
        return {
            **payload,
            "risk": [item for item in payload.get("risk", []) if item.get("disease") == disease_name],
            "growth": [item for item in payload.get("growth", []) if item.get("disease") == disease_name],
            "forecast": [item for item in payload.get("forecast", []) if item.get("disease") == disease_name],
        }

    def model_metrics(self, *, disease: str | None = None) -> dict[str, Any]:
        metrics = self._read_json("model_metrics.json")
        comparison = self._read_json("model_comparison.json", required=False)
        if disease:
            disease_name = self._normalize_disease(disease, self.options())
            summary = metrics.get("by_disease", {}).get(disease_name, {})
            disease_comparison = (comparison or {}).get("by_disease", {}).get(disease_name, {})
            model_names = self.options().get("availability", {}).get(disease_name, {}).get("models", [])
            model_details = {
                model_name: details
                for model_name, details in metrics.get("models", {}).items()
                if model_name in model_names
            }
            return {
                **summary,
                "data_mode": metrics.get("data_mode"),
                "models": model_details,
                "comparison": disease_comparison or summary.get("comparison", {}),
            }
        if comparison:
            metrics = {**metrics, "comparison": comparison}
        return metrics

    def data_quality(self) -> dict[str, Any]:
        return self._read_json("data_quality_report.json")

    def predictions(
        self,
        *,
        location: str | None = None,
        disease: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        payload = self._read_json("predictions.json")
        filtered = self._filter_payload_items(
            payload,
            location=location,
            disease=disease,
            start_date=start_date,
            end_date=end_date,
        )
        options = self.options()
        disease_name = self._normalize_disease(disease or self.default_disease, options)
        availability = options.get("availability", {}).get(disease_name, {})
        default_model = str(availability.get("default_model") or options.get("default_model") or "moving_average")
        model_name = self._normalize_model(model or default_model, options, disease_name)
        prepared_items = []
        prediction_key = f"prediction_{model_name}"
        for item in filtered.get("items", []):
            prepared = dict(item)
            prediction = prepared.get(prediction_key)
            prepared["prediction"] = prediction
            actual = prepared.get("actual_t_plus_7")
            prepared["error"] = prediction - actual if prediction is not None and actual is not None else None
            prepared_items.append(prepared)
        return {**filtered, "model": model_name, "items": prepared_items}

    def weather_correlation(
        self,
        *,
        location: str | None = None,
        disease: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        payload = self._read_json("weather_correlation.json")
        filtered = self._filter_payload_items(
            payload,
            location=location,
            disease=disease,
            start_date=start_date,
            end_date=end_date,
        )
        valid_items = []
        for item in filtered.get("items", []):
            values = [item.get("temperature_mean"), item.get("relative_humidity_mean"), item.get("new_cases_smoothed")]
            if all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values):
                valid_items.append(item)
        fallback_used = False
        if not valid_items and (start_date or end_date) and location and disease:
            full_filtered = self._filter_payload_items(
                payload,
                location=location,
                disease=disease,
                start_date=None,
                end_date=None,
            )
            full_valid_items = []
            for item in full_filtered.get("items", []):
                values = [
                    item.get("temperature_mean"),
                    item.get("relative_humidity_mean"),
                    item.get("new_cases_smoothed"),
                ]
                if all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values):
                    full_valid_items.append(item)
            if full_valid_items:
                filtered = full_filtered
                valid_items = full_valid_items
                fallback_used = True
        metric_label = valid_items[0].get("metric_label") if valid_items else None
        matched_date_range = None
        if valid_items:
            matched_date_range = {
                "start": str(valid_items[0].get("date") or "")[:10],
                "end": str(valid_items[-1].get("date") or "")[:10],
            }
        return {
            **filtered,
            "items": valid_items[-1200:],
            "sample_size": len(valid_items),
            "metric_label": metric_label,
            "temperature_correlation": self._pearson(valid_items, "temperature_mean", "new_cases_smoothed"),
            "humidity_correlation": self._pearson(valid_items, "relative_humidity_mean", "new_cases_smoothed"),
            "fallback_used": fallback_used,
            "matched_date_range": matched_date_range,
            "message": (
                "所选日期窗口没有同期天气，已展示该疾病和地区全部可匹配天气期。"
                if fallback_used
                else (None if valid_items else "当前疾病、地区和日期范围没有可关联的同期天气数据。")
            ),
        }

    def disease_share(self) -> dict[str, Any]:
        return self._read_json("disease_share.json")

    def trend(
        self,
        *,
        location: str | None = None,
        disease: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        options = self.options()
        location_code = self._normalize_location(location or self.default_location, options)
        disease_name = self._normalize_disease(disease or self.default_disease, options)
        availability = options.get("availability", {}).get(disease_name, {})
        default_model = str(availability.get("default_model") or options.get("default_model") or "moving_average")
        model_name = self._normalize_model(model or default_model, options, disease_name)
        start = self._parse_optional_date(start_date, "start_date")
        end = self._parse_optional_date(end_date, "end_date")
        if start and end and start > end:
            raise ValidationError("start_date 不能晚于 end_date")

        payload = self._read_json("trend.json")
        matched = None
        for item in payload.get("items", []):
            if item.get("location_code") == location_code and item.get("disease") == disease_name:
                matched = item
                break
        if matched is None:
            raise ValidationError(f"没有找到地区 {location_code} 和疾病 {disease_name} 的趋势数据")

        points = []
        for point in matched.get("points", []):
            point_date = date.fromisoformat(point["date"])
            if start and point_date < start:
                continue
            if end and point_date > end:
                continue
            prepared = dict(point)
            if model_name == "naive_last_value":
                prepared["prediction"] = prepared.get("actual")
                prepared["lower"] = None
                prepared["upper"] = None
            elif model_name in {"naive_rolling_7", "moving_average"}:
                prepared["prediction"] = prepared.get("rolling_7")
                prepared["lower"] = None
                prepared["upper"] = None
            else:
                prediction = prepared.get(f"prediction_{model_name}")
                prepared["prediction"] = prediction
                prepared["lower"] = max(0.0, prediction * 0.85) if prediction is not None else None
                prepared["upper"] = prediction * 1.15 if prediction is not None else None
            points.append(prepared)
        reporting_profile = None
        if points and matched.get("frequency") == "daily":
            observed_dates = {date.fromisoformat(point["date"]) for point in points}
            expected_days = (max(observed_dates) - min(observed_dates)).days + 1
            actual_values = [point.get("actual") for point in points]
            numeric_values = [value for value in actual_values if isinstance(value, (int, float))]
            zero_day_count = sum(math.isclose(float(value), 0.0, abs_tol=1e-12) for value in numeric_values)
            zero_day_share = zero_day_count / len(numeric_values) if numeric_values else 0.0
            date_gap_count = max(expected_days - len(observed_dates), 0)
            sparse_reporting = (
                date_gap_count == 0
                and zero_day_share >= 0.5
                and any(float(value) > 0 for value in numeric_values)
            )
            reporting_profile = {
                "expected_calendar_days": expected_days,
                "observed_rows": len(observed_dates),
                "date_gap_count": date_gap_count,
                "zero_day_count": zero_day_count,
                "zero_day_share": round(zero_day_share, 4),
                "sparse_reporting": sparse_reporting,
                "note": (
                    "日期连续，但该窗口来源值以批次方式更新；零值是来源中的当日报告值，不是清洗造成的缺行。"
                    if sparse_reporting
                    else ("日期存在缺行，请检查来源覆盖。" if date_gap_count else None)
                ),
            }
        return {
            "data_mode": payload.get("data_mode", "unknown"),
            "location_code": location_code,
            "location": matched.get("location"),
            "disease": disease_name,
            "model": model_name,
            "frequency": matched.get("frequency"),
            "metric": matched.get("metric"),
            "metric_label": matched.get("metric_label"),
            "rolling_label": matched.get("rolling_label"),
            "forecast_horizon_label": matched.get("forecast_horizon_label"),
            "source": matched.get("source"),
            "reporting_profile": reporting_profile,
            "points": points,
        }

    def _filter_payload_items(
        self,
        payload: dict[str, Any],
        *,
        location: str | None,
        disease: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> dict[str, Any]:
        options = self.options()
        location_code = self._normalize_location(location, options) if location else None
        disease_name = self._normalize_disease(disease, options) if disease else None
        start = self._parse_optional_date(start_date, "start_date")
        end = self._parse_optional_date(end_date, "end_date")
        if start and end and start > end:
            raise ValidationError("start_date 不能晚于 end_date")
        items = []
        for item in payload.get("items", []):
            if location_code and item.get("location_code") != location_code:
                continue
            if disease_name and item.get("disease") != disease_name:
                continue
            item_date_text = str(item.get("date") or "")[:10]
            try:
                item_date = date.fromisoformat(item_date_text)
            except ValueError:
                continue
            if start and item_date < start:
                continue
            if end and item_date > end:
                continue
            items.append(item)
        return {
            **payload,
            "location_code": location_code,
            "disease": disease_name,
            "items": items,
        }

    @staticmethod
    def _pearson(items: list[dict[str, Any]], x_key: str, y_key: str) -> float | None:
        if len(items) < 3:
            return None
        xs = [float(item[x_key]) for item in items]
        ys = [float(item[y_key]) for item in items]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        x_sum = sum((x - x_mean) ** 2 for x in xs)
        y_sum = sum((y - y_mean) ** 2 for y in ys)
        denominator = math.sqrt(x_sum * y_sum)
        if denominator == 0:
            return None
        return round(numerator / denominator, 4)

    @staticmethod
    def _parse_optional_date(value: str | None, name: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(f"{name} 必须为 YYYY-MM-DD") from exc

    @staticmethod
    def _normalize_location(value: str, options: dict[str, Any]) -> str:
        cleaned = value.strip().upper()
        by_code = {item["code"].upper(): item for item in options.get("locations", [])}
        by_name = {item["name"].strip().upper(): item for item in options.get("locations", [])}
        if cleaned in by_code:
            return cleaned
        if cleaned in by_name:
            return by_name[cleaned]["code"].upper()
        raise ValidationError(f"location 参数无效: {value}")

    @staticmethod
    def _normalize_disease(value: str, options: dict[str, Any]) -> str:
        for disease in options.get("diseases", []):
            if disease.lower() == value.strip().lower():
                return disease
        raise ValidationError(f"disease 参数无效: {value}")

    @staticmethod
    def _normalize_model(value: str, options: dict[str, Any], disease: str | None = None) -> str:
        if disease:
            configured = options.get("availability", {}).get(disease, {}).get("models", [])
            models = set(configured or options.get("models", []))
        else:
            models = set(options.get("models", []))
        if value == "naive_rolling_7" and "moving_average" in models:
            return "moving_average"
        if value in models:
            return value
        raise ValidationError(f"model 参数无效: {value}")
