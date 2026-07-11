from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.collectors.base_collector import BaseCollector
from src.common.config import get_setting
from src.common.http_client import save_bytes_with_metadata

KEYWORDS = ("法定传染病", "流感监测周报", "流感流行情况概要", "急性呼吸道传染病哨点监测")


class ChinaCDCCollector(BaseCollector):
    """低频归档中国疾控中心公开页面和附件，不绕过登录、验证码或限制。"""

    source_name = "china_cdc"

    @staticmethod
    def safe_name(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def extract_metadata(url: str, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        title = soup.find(["h1", "h2"])
        title_text = title.get_text(" ", strip=True) if title else (soup.title.get_text(" ", strip=True) if soup.title else "")
        text = soup.get_text("\n", strip=True)
        date_match = re.search(r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?", text)
        published_date = None
        if date_match:
            published_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        attachments = []
        for link in soup.find_all("a", href=True):
            href = urljoin(url, link["href"])
            if re.search(r"\.(pdf|docx?|xlsx?|csv|xls)(\?|$)", href, re.I):
                attachments.append(href)
        return {
            "page_url": url,
            "title": title_text,
            "published_date": published_date,
            "stat_period": None,
            "disease_type": None,
            "attachment_urls": sorted(set(attachments)),
            "text_preview": text[:800],
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

    def collect(self, *, max_detail_pages: int | None = None, download_attachments: bool = True) -> Path:
        start_urls = list(get_setting(self.settings, "collectors.china_cdc.start_urls", []))
        max_detail_pages = max_detail_pages or int(get_setting(self.settings, "collectors.china_cdc.max_detail_pages", 80))
        delay = float(get_setting(self.settings, "collectors.request_interval", 1.5))
        html_dir = self.output_dir / "html"
        attachment_dir = self.output_dir / "attachments"
        html_dir.mkdir(parents=True, exist_ok=True)
        attachment_dir.mkdir(parents=True, exist_ok=True)
        candidates: dict[str, str] = {}
        for start_url in start_urls:
            response = self.client.get(start_url)
            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "lxml")
            for link in soup.find_all("a", href=True):
                text = link.get_text(" ", strip=True)
                if any(keyword in text for keyword in KEYWORDS):
                    detail_url = urljoin(start_url, link["href"])
                    if urlparse(detail_url).netloc.endswith("chinacdc.cn"):
                        candidates[detail_url] = text

        records = []
        for index, (url, anchor_title) in enumerate(list(candidates.items())[:max_detail_pages], start=1):
            try:
                response = self.client.get(url)
                response.encoding = response.apparent_encoding or "utf-8"
                html = response.text
                html_path = html_dir / f"{self.safe_name(url)}.html"
                html_path.write_text(html, encoding="utf-8")
                metadata = self.extract_metadata(url, html)
                metadata["anchor_title"] = anchor_title
                metadata["local_html_path"] = str(html_path.relative_to(self.output_dir))
                metadata["local_attachment_paths"] = []
                if download_attachments:
                    for attachment_url in metadata["attachment_urls"]:
                        if not urlparse(attachment_url).netloc.endswith("chinacdc.cn"):
                            continue
                        suffix = Path(urlparse(attachment_url).path).suffix or ".bin"
                        attachment_path = attachment_dir / f"{self.safe_name(attachment_url)}{suffix}"
                        try:
                            attachment_response = self.client.get(attachment_url)
                            save_bytes_with_metadata(
                                attachment_response.content,
                                attachment_path,
                                source_url=attachment_url,
                                extra={"page_url": url},
                            )
                            metadata["local_attachment_paths"].append(str(attachment_path.relative_to(self.output_dir)))
                        except Exception as exc:
                            metadata.setdefault("attachment_errors", []).append({"url": attachment_url, "error": str(exc)})
                records.append(metadata)
                self.logger.info("China CDC %s/%s %s", index, min(len(candidates), max_detail_pages), metadata["title"][:40])
            except Exception as exc:
                records.append({"page_url": url, "anchor_title": anchor_title, "parse_error": str(exc), "downloaded_at": self.utc_now()})
            time.sleep(delay)
        output_path = self.output_dir / "page_metadata.jsonl"
        self.write_jsonl(output_path, records)
        self.write_json(
            self.output_dir / "manual_review_note.json",
            {
                "message": "中国疾控页面结构不完全一致，无法稳定解析的 HTML/PDF/Excel 应人工核查后再结构化。",
                "records": len(records),
                "collected_at": self.utc_now(),
            },
        )
        return output_path


def collect(output_dir: str | Path | None = None) -> Path:
    return ChinaCDCCollector(output_dir).collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-detail-pages", type=int, default=None)
    parser.add_argument("--no-attachments", action="store_true")
    args = parser.parse_args()
    ChinaCDCCollector(args.output_dir).collect(
        max_detail_pages=args.max_detail_pages,
        download_attachments=not args.no_attachments,
    )


if __name__ == "__main__":
    main()
