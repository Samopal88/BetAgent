#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_football_sources.py

Проверяет доступность источников для футбольных данных
которых нет в football-data.org (РПЛ и другие лиги).

Запуск: python probe_football_sources.py
"""

import requests
import urllib3
import json
from pathlib import Path

urllib3.disable_warnings()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

OUT = Path("tests_output")
OUT.mkdir(exist_ok=True)

SOURCES = [
    # TheSports — РПЛ (как для КХЛ)
    {
        "name": "the_sports_rpl",
        "url": "https://www.the-sports.org/football-russia-premier-league-2025-2026-results-dtrd202669.html",
        "tokens": ["Зенит", "Спартак", "Краснодар", "ЦСКА", "standings", "results"],
    },
    # TheSports — общий поиск РПЛ
    {
        "name": "the_sports_rpl_v2",
        "url": "https://www.the-sports.org/football-russia-premier-league-results-dtrd99498.html",
        "tokens": ["Зенит", "Спартак", "Краснодар", "standings"],
    },
    # OpenLigaDB — бесплатный немецкий API (Бундеслига и другие)
    {
        "name": "openligadb_bl1",
        "url": "https://api.openligadb.de/getbltable/bl1/2025",
        "tokens": ["Bayern", "Dortmund", "Points", "teamName"],
    },
    # football-data.org — проверяем покрытие РПЛ
    {
        "name": "football_data_rpl_check",
        "url": "https://api.football-data.org/v4/competitions/PPL/standings",
        "tokens": ["standings", "table"],
    },
    # Sofascore API (неофициальный)
    {
        "name": "sofascore_rpl",
        "url": "https://api.sofascore.com/api/v1/unique-tournament/203/season/63814/standings/total",
        "tokens": ["standings", "rows", "team"],
    },
    # livesport / flashscore
    {
        "name": "flashscore_rpl",
        "url": "https://www.flashscore.com/football/russia/premier-league/",
        "tokens": ["standings", "table", "Зенит", "Спартак"],
    },
]

def probe(source):
    name = source["name"]
    url = source["url"]
    tokens = source["tokens"]

    try:
        r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        status = r.status_code
        text = r.text or ""
        length = len(text)

        matched = [t for t in tokens if t.lower() in text.lower()]
        ok = status == 200 and length > 500 and len(matched) >= 1

        # Сохраняем HTML/JSON
        out_file = OUT / f"{name}.html"
        out_file.write_text(text[:50000], encoding="utf-8", errors="ignore")

        # Попробуем JSON
        json_preview = ""
        try:
            data = r.json()
            json_preview = json.dumps(data, ensure_ascii=False)[:300]
        except Exception:
            json_preview = text[:300]

        return {
            "name": name,
            "ok": ok,
            "status": status,
            "length": length,
            "matched": matched,
            "preview": json_preview,
        }
    except Exception as e:
        return {"name": name, "ok": False, "status": None, "error": str(e), "matched": []}


def main():
    print("Проверяем источники для футбола (РПЛ и другие)...\n")
    results = []

    for s in SOURCES:
        print(f"→ {s['name']}")
        res = probe(s)
        results.append(res)

        if res["ok"]:
            print(f"  ✅ OK | status={res['status']} | len={res['length']} | tokens={res['matched']}")
            print(f"  Preview: {res.get('preview', '')[:150]}")
        else:
            err = res.get("error", f"status={res['status']}, tokens={res['matched']}")
            print(f"  ❌ FAIL | {err}")
        print()

    # Итог
    print("=" * 50)
    ok_sources = [r["name"] for r in results if r["ok"]]
    print(f"Рабочих источников: {len(ok_sources)}")
    for n in ok_sources:
        print(f"  ✅ {n}")

    # Сохраняем отчёт
    report_path = OUT / "football_sources_report.json"
    report_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nОтчёт: {report_path}")


if __name__ == "__main__":
    main()
