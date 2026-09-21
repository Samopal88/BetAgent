#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_team_history.py

Загружает историю матчей каждой команды РПЛ
с персональных страниц TheSports (identity pages).

Структура страницы (по скрину):
  "20 July 2025 - 14h30" + "Round 1"  ← блок с датой
  FC Nizhny Novgorod  0 - 3  FC Krasnodar  ← строка матча

Пишет в results_raw с league='rpl_prev'.

Запуск:
  python fetch_team_history.py
  python fetch_team_history.py --limit 3   (тест на 3 командах)
  python fetch_team_history.py --matches 20
"""

import os, re, time, sqlite3, argparse
import requests, urllib3
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

urllib3.disable_warnings()

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BASE = "https://www.the-sports.org/football-soccer-"
LEAGUE_KEY = "rpl_prev"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

TEAM_SLUGS = {
    "Зенит":            "zenith-saint-petersburg-results-identity-equ1293.html",
    "Спартак":          "spartak-moscow-results-identity-equ876.html",
    "ЦСКА":             "cska-moscow-results-identity-equ1039.html",
    "Динамо Москва":    "dinamo-moscow-results-identity-equ1876.html",
    "Краснодар":        "fc-krasnodar-results-identity-equ11864.html",
    "Локомотив Москва": "fc-lokomotiv-moscow-results-identity-equ828.html",
    "Ростов":           "fc-rostov-results-identity-equ2197.html",
    "Рубин":            "fc-rubin-kazan-results-identity-equ2198.html",
    "Крылья Советов":   "fc-krylya-sovetov-samara-results-identity-equ505.html",
    "Ахмат":            "fc-akhmat-grozny-results-identity-equ1294.html",
    "Оренбург":         "fc-gazovik-orenburg-results-identity-equ14249.html",
    "Пари НН":          "fc-nizhny-novgorod-results-identity-equ56019.html",
    "Балтика":          "fc-baltika-kaliningrad-results-identity-equ19840.html",
    "Сочи":             "fc-sochi-results-identity-equ51104.html",
    "Динамо Махачкала": "dynamo-makhachkala-results-identity-equ93247.html",
    "Акрон":            "fk-akron-togliatti-results-identity-equ82530.html",
    "Химки":            "fc-khimki-results-identity-equ4931.html",
    "Факел":            "fc-fakel-voronezh-results-identity-equ16940.html",
}

TEAM_MAP = {
    "Zenith Saint-Petersburg": "Зенит",
    "Zenit St. Petersburg":    "Зенит",
    "Spartak Moscow":          "Спартак",
    "CSKA Moscow":             "ЦСКА",
    "Dinamo Moscow":           "Динамо Москва",
    "Dynamo Moscow":           "Динамо Москва",
    "FC Krasnodar":            "Краснодар",
    "Krasnodar":               "Краснодар",
    "FC Lokomotiv Moscow":     "Локомотив Москва",
    "Lokomotiv Moscow":        "Локомотив Москва",
    "FC Rostov":               "Ростов",
    "Rostov":                  "Ростов",
    "FC Rubin Kazan":          "Рубин",
    "Rubin Kazan":             "Рубин",
    "FC Krylya Sovetov Samara":"Крылья Советов",
    "FC Akhmat Grozny":        "Ахмат",
    "Akhmat Grozny":           "Ахмат",
    "FC Gazovik Orenburg":     "Оренбург",
    "FC Nizhny Novgorod":      "Пари НН",
    "Nizhny Novgorod":         "Пари НН",
    "FC Baltika Kaliningrad":  "Балтика",
    "Baltika Kaliningrad":     "Балтика",
    "FC Sochi":                "Сочи",
    "Sochi":                   "Сочи",
    "Dynamo Makhachkala":      "Динамо Махачкала",
    "FK Makhachkala":          "Динамо Махачкала",
    "FK Akron Togliatti":      "Акрон",
    "FC Khimki":               "Химки",
    "FC Fakel Voronezh":       "Факел",
    "Torpedo Moscow":          "Торпедо",
    "FC Ural Yekaterinburg":   "Урал",
    "FC Anzhi Makhachkala":    "Анжи",
}

MONTHS = {
    "January":"01","February":"02","March":"03","April":"04",
    "May":"05","June":"06","July":"07","August":"08",
    "September":"09","October":"10","November":"11","December":"12",
}

def norm_team(name: str) -> str:
    name = re.sub(r"\s*\(\d+\)\s*$", "", (name or "").strip())
    name = re.sub(r"\s*\(RUS\)\s*", "", name).strip()
    return TEAM_MAP.get(name, name)

def parse_date(text: str):
    """Парсит '20 July 2025 - 14h30' → ('2025-07-20', '14:30')"""
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip())
    if not m:
        return None, None
    d, mon, y = m.groups()
    mm = MONTHS.get(mon)
    if not mm:
        return None, None
    date_str = f"{y}-{mm}-{int(d):02d}"
    tm = re.search(r"(\d{1,2})h(\d{2})", text)
    time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "00:00"
    return date_str, time_str

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_page(slug: str):
    url = BASE + slug
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        if r.status_code == 200 and len(r.text) > 5000:
            return r.text
    except Exception as e:
        print(f"    ❌ {e}")
    return None

def parse_team_results(html: str, n: int = 15):
    """
    Структура страницы команды TheSports:
    <tr>
      <td class="tdcol-25">20 July 2025 - 17h00 Round 1</td>
      <td>Zenith Saint-Petersburg (4)</td>
      <td class="tdcol-15 td-center">2 - 1</td>
      <td>FC Rostov (13)</td>
    </tr>
    Дата, home, счёт, away — всё в одной строке.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for tr in soup.find_all("tr"):
        cols = tr.find_all("td")
        if len(cols) < 4:
            continue

        # Первая ячейка — дата + Round
        date_txt = cols[0].get_text(" ", strip=True)
        date, time_str = parse_date(date_txt)
        if not date:
            continue

        # Третья ячейка — счёт
        score_txt = cols[2].get_text(" ", strip=True)
        if "cancel" in score_txt.lower() or "postponed" in score_txt.lower():
            continue
        sm = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", score_txt)
        if not sm:
            continue

        # Вторая и четвёртая — команды (убираем "(N)" в конце)
        home_raw = re.sub(r"\s*\(\d+\)\s*$", "", cols[1].get_text(" ", strip=True)).strip()
        away_raw = re.sub(r"\s*\(\d+\)\s*$", "", cols[3].get_text(" ", strip=True)).strip()

        home = norm_team(home_raw)
        away = norm_team(away_raw)

        if not home or not away or home == away:
            continue

        results.append({
            "match_date": date,
            "kickoff": f"{date} {time_str}",
            "home_team": home,
            "away_team": away,
            "home_score": int(sm.group(1)),
            "away_score": int(sm.group(2)),
        })

        if len(results) >= n:
            break

    return results

