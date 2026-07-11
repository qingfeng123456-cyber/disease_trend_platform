from __future__ import annotations

from datetime import date
from typing import Any


def parse_iso_date(value: str) -> date:
    """解析 ISO 日期，失败时抛出清晰异常。"""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"日期格式应为 YYYY-MM-DD，实际为: {value}") from exc


def standardize_location_code(value: str | None) -> str | None:
    """统一 ISO3 地区代码。"""
    if value is None:
        return None
    code = value.strip().upper()
    return code if len(code) == 3 and code.isalpha() else None


def build_disease_alias_map(alias_config: dict[str, list[str]]) -> dict[str, str]:
    """把病种别名配置展开为 alias -> 标准名。"""
    mapping: dict[str, str] = {}
    for standard, aliases in alias_config.items():
        mapping[standard.lower()] = standard
        for alias in aliases:
            mapping[str(alias).strip().lower()] = standard
    return mapping


def normalize_disease_name(value: str | None, alias_config: dict[str, list[str]]) -> str | None:
    """按配置统一疾病名称。"""
    if not value:
        return None
    mapping = build_disease_alias_map(alias_config)
    return mapping.get(value.strip().lower(), value.strip())


def clean_new_cases(value: Any) -> tuple[float | None, float | None, bool]:
    """保留原始病例值，同时把负数修订值截断为 0 供建模使用。"""
    if value is None or value == "":
        return None, None, False
    raw = float(value)
    return raw, max(raw, 0.0), raw < 0


def smape(actual: float, predicted: float) -> float:
    """单点 SMAPE，0/0 时返回 0。"""
    denom = abs(actual) + abs(predicted)
    if denom == 0:
        return 0.0
    return 2.0 * abs(predicted - actual) / denom
