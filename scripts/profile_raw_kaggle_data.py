from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M",
)
DATE_KEYWORDS = ("date", "datetime", "observationdate", "last update", "last_update", "dt")
REGION_KEYWORDS = ("country", "region", "province", "state", "city", "location", "admin", "combined_key")
CODE_KEYWORDS = ("iso", "code", "uid", "fips", "cca3")
LAT_LON_KEYWORDS = ("lat", "latitude", "long", "longitude")
YEAR_KEYWORDS = ("year",)


def open_text(path: Path):
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            handle = path.open("r", encoding=encoding, newline="")
            handle.read(4096)
            handle.seek(0)
            return handle, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            try:
                handle.close()
            except Exception:
                pass
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"cannot decode {path}: {last_error}")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def parse_date_value(value: str) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_number(value: str) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def detect_column_roles(columns: list[str]) -> dict[str, list[str]]:
    roles: dict[str, list[str]] = {
        "date": [],
        "country": [],
        "country_code": [],
        "province": [],
        "city": [],
        "latitude": [],
        "longitude": [],
        "year": [],
        "wide_date_columns": [],
    }
    for column in columns:
        n = norm(column)
        lower = column.strip().lower()
        if any(keyword in n for keyword in DATE_KEYWORDS):
            roles["date"].append(column)
        if "country" in n or n in {"region", "country_region"}:
            roles["country"].append(column)
        if any(keyword in n for keyword in CODE_KEYWORDS) and ("iso" in n or "code" in n or n in {"cca3"}):
            roles["country_code"].append(column)
        if "province" in n or "state" in n:
            roles["province"].append(column)
        if "city" in n:
            roles["city"].append(column)
        if n in {"lat", "latitude"}:
            roles["latitude"].append(column)
        if n in {"long", "longitude", "lon"}:
            roles["longitude"].append(column)
        if n in YEAR_KEYWORDS or re.fullmatch(r"\d{4}_population|\d{4}", n):
            roles["year"].append(column)
        if parse_date_value(column) is not None:
            roles["wide_date_columns"].append(column)
    return roles


