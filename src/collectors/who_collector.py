from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from src.collectors.base_collector import BaseCollector
from src.common.exceptions import PlatformError, ValidationError


class WHOCollector(BaseCollector):
    """
    WHO GHO OData 采集器。

    自动发现并下载以下疾病相关指标：
    - covid：新冠肺炎 / COVID-19
    - influenza：流感 / influenza
    - tuberculosis：肺结核 / TB
    - hiv：HIV / AIDS

    示例：
        python -m src.collectors.who --diseases covid influenza tuberculosis hiv
        python -m src.collectors.who --search tuberculosis
        python -m src.collectors.who --indicators SDGTB
    """

    source_name = "who"
    base_url = "https://ghoapi.azureedge.net/api"

    DISEASE_KEYWORDS: dict[str, list[str]] = {
        "covid": [
            "covid",
            "covid-19",
            "sars-cov-2",
            "coronavirus",
        ],
        "influenza": [
            "influenza",
            "seasonal influenza",
            "seasonal flu",
        ],
        "tuberculosis": [
            "tuberculosis",
            "tuberculous",
            "tb",
        ],
        "hiv": [
            "hiv",
            "aids",
            "human immunodeficiency",
        ],
    }

    OUTPUT_FIELDS = [
        "source",
        "endpoint",
        "indicator_code",
        "indicator_name",
        "location_code",
        "location_name",
        "location_type",
        "year",
        "value",
        "numeric_value",
        "low",
        "high",
        "unit",
        "sex",
        "age",
        "publish_state",
        "raw_json",
    ]

    @staticmethod
    def pick(row: dict[str, Any], *keys: str) -> Any:
        """按候选字段顺序返回第一个非空值。"""
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def clean_code(value: str) -> str:
        """校验 WHO 指标代码，避免非法 URL/文件名。"""
        value = value.strip()
        if not value:
            raise ValidationError("WHO 指标代码不能为空。")

        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValidationError(f"非法 WHO 指标代码：{value}")

        return value

    @staticmethod
    def keyword_matches(text: str, keyword: str) -> bool:
        """Match complete terms so `flu`/`hiv` do not hit fluoride, flux or archived."""
        pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword.lower().strip())}(?![A-Za-z0-9])"
        return bool(re.search(pattern, text.lower()))

    def request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        """带重试的 WHO API 请求。"""
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()

                payload = response.json()
                if not isinstance(payload, dict):
                    raise PlatformError(f"WHO 返回内容不是 JSON 对象：{url}")

                return payload

            except Exception as error:
                last_error = error

                if attempt == retries:
                    break

                wait_seconds = 1.5 * (2**attempt)
                self.logger.warning(
                    "WHO 请求失败，第 %s/%s 次重试：%s",
                    attempt + 1,
                    retries,
                    error,
                )
                time.sleep(wait_seconds)

        raise PlatformError(f"WHO API 请求失败：{url}；原因：{last_error}")

    def fetch_all_indicator_metadata(
        self,
        *,
        page_size: int = 1000,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """
        下载 WHO 的 Indicator 指标目录。

        不依赖本地 YAML 配置；自动发现疾病指标时会调用此方法。
        """
        rows: list[dict[str, Any]] = []
        url = f"{self.base_url}/Indicator"
        params: dict[str, Any] | None = {"$top": page_size, "$skip": 0}

        for page_index in range(max_pages):
            payload = self.request_json(url, params=params)
            values = payload.get("value") or []

            if not isinstance(values, list):
                raise PlatformError("WHO /Indicator 返回格式错误：value 不是列表。")

            rows.extend(values)

            next_link = (
                payload.get("@odata.nextLink")
                or payload.get("odata.nextLink")
                or payload.get("nextLink")
            )

            if next_link:
                url = urljoin(f"{self.base_url}/", str(next_link))
                params = None
                continue

            if len(values) < page_size:
                break

            params = {
                "$top": page_size,
                "$skip": (page_index + 1) * page_size,
            }

        self.logger.info("WHO 指标目录读取完成，共 %s 条指标。", len(rows))
        return rows

    def search_indicators(
        self,
        keywords: list[str],
        *,
        max_pages: int = 20,
    ) -> list[dict[str, str]]:
        """在 WHO 指标目录中按关键词本地筛选指标。"""
        normalized_keywords = [item.lower().strip() for item in keywords if item.strip()]
        if not normalized_keywords:
            raise ValidationError("指标搜索关键词不能为空。")

        all_indicators = self.fetch_all_indicator_metadata(max_pages=max_pages)
        results: list[dict[str, str]] = []

        for row in all_indicators:
            code = str(
                self.pick(row, "IndicatorCode", "Indicator", "Code") or ""
            ).strip()
            name = str(
                self.pick(row, "IndicatorName", "Name", "Title") or ""
            ).strip()

            if not code:
                continue

            text = f"{code} {name}".lower()
            if any(self.keyword_matches(text, keyword) for keyword in normalized_keywords):
                results.append(
                    {
                        "indicator_code": code,
                        "indicator_name": name,
                    }
                )

        # 按指标代码去重。
        unique: dict[str, dict[str, str]] = {}
        for result in results:
            unique[result["indicator_code"]] = result

        return list(unique.values())

    def discover_disease_indicators(
        self,
        diseases: list[str],
        *,
        max_pages: int = 20,
    ) -> dict[str, list[dict[str, str]]]:
        """
        自动发现各疾病的 WHO 指标代码。

        注意：WHO 指标目录匹配到的是“候选指标”。
        后续 collect 会真正请求 endpoint；请求失败者写入 failed 清单。
        """
        invalid = [item for item in diseases if item not in self.DISEASE_KEYWORDS]
        if invalid:
            available = ", ".join(self.DISEASE_KEYWORDS)
            raise ValidationError(
                f"不支持的疾病键：{', '.join(invalid)}。可用值：{available}"
            )

        all_indicators = self.fetch_all_indicator_metadata(max_pages=max_pages)
        discovered: dict[str, list[dict[str, str]]] = {}

        for disease in diseases:
            keywords = self.DISEASE_KEYWORDS[disease]
            matched: dict[str, dict[str, str]] = {}

            for row in all_indicators:
                code = str(
                    self.pick(row, "IndicatorCode", "Indicator", "Code") or ""
                ).strip()
                name = str(
                    self.pick(row, "IndicatorName", "Name", "Title") or ""
                ).strip()

                if not code:
                    continue

                text = f"{code} {name}".lower()
                if any(self.keyword_matches(text, keyword) for keyword in keywords):
                    matched[code] = {
                        "indicator_code": code,
                        "indicator_name": name,
                    }

            discovered[disease] = list(matched.values())
            self.logger.info(
                "自动发现 %s 相关 WHO 指标 %s 个。",
                disease,
                len(discovered[disease]),
            )

        return discovered

    def fetch_pages(
        self,
        indicator: str,
        *,
        page_size: int = 1000,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """下载某一 WHO 指标 endpoint 的全部分页记录。"""
        indicator = self.clean_code(indicator)

        rows: list[dict[str, Any]] = []
        url = f"{self.base_url}/{indicator}"
        params: dict[str, Any] | None = {"$top": page_size, "$skip": 0}

        for page_index in range(max_pages):
            payload = self.request_json(url, params=params)
            values = payload.get("value") or []

            if not isinstance(values, list):
                raise PlatformError(
                    f"WHO 指标 {indicator} 返回格式错误：value 不是列表。"
                )

            rows.extend(values)

            next_link = (
                payload.get("@odata.nextLink")
                or payload.get("odata.nextLink")
                or payload.get("nextLink")
            )

            if next_link:
                url = urljoin(f"{self.base_url}/", str(next_link))
                params = None
                continue

            if len(values) < page_size:
                break

            params = {
                "$top": page_size,
                "$skip": (page_index + 1) * page_size,
            }
        else:
            self.logger.warning(
                "%s 达到 max_pages=%s，可能尚未下载完整。",
                indicator,
                max_pages,
            )

        return rows

    def normalize(
        self,
        row: dict[str, Any],
        *,
        endpoint: str,
        indicator_name: str | None,
    ) -> dict[str, Any]:
        """将 WHO 不同 endpoint 的记录统一为长表字段。"""
        return {
            "source": "WHO GHO OData",
            "endpoint": endpoint,
            "indicator_code": self.pick(
                row,
                "IndicatorCode",
                "Indicator",
            )
            or endpoint,
            "indicator_name": self.pick(
                row,
                "IndicatorName",
                "IndicatorLabel",
            )
            or indicator_name,
            "location_code": self.pick(
                row,
                "SpatialDim",
                "LocationCode",
                "CountryCode",
                "GEO_CODE",
            ),
            "location_name": self.pick(
                row,
                "SpatialDimText",
                "SpatialDimValue",
                "LocationName",
                "CountryName",
            ),
            "location_type": self.pick(
                row,
                "SpatialDimType",
                "LocationType",
            ),
            "year": self.pick(
                row,
                "TimeDim",
                "Year",
                "TIME_PERIOD",
            ),
            "value": self.pick(
                row,
                "NumericValue",
                "Value",
                "DisplayValue",
                "OBS_VALUE",
            ),
            "numeric_value": self.pick(
                row,
                "NumericValue",
                "OBS_VALUE",
            ),
            "low": self.pick(
                row,
                "Low",
                "LowerBound",
                "NumericValueLow",
            ),
            "high": self.pick(
                row,
                "High",
                "UpperBound",
                "NumericValueHigh",
            ),
            "unit": self.pick(
                row,
                "Unit",
                "UnitName",
                "ValueUnit",
            ),
            "sex": self.pick(row, "Sex", "SexCode", "DIM_SEX"),
            "age": self.pick(row, "Age", "AgeGroup", "DIM_AGE"),
            "publish_state": self.pick(row, "PublishState", "PUBLISHSTATE"),
            "raw_json": json.dumps(row, ensure_ascii=False, default=str),
        }

    def write_csv(
        self,
        *,
        disease: str,
        indicator_code: str,
        indicator_name: str,
        rows: list[dict[str, Any]],
    ) -> Path:
        """每个疾病—指标单独输出一个 CSV 与 meta 文件。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", indicator_code)
        output_path = self.output_dir / (
            f"who_{disease}_{safe_name}_{self.stamp()}.csv"
        )

        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        self.write_json(
            output_path.with_suffix(".csv.meta.json"),
            {
                "source": self.source_name,
                "disease": disease,
                "endpoint": indicator_code,
                "indicator_name": indicator_name,
                "rows": len(rows),
                "collected_at": self.utc_now(),
            },
        )
        return output_path

    def collect(
        self,
        *,
        diseases: list[str] | None = None,
        indicators: list[str] | None = None,
        page_size: int = 1000,
        max_pages: int = 100,
        catalog_max_pages: int = 20,
    ) -> list[Path]:
        """
        两种模式：

        1. 指定指标：
           --indicators SDGTB XXX

        2. 自动按疾病发现：
           --diseases covid influenza tuberculosis hiv
        """
        if not diseases and not indicators:
            raise ValidationError(
                "必须传入 --diseases 或 --indicators。"
                "例如：--diseases covid influenza tuberculosis hiv"
            )

        discovered: dict[str, list[dict[str, str]]] = {}

        if indicators:
            discovered["manual"] = [
                {
                    "indicator_code": self.clean_code(code),
                    "indicator_name": "",
                }
                for code in indicators
            ]

        if diseases:
            automatic = self.discover_disease_indicators(
                diseases,
                max_pages=catalog_max_pages,
            )
            for disease, items in automatic.items():
                discovered[disease] = items

        outputs: list[Path] = []
        manifest: dict[str, Any] = {
            "source": self.source_name,
            "collected_at": self.utc_now(),
            "success": [],
            "failed": [],
        }

        for disease, candidates in discovered.items():
            for item in candidates:
                code = item["indicator_code"]
                name = item["indicator_name"]

                try:
                    self.logger.info(
                        "开始采集：疾病=%s，指标=%s，名称=%s",
                        disease,
                        code,
                        name,
                    )

                    raw_rows = self.fetch_pages(
                        code,
                        page_size=page_size,
                        max_pages=max_pages,
                    )
                    normalized_rows = [
                        self.normalize(
                            row,
                            endpoint=code,
                            indicator_name=name,
                        )
                        for row in raw_rows
                    ]

                    output_path = self.write_csv(
                        disease=disease,
                        indicator_code=code,
                        indicator_name=name,
                        rows=normalized_rows,
                    )
                    outputs.append(output_path)

                    manifest["success"].append(
                        {
                            "disease": disease,
                            "indicator_code": code,
                            "indicator_name": name,
                            "rows": len(normalized_rows),
                            "file": str(output_path),
                        }
                    )
                    self.logger.info("采集成功：%s，共 %s 行。", code, len(raw_rows))

                except Exception as error:
                    # 一个指标失败不影响其余疾病或指标。
                    self.logger.warning("跳过不可采集指标 %s：%s", code, error)
                    manifest["failed"].append(
                        {
                            "disease": disease,
                            "indicator_code": code,
                            "indicator_name": name,
                            "error": str(error),
                        }
                    )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_dir / f"who_collection_manifest_{self.stamp()}.json"
        self.write_json(manifest_path, manifest)

        self.logger.info(
            "WHO 采集结束：成功 %s 个文件，失败 %s 个指标；清单：%s",
            len(manifest["success"]),
            len(manifest["failed"]),
            manifest_path,
        )
        return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WHO GHO 新冠、流感、肺结核、HIV/AIDS 数据采集器"
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--diseases",
        nargs="+",
        choices=["covid", "influenza", "tuberculosis", "hiv"],
        help="自动发现并采集的疾病。",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        help="直接指定 WHO 指标代码；与 --diseases 可以同时使用。",
    )
    parser.add_argument(
        "--search",
        nargs="+",
        help="仅搜索 WHO 指标目录，不下载数据。如：--search tuberculosis",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument(
        "--catalog-max-pages",
        type=int,
        default=20,
        help="WHO 指标目录最大分页数。",
    )
    args = parser.parse_args()

    collector = WHOCollector(args.output_dir)

    if args.search:
        results = collector.search_indicators(
            args.search,
            max_pages=args.catalog_max_pages,
        )
        print("indicator_code,indicator_name")
        for item in results:
            print(f'{item["indicator_code"]},"{item["indicator_name"]}"')
        print(f"\n共找到 {len(results)} 个候选指标。")
        return

    outputs = collector.collect(
        diseases=args.diseases,
        indicators=args.indicators,
        page_size=args.page_size,
        max_pages=args.max_pages,
        catalog_max_pages=args.catalog_max_pages,
    )

    print(f"\n采集完成，成功生成 {len(outputs)} 个 CSV 文件。")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