def save_results(conn, results: list) -> int:
    if not results:
        return 0
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    for r in results:
        exists = cur.execute("""
            SELECT id FROM results_raw
            WHERE league=? AND match_date=? AND home_team=? AND away_team=?
        """, (LEAGUE_KEY, r["match_date"], r["home_team"], r["away_team"])).fetchone()
        if not exists:
            cur.execute("""
                INSERT INTO results_raw (
                    league, match_date, kickoff, home_team, away_team,
                    home_score, away_score, is_finished, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'TheSports team page', ?)
            """, (
                LEAGUE_KEY, r["match_date"], r["kickoff"],
                r["home_team"], r["away_team"],
                r["home_score"], r["away_score"], now
            ))
            saved += 1
    conn.commit()
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",   type=int, default=0,  help="Сколько команд (0=все)")
    ap.add_argument("--matches", type=int, default=15, help="Матчей на команду")
    args = ap.parse_args()

    conn = get_conn()
    teams = list(TEAM_SLUGS.items())
    if args.limit:
        teams = teams[:args.limit]

    print(f"Загружаем историю матчей для {len(teams)} команд РПЛ...\n")

    total_saved = 0
    for team_name, slug in teams:
        print(f"  {team_name}...")
        html = fetch_page(slug)
        if not html:
            print(f"    ⚠️  Страница недоступна")
            continue
        results = parse_team_results(html, n=args.matches)
        saved = save_results(conn, results)
        total_saved += saved
        status = f"{len(results)} матчей, {saved} новых"
        if results:
            dates = [r["match_date"] for r in results]
            status += f" | {min(dates)} — {max(dates)}"
        print(f"    → {status}")
        time.sleep(0.8)

    total = conn.execute(
        "SELECT COUNT(*) as c FROM results_raw WHERE league=?", (LEAGUE_KEY,)
    ).fetchone()["c"]
    print(f"\n✅ Всего в БД (league='{LEAGUE_KEY}'): {total} матчей")
    print("\nТеперь запускай:")
    print("  python enricher_football_rpl_v3.py")
    conn.close()

if __name__ == "__main__":
    main()
