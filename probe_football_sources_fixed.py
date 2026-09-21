#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
probe_football_sources_fixed.py

Проверяет источники данных для футбола с фокусом на РПЛ.
Что исправлено:
- TheSports URL заменены на рабочие страницы РПЛ 2025/2026
- football-data.org не проверяется по неверному коду PPL
- OpenLigaDB Bundesliga убран из отчёта по РПЛ, чтобы не шумел
- Flashscore оставлен как fallback / HTML-source
"""

import json
import os
import re
from pathlib import Path

import requests

OUT_DIR = Path("tests_output")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

SOURCES = [
    {
        "name": "the_sports_rpl_home",
        "url": "https://www.the-sports.org/football-soccer-2025-2026-russia-division-1-russian-premier-league-epr136873.html",
        "tokens": ["Regular Season", "Russian Premier League", "Spartak Moscow", "Zenit", "Standings"],
    },
    {
        "name": "the_sports_rpl_results",
        "url": "https://www.the-sports.org/football-soccer-russia-division-1-russian-premier-league-2025-2026-results-eprd136876.html",
        "tokens": ["Detailed results", "Standings", "Russian Premier League", "Spartak Moscow", "Zenit"],
    },
    {
        "name": "flashscore_rpl",
        "url": "https://www.flashscore.com/football/russia/premier-league/standings/",
        "tokens": ["Russian Premier League", "standings", "table"],
    },
    {
        "name": "football_data_rpl_check",
        "url": "https://api.football-data.org/v4/competitions/RFPL/standings",
        "tokens": ["standings", "table", "competition"],
        "headers": {
            "X-Auth-Token": os.getenv("FOOTBALL_DATA_API_KEY", ""),
        },
        "expect_auth_or_paid": True,
    },
]

def fetch_source(source: dict) -> dict:
    headers = dict(HEADERS)
    headers.update(source.get("headers", {}))

    try:
        resp = requests.get(source["url"], headers=headers, timeout=25)
        text = resp.text or ""
        ok = resp.status_code == 200 and all(tok.lower() in text.lower() for tok in source["tokens"])

        result = {
            "name": source["name"],
            "url": source["url"],
            "status_code": resp.status_code,
            "ok": ok,
            "content_length": len(text),
            "tokens": source["tokens"],
            "preview": text[:400],
        }

        if source.get("expect_auth_or_paid") and resp.status_code in (401, 403):
            result["note"] = "Источник существует, но доступ ограничен тарифом/авторизацией"
        return result
    except Exception as e:
        return {
            "name": source["name"],
            "url": source["url"],
            "status_code": None,
            "ok": False,
            "content_length": 0,
            "tokens": source["tokens"],
            "preview": "",
            "error": str(e),
        }

def main():
    print("Проверяем источники для футбола (РПЛ и fallback)...\n")
    results = []

    for source in SOURCES:
        print(f"→ {source['name']}")
        res = fetch_source(source)
        results.append(res)

        if res["ok"]:
            print(f"  ✅ OK | status={res['status_code']} | len={res['content_length']} | tokens={res['tokens']}")
            preview = re.sub(r"\\s+", " ", res["preview"]).strip()
            print(f"  Preview: {preview[:180]}")
        else:
            extra = f", note={res['note']}" if res.get("note") else ""
            err = f", error={res['error']}" if res.get("error") else ""
            print(f"  ❌ FAIL | status={res['status_code']}, tokens={res['tokens']}{extra}{err}")
        print()

    report_path = OUT_DIR / "football_sources_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    ok_sources = [r for r in results if r["ok"]]
    print("=" * 50)
    print(f"Рабочих источников: {len(ok_sources)}")
    for r in ok_sources:
        print(f"  ✅ {r['name']}")
    print()
    print(f"Отчёт: {report_path}")

if __name__ == "__main__":
    main()
