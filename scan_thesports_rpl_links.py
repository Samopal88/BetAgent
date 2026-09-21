#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_thesports_rpl_links.py

Сканирует страницу TheSports по РПЛ и пытается найти:
- ссылки на архивы
- ссылки на сезоны
- ссылки на standings/results/statistics/help
- возможные round/manche/result subpages
- все ссылки, где встречаются football / premier league / russia / result / archive

Можно запускать:
1) по локальному HTML:
   python scan_thesports_rpl_links.py --html tests_output/rpl_prev_season.html

2) по URL:
   python scan_thesports_rpl_links.py --url "https://www.the-sports.org/..."

Сохраняет:
- полный список ссылок
- отфильтрованные кандидаты
"""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://www.the-sports.org/football-soccer-russia-division-1-russian-premier-league-2024-2025-results-eprd134327.html"
OUT_DIR = Path("tests_output")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

KEYWORDS = [
    "archive", "archives", "result", "results", "standing", "statistics",
    "help", "presentation", "prize", "team", "calendar", "classification",
    "football", "soccer", "russia", "premier", "division", "epr", "eprd",
    "round", "tour", "stage", "regular"
]

def load_html_from_url(url: str) -> tuple[str, str]:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text, url

def load_html_from_file(path: Path) -> tuple[str, str]:
    return path.read_text(encoding="utf-8"), "https://www.the-sports.org/"

def short(text: str, n: int = 140) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:n]

def score_link(href: str, text: str) -> int:
    base = f"{href} {text}".lower()
    score = 0
    for kw in KEYWORDS:
        if kw in base:
            score += 1
    if "2024-2025" in base or "2025-2026" in base:
        score += 2
    if "russian-premier-league" in base:
        score += 3
    if "epr" in base or "eprd" in base:
        score += 1
    return score

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=str, default=None, help="Локальный HTML-файл")
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help="URL страницы TheSports")
    args = parser.parse_args()

    if args.html:
        html, base_url = load_html_from_file(Path(args.html))
        source_label = Path(args.html).stem
    else:
        html, base_url = load_html_from_url(args.url)
        source_label = "live"

    soup = BeautifulSoup(html, "html.parser")

    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(" ", strip=True)
        full = urljoin(base_url, href)

        key = (full, text)
        if key in seen:
            continue
        seen.add(key)

        item = {
            "text": text,
            "href": href,
            "full_url": full,
            "score": score_link(href, text),
        }
        links.append(item)

    links_sorted = sorted(links, key=lambda x: (-x["score"], x["full_url"]))

    candidates = [
        x for x in links_sorted
        if x["score"] >= 2
    ]

    exact_rpl_candidates = [
        x for x in links_sorted
        if any(tok in x["full_url"].lower() for tok in [
            "russian-premier-league",
            "division-1",
            "2024-2025",
            "2025-2026",
            "epr",
            "eprd",
            "archive",
            "results",
            "statistics"
        ])
    ]

    all_path = OUT_DIR / f"{source_label}_all_links.json"
    cand_path = OUT_DIR / f"{source_label}_candidate_links.json"
    exact_path = OUT_DIR / f"{source_label}_exact_rpl_links.json"

    all_path.write_text(json.dumps(links_sorted, ensure_ascii=False, indent=2), encoding="utf-8")
    cand_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    exact_path.write_text(json.dumps(exact_rpl_candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Сканирование завершено.\n")
    print(f"Всего уникальных ссылок: {len(links_sorted)}")
    print(f"Кандидатов (score>=2): {len(candidates)}")
    print(f"RPL/exact candidates: {len(exact_rpl_candidates)}\n")

    print("=" * 80)
    print("TOP CANDIDATES")
    print("=" * 80)
    for i, item in enumerate(candidates[:60], 1):
        print(f"{i:02d}. score={item['score']} | text={short(item['text'])}")
        print(f"    {item['full_url']}")

    print("\n" + "=" * 80)
    print("RPL / EXACT CANDIDATES")
    print("=" * 80)
    for i, item in enumerate(exact_rpl_candidates[:60], 1):
        print(f"{i:02d}. score={item['score']} | text={short(item['text'])}")
        print(f"    {item['full_url']}")

    print("\nСохранено:")
    print(f"- {all_path}")
    print(f"- {cand_path}")
    print(f"- {exact_path}")

if __name__ == "__main__":
    main()
