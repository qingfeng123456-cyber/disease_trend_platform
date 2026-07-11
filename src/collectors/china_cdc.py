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

from src.common.config import ensure_dir, load_settings
from src.common.http import get_with_retry

START_URLS = [
    "https://www.chinacdc.cn/jksj/",
    "https://www.chinacdc.cn/jksj/jksj04_14249/",
    "https://www.chinacdc.cn/jksj/jksj04_14275/",
]
KEYWORDS = (
    "法定传染病",
    "流感监测周报",
    "流感流行情况概要",
    "急性呼吸道传染病哨点监测",
)


def _safe_name(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def _extract_metadata(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    h1 = soup.find(["h1", "h2"])
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)
    text = soup.get_text("\n", strip=True)
    date_match = re.search(r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?", text)
    published_date = None
    if date_match:
        published_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    attachments = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if re.search(r"\.(pdf|docx?|xlsx?|csv)(\?|$)", href, re.I):
            attachments.append(href)
    return {
        "url": url,
        "title": title,
        "published_date": published_date,
        "attachments": sorted(set(attachments)),
        "text_preview": text[:1200],
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def collect(output_dir: str | Path | None = None, max_detail_pages: int = 80) -> Path:
    settings = load_settings()
    base = ensure_dir(output_dir or settings["paths"]["local_raw"]) / "china_cdc"
    html_dir = base / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)

    candidate_urls: dict[str, str] = {}
    for start_url in START_URLS:
        response = get_with_retry(start_url)
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "lxml")
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if any(keyword in title for keyword in KEYWORDS):
                detail_url = urljoin(start_url, a["href"])
                if urlparse(detail_url).netloc.endswith("chinacdc.cn"):
                    candidate_urls[detail_url] = title

    records = []
    for index, (url, anchor_title) in enumerate(list(candidate_urls.items())[:max_detail_pages], start=1):
        try:
            response = get_with_retry(url)
            response.encoding = response.apparent_encoding or "utf-8"
            html = response.text
            filename = html_dir / f"{_safe_name(url)}.html"
            filename.write_text(html, encoding="utf-8")
            metadata = _extract_metadata(url, html)
            metadata["anchor_title"] = anchor_title
            metadata["local_html"] = str(filename)
            records.append(metadata)
            print(f"[China CDC] {index}/{min(len(candidate_urls), max_detail_pages)} {metadata['title'][:50]}")
        except Exception as exc:
            records.append(
                {
                    "url": url,
                    "anchor_title": anchor_title,
                    "parse_error": str(exc),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        time.sleep(float(settings["collection"]["polite_delay_seconds"]))

    output_path = base / "page_metadata.jsonl"
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[China CDC] 元数据保存: {output_path}; 共 {len(records)} 条")
    print("提示：本脚本只做低频原始页面归档。结构化表格解析应在抽样检查页面后单独实现。")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-detail-pages", type=int, default=80)
    args = parser.parse_args()
    collect(args.output_dir, args.max_detail_pages)


if __name__ == "__main__":
    main()