def infer_value_type(value: str, *, is_date_candidate: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if is_date_candidate and parse_date_value(str(value)) is not None:
        return "date"
    number = parse_number(str(value))
    if number is not None:
        return "integer" if number.is_integer() else "float"
    return "string"


def merge_type(current: str | None, new: str | None) -> str | None:
    if new is None:
        return current
    if current is None:
        return new
    if current == new:
        return current
    if {current, new} <= {"integer", "float"}:
        return "float"
    return "string"


def numeric_anomaly_label(column: str, value: float) -> str | None:
    n = norm(column)
    if value < 0 and any(token in n for token in ("case", "death", "confirmed", "recovered", "active", "population")):
        return "negative_public_health_or_population_value"
    if n in {"lat", "latitude"} and not (-90 <= value <= 90):
        return "latitude_out_of_range"
    if n in {"long", "long_", "lon", "longitude"} and not (-180 <= value <= 180):
        return "longitude_out_of_range"
    if "humidity" in n and not (0 <= value <= 100):
        return "humidity_out_of_range"
    if "population" in n and value < 0:
        return "negative_population"
    return None


def profile_csv(path: Path, root: Path) -> dict[str, Any]:
    handle, encoding = open_text(path)
    with handle:
        handle.read(8192)
        handle.seek(0)
        # Kaggle 的这些文件均为标准逗号分隔 CSV；固定 csv.excel 可避免
        # Sniffer 在 JHU 宽表字段里误判分隔符。
        dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        columns = reader.fieldnames or []
        roles = detect_column_roles(columns)
        missing = {column: 0 for column in columns}
        type_guess = {column: None for column in columns}
        numeric_stats: dict[str, dict[str, Any]] = {
            column: {"min": None, "max": None, "negative_count": 0, "zero_count": 0, "anomaly_count": 0, "anomaly_examples": []}
            for column in columns
        }
        date_ranges: dict[str, dict[str, str | None]] = {}
        region_values: dict[str, set[str]] = defaultdict(set)
        duplicate_hashes: set[str] = set()
        duplicate_count = 0
        first_5_rows: list[dict[str, str]] = []
        first_5_rows_truncated: list[dict[str, str]] = []
        row_count = 0
        future_date_count = 0
        today = date.today()

        wide_dates = [parse_date_value(column) for column in roles["wide_date_columns"]]
        wide_dates = [item for item in wide_dates if item is not None]
        date_candidate_columns = set(roles["date"])
        if wide_dates:
            date_ranges["wide_date_columns"] = {"min": min(wide_dates).isoformat(), "max": max(wide_dates).isoformat()}
            future_date_count += sum(1 for item in wide_dates if item > today)

        for row in reader:
            row_count += 1
            ordered_values = [str(row.get(column, "") or "") for column in columns]
            row_hash = hashlib.sha1("\x1f".join(ordered_values).encode("utf-8", errors="replace")).hexdigest()
            if row_hash in duplicate_hashes:
                duplicate_count += 1
            else:
                duplicate_hashes.add(row_hash)

            if len(first_5_rows) < 5:
                first_5_rows.append({column: row.get(column, "") for column in columns})
                first_5_rows_truncated.append({column: row.get(column, "") for column in columns[:20]})

            for column in columns:
                value = row.get(column, "")
                if value is None or str(value).strip() == "":
                    missing[column] += 1
                    continue
                is_date_candidate = column in date_candidate_columns
                type_guess[column] = merge_type(type_guess[column], infer_value_type(str(value), is_date_candidate=is_date_candidate))
                if is_date_candidate:
                    parsed_date = parse_date_value(str(value))
                    if parsed_date is not None:
                        current = date_ranges.setdefault(column, {"min": None, "max": None})
                        current["min"] = parsed_date.isoformat() if current["min"] is None else min(current["min"], parsed_date.isoformat())
                        current["max"] = parsed_date.isoformat() if current["max"] is None else max(current["max"], parsed_date.isoformat())
                        if parsed_date > today:
                            future_date_count += 1
                number = parse_number(str(value))
                if number is not None:
                    stats = numeric_stats[column]
                    stats["min"] = number if stats["min"] is None else min(stats["min"], number)
                    stats["max"] = number if stats["max"] is None else max(stats["max"], number)
                    if number < 0:
                        stats["negative_count"] += 1
                    if number == 0:
                        stats["zero_count"] += 1
                    label = numeric_anomaly_label(column, number)
                    if label:
                        stats["anomaly_count"] += 1
                        if len(stats["anomaly_examples"]) < 5:
                            stats["anomaly_examples"].append({"row": row_count, "value": number, "reason": label})

            for column in roles["country"] + roles["country_code"] + roles["province"] + roles["city"]:
                value = row.get(column, "")
                if value and len(region_values[column]) < 200000:
                    region_values[column].add(value.strip())

        missing_rate = {
            column: round(missing[column] / row_count, 6) if row_count else 0.0
            for column in columns
        }
        data_types = {column: type_guess[column] or "all_missing" for column in columns}
        compact_numeric_stats = {
            column: stats
            for column, stats in numeric_stats.items()
            if stats["min"] is not None
        }
        region_counts = {column: len(values) for column, values in region_values.items()}

        return {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "absolute_path": str(path),
            "size_bytes": path.stat().st_size,
            "encoding": encoding,
            "row_count": row_count,
            "column_count": len(columns),
            "columns": columns,
            "first_5_rows": first_5_rows,
            "first_5_rows_truncated_to_20_columns": first_5_rows_truncated,
            "data_types": data_types,
            "date_ranges": date_ranges,
            "future_date_count": future_date_count,
            "region_unique_counts": region_counts,
            "missing_rate": missing_rate,
            "duplicate_row_count": duplicate_count,
            "numeric_stats": compact_numeric_stats,
            "association_keys": roles,
        }


def classify_dataset(profile: dict[str, Any]) -> str:
    path = profile["path"].lower()
    columns = {norm(column) for column in profile["columns"]}
    if "weather" in path or {"temperature", "humidity", "pressure"} & columns:
        return "weather"
    if "population" in path or "2022_population" in columns or "cca3" in columns:
        return "population"
    if "covid" in path or {"confirmed", "deaths", "recovered"} & columns:
        return "epidemic"
    return "unknown"


def score_profile(profile: dict[str, Any]) -> dict[str, Any]:
    kind = classify_dataset(profile)
    keys = profile["association_keys"]
    score = 0
    reasons: list[str] = []
    if kind == "epidemic":
        if keys["date"] or keys["wide_date_columns"]:
            score += 3
            reasons.append("has date or wide date columns")
        if keys["country"]:
            score += 3
            reasons.append("has country field")
        if {"Confirmed", "Deaths", "Recovered"} & set(profile["columns"]):
            score += 3
            reasons.append("has confirmed/deaths/recovered fields")
        if profile["row_count"] > 10000:
            score += 1
            reasons.append("enough rows for time series")
    elif kind == "weather":
        if keys["date"]:
            score += 3
            reasons.append("has datetime column")
        if "temperature" in profile["path"].lower():
            score += 3
            reasons.append("temperature table available")
        if profile["row_count"] > 10000:
            score += 1
            reasons.append("hourly time series is large enough")
    elif kind == "population":
        if keys["country_code"]:
            score += 3
            reasons.append("has country code")
        if keys["country"]:
            score += 2
            reasons.append("has country name")
        if any("population" in norm(column) for column in profile["columns"]):
            score += 3
            reasons.append("has population columns")
    return {"kind": kind, "score": score, "reasons": reasons}


def best_profiles(profiles: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    scored = [{**profile, "_score": score_profile(profile)} for profile in profiles]
    result: dict[str, dict[str, Any] | None] = {"epidemic": None, "weather": None, "population": None}
    for kind in result:
        candidates = [profile for profile in scored if profile["_score"]["kind"] == kind]
        if candidates:
            result[kind] = sorted(candidates, key=lambda item: (item["_score"]["score"], item["row_count"]), reverse=True)[0]
    return result


def build_cross_dataset_checks(profiles: list[dict[str, Any]], selected: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "join_feasibility": [],
        "risks": [],
    }
    epidemic = selected.get("epidemic")
    weather = selected.get("weather")
    population = selected.get("population")
    if epidemic and population:
        epi_keys = epidemic["association_keys"]
        pop_keys = population["association_keys"]
        if epi_keys["country"] and (pop_keys["country"] or pop_keys["country_code"]):
            checks["join_feasibility"].append("epidemic <-> population: join by normalized country name; population CCA3 can help after mapping")
        else:
            checks["risks"].append("epidemic and population lack a direct shared country key")
    if epidemic and weather:
        epi_keys = epidemic["association_keys"]
        weather_keys = weather["association_keys"]
        if weather_keys["date"] and weather_keys["city"]:
            checks["join_feasibility"].append("epidemic <-> weather: aggregate weather hourly datetime to daily city data, then map city to country before joining by date")
            checks["risks"].append("weather data is city-based while epidemic data is country/province-based; a city-to-country mapping is required")
        elif weather_keys["date"] and weather_keys["country"]:
            checks["join_feasibility"].append("epidemic <-> weather: join by normalized country and date after daily aggregation")
        else:
            checks["risks"].append("weather table does not expose a direct country/date join key")
    for profile in profiles:
        if profile["future_date_count"]:
            checks["risks"].append(f"{profile['path']}: contains future dates")
        negative_columns = [
            column for column, stats in profile["numeric_stats"].items()
            if stats.get("negative_count", 0) > 0 and any(token in norm(column) for token in ("case", "death", "confirmed", "recovered", "active", "population"))
        ]
        if negative_columns:
            checks["risks"].append(f"{profile['path']}: negative public-health/population values in {negative_columns}")
    return checks


def md_table_row(values: list[Any]) -> str:
    return "| " + " | ".join(str(value).replace("\n", " ") for value in values) + " |"


def write_profile_markdown(path: Path, root: Path, profiles: list[dict[str, Any]], selected: dict[str, dict[str, Any] | None], checks: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Raw Kaggle 数据画像")
    lines.append("")
    lines.append(f"扫描目录：`{root}`")
    lines.append(f"CSV 文件数量：{len(profiles)}")
    lines.append("")
    lines.append("## 文件总览")
    lines.append("")
    lines.append(md_table_row(["文件", "大小 MB", "行数", "列数", "类型判断", "日期范围", "地区字段"]))
    lines.append(md_table_row(["---", "---:", "---:", "---:", "---", "---", "---"]))
    for profile in profiles:
        score = score_profile(profile)
        date_range_text = "; ".join(
            f"{col}: {rng.get('min')}~{rng.get('max')}"
            for col, rng in profile["date_ranges"].items()
        ) or "未识别"
        region_text = "; ".join(f"{col}={count}" for col, count in profile["region_unique_counts"].items()) or "未识别"
        lines.append(
            md_table_row([
                f"`{profile['path']}`",
                f"{profile['size_bytes'] / 1024 / 1024:.2f}",
                profile["row_count"],
                profile["column_count"],
                score["kind"],
                date_range_text,
                region_text,
            ])
        )
    lines.append("")

    lines.append("## 推荐主表")
    lines.append("")
    for kind, label in [("epidemic", "疫情主表"), ("weather", "天气表"), ("population", "人口/社会经济表")]:
        profile = selected.get(kind)
        if profile:
            lines.append(f"- {label}：`{profile['path']}`")
        else:
            lines.append(f"- {label}：未找到合适候选")
    lines.append("")

    for profile in profiles:
        lines.append(f"## {profile['path']}")
        lines.append("")
        lines.append(f"- 文件大小：{profile['size_bytes']} bytes ({profile['size_bytes'] / 1024 / 1024:.2f} MB)")
        lines.append(f"- 行数/列数：{profile['row_count']} 行，{profile['column_count']} 列")
        lines.append(f"- 编码：{profile['encoding']}")
        lines.append(f"- 字段名：`{', '.join(profile['columns'])}`")
        lines.append(f"- 重复行数量：{profile['duplicate_row_count']}")
        if profile["date_ranges"]:
            lines.append("- 日期范围：")
            for column, bounds in profile["date_ranges"].items():
                lines.append(f"  - `{column}`：{bounds.get('min')} 至 {bounds.get('max')}")
        else:
            lines.append("- 日期范围：未识别")
        if profile["region_unique_counts"]:
            lines.append("- 地区数量：")
            for column, count in profile["region_unique_counts"].items():
                lines.append(f"  - `{column}`：{count}")
        else:
            lines.append("- 地区数量：未识别")
        lines.append("- 可作为关联键的字段：")
        for key, values in profile["association_keys"].items():
            if values:
                preview = values[:12]
                suffix = " ..." if len(values) > 12 else ""
                lines.append(f"  - `{key}`：`{', '.join(preview)}`{suffix}")
        worst_missing = sorted(profile["missing_rate"].items(), key=lambda item: item[1], reverse=True)[:12]
        lines.append("- 缺失率最高字段：")
        for column, rate in worst_missing:
            lines.append(f"  - `{column}`：{rate:.2%}")
        lines.append("- 数据类型：")
        for column, dtype in list(profile["data_types"].items())[:40]:
            lines.append(f"  - `{column}`：{dtype}")
        if len(profile["data_types"]) > 40:
            lines.append("  - 其余字段详见 JSON 报告。")
        numeric_items = list(profile["numeric_stats"].items())
        if numeric_items:
            lines.append("- 数值字段统计：")
            for column, stats in numeric_items[:30]:
                anomaly = f", anomaly_count={stats['anomaly_count']}" if stats["anomaly_count"] else ""
                lines.append(
                    f"  - `{column}`：min={stats['min']}, max={stats['max']}, "
                    f"negative_count={stats['negative_count']}, zero_count={stats['zero_count']}{anomaly}"
                )
            if len(numeric_items) > 30:
                lines.append("  - 其余数值字段详见 JSON 报告。")
        lines.append("- 前 5 行预览：")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(profile["first_5_rows_truncated_to_20_columns"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    lines.append("## 跨数据集关联检查")
    lines.append("")
    if checks["join_feasibility"]:
        lines.append("可行关联：")
        for item in checks["join_feasibility"]:
            lines.append(f"- {item}")
    if checks["risks"]:
        lines.append("")
        lines.append("发现的风险：")
        for item in checks["risks"]:
            lines.append(f"- {item}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cleaning_plan(path: Path, selected: dict[str, dict[str, Any] | None], checks: dict[str, Any]) -> None:
    epidemic = selected.get("epidemic")
    weather = selected.get("weather")
    population = selected.get("population")
    lines: list[str] = []
    lines.append("# Kaggle 原始数据清洗计划")
    lines.append("")
    lines.append("本计划基于实际读取 `data/raw/kaggle` 中 CSV 后生成。本阶段不修改 Spark 作业。")
    lines.append("")
    lines.append("## 1. 推荐使用文件")
    lines.append("")
    lines.append(f"- 疫情主表：`{epidemic['path'] if epidemic else '未选择'}`")
    lines.append(f"- 天气表：`{weather['path'] if weather else '未选择'}`")
    lines.append(f"- 人口/社会经济表：`{population['path'] if population else '未选择'}`")
    lines.append("")
    lines.append("## 2. 关联方式")
    lines.append("")
    if epidemic and population:
        lines.append("- 疫情表与人口表：优先把疫情表国家名标准化，再与人口表 `CCA3`/国家名映射关联。")
    if epidemic and weather:
        lines.append("- 疫情表与天气表：天气数据先按小时聚合为日频，再把城市映射到国家，最后按 `date + country` 关联。")
    lines.append("- 如果后续补充 ISO3 映射表，应统一输出 `location_code`。")
    lines.append("")
    lines.append("## 3. 字段处理建议")
    lines.append("")
    if epidemic:
        cols = epidemic["columns"]
        lines.append("### 疫情主表")
        lines.append("")
        lines.append("- 保留/转换：")
        if "ObservationDate" in cols:
            lines.append("  - `ObservationDate` -> `date`，转换为 `YYYY-MM-DD`。")
        if "Country/Region" in cols:
            lines.append("  - `Country/Region` -> `location`，后续映射为 `location_code`。")
        if "Province/State" in cols:
            lines.append("  - `Province/State` -> `province`，国家级分析可为空或聚合。")
        for old, new in [("Confirmed", "total_cases"), ("Deaths", "total_deaths"), ("Recovered", "total_recovered")]:
            if old in cols:
                lines.append(f"  - `{old}` -> `{new}`，属于累计值。")
        lines.append("- 注意：当前主表多为累计值，需要按地区和日期排序后用差分计算新增值，不能把累计值直接当新增病例。")
        lines.append("- 删除或暂不进入模型：`SNo`、`Last Update`。")
        if epidemic["duplicate_row_count"]:
            lines.append("- 存在完全重复行，需先去重。")
    if weather:
        lines.append("")
        lines.append("### 天气表")
        lines.append("")
        lines.append("- `datetime` -> `date`，小时级聚合为日频。")
        lines.append("- `temperature.csv` 通常为开尔文温度，需转换为摄氏度：`temperature_c = temperature_k - 273.15`。")
        lines.append("- `humidity.csv` 单位通常为百分比，需检查 0-100 合法范围。")
        lines.append("- 需要读取 `city_attributes.csv` 获取城市、国家、经纬度，再和天气宽表按城市列关联。")
        lines.append("- 天气表是宽表，城市在列上，清洗时应转换成长表：`date, city, value`。")
    if population:
        lines.append("")
        lines.append("### 人口/社会经济表")
        lines.append("")
        lines.append("- `Country/Territory` -> `location`。")
        lines.append("- `CCA3` -> `location_code`。")
        lines.append("- `2022 Population`、`2020 Population` 等年份列应转换成长表：`location_code, year, population`。")
        lines.append("- `Density (per km²)` 可保留为人口密度特征。")
    lines.append("")
    lines.append("## 4. 需要重点检查的问题")
    lines.append("")
    issues = checks["risks"] or ["未在自动画像中发现严重问题，但仍需人工抽样核查。"]
    for item in issues:
        lines.append(f"- {item}")
    lines.append("- 国家名称不一致：疫情表国家名与人口表国家名可能不同，应建立国家名到 ISO3 的映射。")
    lines.append("- 日期格式不一致：疫情表可能是 `MM/DD/YYYY`，天气表可能是 `YYYY-MM-DD HH:MM:SS`。")
    lines.append("- 数据泄漏风险：预测目标必须用未来值构造，但输入特征只能使用当前日及历史日；累计值差分必须只用历史相邻日期。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile raw Kaggle CSV files without loading them all into memory.")
    parser.add_argument("--root", default="data/raw/kaggle")
    parser.add_argument("--profile-md", default="docs/raw_data_profile.md")
    parser.add_argument("--plan-md", default="docs/data_cleaning_plan.md")
    parser.add_argument("--json-output", default="data/serving/raw_data_profile.json")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Directory not found: {root}")
    csv_files = sorted(path for path in root.rglob("*.csv") if path.is_file())
    profiles = [profile_csv(path, root) for path in csv_files]
    selected = best_profiles(profiles)
    checks = build_cross_dataset_checks(profiles, selected)

    payload = {
        "root": str(root),
        "csv_count": len(profiles),
        "files": profiles,
        "selected": {
            key: (value["path"] if value else None)
            for key, value in selected.items()
        },
        "cross_dataset_checks": checks,
    }
    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_profile_markdown(Path(args.profile_md), root, profiles, selected, checks)
    write_cleaning_plan(Path(args.plan_md), selected, checks)
    print(f"profile_md={args.profile_md}")
    print(f"plan_md={args.plan_md}")
    print(f"json={args.json_output}")
    print(json.dumps(payload["selected"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
