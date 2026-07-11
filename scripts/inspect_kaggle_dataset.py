from __future__ import annotations

import argparse
import csv
import json
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO


DATE_COLUMNS = {
    "date",
    "datetime",
    "observationdate",
    "observation_date",
    "last update",
    "last_update",
    "dt",
    "time",
}

REGION_COLUMNS = {
    "country",
    "country/region",
    "country_region",
    "country name",
    "country_name",
    "country/territory",
    "province/state",
    "province_state",
    "state",
    "city",
    "location",
    "iso_code",
    "country code",
    "country_code",
    "cca3",
}

ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")


@dataclass
class CsvProfile:
    source: str
    file_name: str
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    missing_rate: dict[str, float] = field(default_factory=dict)
    date_ranges: dict[str, dict[str, str | None]] = field(default_factory=dict)
    region_unique_counts: dict[str, int] = field(default_factory=dict)
    sample_rows: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


def decode_bytes(data: bytes) -> str:
    """尝试用常见编码解码 Kaggle CSV。"""
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"无法解码文件: {last_error}")


def normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def parse_date(value: str) -> datetime | None:
    """识别常见日期格式；识别失败返回 None，不猜测。"""
    if not value:
        return None
    text = value.strip()
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def profile_csv(handle: TextIO, source: str, file_name: str) -> CsvProfile:
    profile = CsvProfile(source=source, file_name=file_name)
    try:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        profile.columns = reader.fieldnames or []
        if not profile.columns:
            profile.error = "CSV 没有表头"
            return profile

        missing_counts = {column: 0 for column in profile.columns}
        date_min: dict[str, datetime] = {}
        date_max: dict[str, datetime] = {}
        region_values: dict[str, set[str]] = {}
        normalized_columns = {column: normalize(column) for column in profile.columns}
        date_candidates = [
            column
            for column, normalized in normalized_columns.items()
            if normalized in DATE_COLUMNS or "date" in normalized or normalized.endswith("_time")
        ]
        region_candidates = [
            column
            for column, normalized in normalized_columns.items()
            if normalized in REGION_COLUMNS or "country" in normalized or "region" in normalized
        ]

        for row in reader:
            profile.row_count += 1
            if len(profile.sample_rows) < 3:
                profile.sample_rows.append({column: row.get(column, "") for column in profile.columns[:12]})
            for column in profile.columns:
                value = row.get(column)
                if value is None or str(value).strip() == "":
                    missing_counts[column] += 1
            for column in date_candidates:
                parsed = parse_date(row.get(column, ""))
                if parsed is None:
                    continue
                date_min[column] = min(date_min.get(column, parsed), parsed)
                date_max[column] = max(date_max.get(column, parsed), parsed)
            for column in region_candidates:
                value = row.get(column, "").strip()
                if not value:
                    continue
                values = region_values.setdefault(column, set())
                if len(values) < 100000:
                    values.add(value)

        if profile.row_count:
            profile.missing_rate = {
                column: round(missing_counts[column] / profile.row_count, 6)
                for column in profile.columns
            }
        profile.date_ranges = {
            column: {
                "min": date_min[column].date().isoformat(),
                "max": date_max[column].date().isoformat(),
            }
            for column in date_min
        }
        profile.region_unique_counts = {
            column: len(values)
            for column, values in region_values.items()
        }
        return profile
    except Exception as exc:
        profile.error = str(exc)
        return profile


def iter_csv_sources(root: Path) -> Iterable[tuple[str, str, str]]:
    """遍历普通 CSV 和 ZIP 内 CSV，返回 source、文件名、文本内容。"""
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            data = path.read_bytes()
            yield str(path.relative_to(root)), path.name, decode_bytes(data)
        elif suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in sorted(zf.namelist()):
                    if name.lower().endswith(".csv"):
                        data = zf.read(name)
                        yield f"{path.relative_to(root)}::{name}", Path(name).name, decode_bytes(data)


