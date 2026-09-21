#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source_probe.py

Проверяет доступность внешних источников для BETAGENT и сохраняет сырой ответ.
Нужен для честной проверки: что реально читается парсером, а что нет.

Проверяем:
1) the-sports.org  -> standings / таблица
2) livesport.com   -> форма / расписание / результаты
3) flashscore.info -> standings / h2h / stats

Что делает:
- делает GET-запрос
- сохраняет status code
- сохраняет кусок HTML
- пишет простой вывод в консоль
- сохраняет результаты в tests_output/

Запуск:
    python source_probe.py
"""

import json
import re
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT_DIR = Path("tests_output")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

SOURCES = [
    {
        "name": "the_sports_standings",
        "url": "https://www.the-sports.org/ice-hockey-kontinental-hockey-league-khl-2025-2026-results-eprd137186.html",
        "must_contain_any": ["Kontinental", "KHL", "Results", "Standings", "Металлург", "Динамо"],
    },
    {
        "name": "livesport_khl",
        "url": "https://www.livesport.com/hockey/russia/khl/",
        "must_contain_any": ["KHL", "standings", "results", "fixtures", "hockey", "Russia"],
    },
    {
        "name": "flashscore_info_khl",
        "url": "https://www.flashscore.info/ice-hockey/russia/khl/standings/",
        "must_contain_any": ["KHL", "standings", "head-to-head", "h2h", "form", "Russia"],
    },
]

def get_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s

def clean_preview(text: str, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text)
    return text[:limit]

def probe_source(session: requests.Session, source: dict) -> dict:
    name = source["name"]
    url = source["url"]
    must_contain_any = source["must_contain_any"]

    result = {
        "name": name,
        "url": url,
        "ok": False,
        "status_code": None,
        "contains_expected": False,
        "matched_tokens": [],
        "error": None,
        "content_length": 0,
        "preview": "",
        "saved_html": None,
    }

    try:
        r = session.get(url, timeout=25, verify=False)
        result["status_code"] = r.status_code
        html = r.text or ""
        result["content_length"] = len(html)

        preview = clean_preview(html)
        result["preview"] = preview

        lower_html = html.lower()
        matched = [token for token in must_contain_any if token.lower() in lower_html]
        result["matched_tokens"] = matched
        result["contains_expected"] = len(matched) > 0

        html_path = OUT_DIR / f"{name}.html"
        html_path.write_text(html, encoding="utf-8", errors="ignore")
        result["saved_html"] = str(html_path)

        result["ok"] = (r.status_code == 200 and len(html) > 500 and result["contains_expected"])
        return result

    except Exception as e:
        result["error"] = str(e)
        return result

def main():
    session = get_session()
    results = []

    print("Проверяем источники...\n")

    for source in SOURCES:
        print(f"-> {source['name']} | {source['url']}")
        res = probe_source(session, source)
        results.append(res)

        if res["ok"]:
            print(f"   ✅ OK | status={res['status_code']} | len={res['content_length']} | tokens={res['matched_tokens']}")
        else:
            print(f"   ❌ FAIL | status={res['status_code']} | error={res['error']} | tokens={res['matched_tokens']}")
        time.sleep(0.8)

    json_path = OUT_DIR / "source_probe_results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nГотово.")
    print(f"JSON-отчёт: {json_path}")
    print(f"HTML-файлы: {OUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