def read_metadata(root: Path) -> list[dict]:
    """读取可能存在的 Kaggle dataset-metadata.json。"""
    items = []
    for path in sorted(root.rglob("dataset-metadata.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({"path": str(path.relative_to(root)), "metadata": data})
        except Exception as exc:
            items.append({"path": str(path.relative_to(root)), "error": str(exc)})
    return items


def write_markdown(output: Path, root: Path, profiles: list[CsvProfile], metadata: list[dict]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Kaggle 本地数据集检查报告")
    lines.append("")
    lines.append(f"检查目录：`{root}`")
    lines.append(f"CSV 文件数：{len(profiles)}")
    lines.append("")

    if metadata:
        lines.append("## dataset-metadata.json")
        lines.append("")
        for item in metadata:
            lines.append(f"- `{item['path']}`")
            meta = item.get("metadata") or {}
            if meta:
                lines.append(f"  - 标题：{meta.get('title') or meta.get('id') or '未提供'}")
                lines.append(f"  - 许可证：{meta.get('licenses') or meta.get('licenseName') or '未提供'}")
            if item.get("error"):
                lines.append(f"  - 读取错误：{item['error']}")
        lines.append("")

    for profile in profiles:
        lines.append(f"## {profile.source}")
        lines.append("")
        if profile.error:
            lines.append(f"- 读取错误：{profile.error}")
            lines.append("")
            continue
        lines.append(f"- 文件名：`{profile.file_name}`")
        lines.append(f"- 行数：{profile.row_count}")
        lines.append(f"- 字段数：{len(profile.columns)}")
        lines.append(f"- 字段名：`{', '.join(profile.columns)}`")
        if profile.date_ranges:
            lines.append("- 日期范围：")
            for column, bounds in profile.date_ranges.items():
                lines.append(f"  - `{column}`：{bounds['min']} 至 {bounds['max']}")
        else:
            lines.append("- 日期范围：未识别日期字段")
        if profile.region_unique_counts:
            lines.append("- 地区字段去重数量：")
            for column, count in profile.region_unique_counts.items():
                lines.append(f"  - `{column}`：{count}")
        else:
            lines.append("- 地区字段：未识别")
        if profile.missing_rate:
            worst = sorted(profile.missing_rate.items(), key=lambda item: item[1], reverse=True)[:10]
            lines.append("- 缺失率最高字段 Top 10：")
            for column, rate in worst:
                if math.isnan(rate):
                    continue
                lines.append(f"  - `{column}`：{rate:.2%}")
        if profile.sample_rows:
            lines.append("- 样例行：")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(profile.sample_rows, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="检查本地 Kaggle CSV/ZIP 数据集的字段、行数、日期范围和缺失率。")
    parser.add_argument("--root", default="data/raw/kaggle", help="Kaggle 数据集根目录")
    parser.add_argument("--output", default="docs/kaggle_local_inventory.md", help="Markdown 报告输出路径")
    parser.add_argument("--json-output", default="data/raw/kaggle_inventory.json", help="JSON 报告输出路径")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Directory not found: {root}. Download and unzip Kaggle datasets there first.")

    profiles: list[CsvProfile] = []
    for source, file_name, text in iter_csv_sources(root):
        from io import StringIO

        profiles.append(profile_csv(StringIO(text), source, file_name))

    metadata = read_metadata(root)
    write_markdown(Path(args.output), root, profiles, metadata)

    json_payload = {
        "root": str(root),
        "csv_count": len(profiles),
        "metadata": metadata,
        "profiles": [
            {
                "source": profile.source,
                "file_name": profile.file_name,
                "columns": profile.columns,
                "row_count": profile.row_count,
                "missing_rate": profile.missing_rate,
                "date_ranges": profile.date_ranges,
                "region_unique_counts": profile.region_unique_counts,
                "sample_rows": profile.sample_rows,
                "error": profile.error,
            }
            for profile in profiles
        ],
    }
    Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_output).write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成: {args.output}")
    print(f"已生成: {args.json_output}")


if __name__ == "__main__":
    main()
