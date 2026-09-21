#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загрузчик летних футбольных лиг с football-data.co.uk
Источник: https://www.football-data.co.uk/new/XXX.csv

Лиги:
  NOR - Норвегия Eliteserien (апрель-ноябрь)
  SWE - Швеция Allsvenskan (апрель-ноябрь)
  FIN - Финляндия Veikkausliiga (апрель-октябрь)
  DNK - Дания Суперлига (круглый год)
  IRL - Ирландия Премьер-лига (март-ноябрь)

Запуск:
  python3 backtest_summer_leagues.py
  python3 backtest_summer_leagues.py --leagues NOR SWE
  python3 backtest_summer_leagues.py --from-year 2021
"""
import argparse, csv, io, sqlite3, requests
from datetime import datetime
from pathlib import Path

DB_PATH = "betagent.db"
BASE_URL = "https://www.football-data.co.uk/new/{code}.csv"

LEAGUES = {
    "NOR": "Норвегия. Элитесериен",
    "SWE": "Швеция. Аллсвенскан",
    "FIN": "Финляндия. Вейккаусліга",
    "DNK": "Дания. Суперлига",
    "IRL": "Ирландия. Премьер-лига",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT,
    match_date TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    odds_home REAL,
    odds_draw REAL,
    odds_away REAL,
    odds_btts_yes REAL,
    odds_btts_no REAL,
    odds_over_2_5 REAL,
    odds_under_2_5 REAL,
    odds_over_1_5 REAL,
    odds_under_1_5 REAL,
    source_url TEXT,
    created_at TEXT,
    UNIQUE(match_date, home_team, away_team)
)
"""

def parse_odd(val: str):
    try:
        v = float(val.strip().replace(",", "."))
        return v if v > 1.0 else None
    except Exception:
        return None

def parse_date(val: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(val.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None

def download_league(code: str, league_name: str, from_year: int, db_path: str) -> int:
    url = BASE_URL.format(code=code)
    print(f"\n📥 {league_name} ({code})...")
    print(f"   URL: {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception as e:
        print(f"   ❌ Ошибка загрузки: {e}")
        return 0

    lines = r.text.strip().splitlines()
    if not lines:
        print("   ❌ Пустой файл")
        return 0

    reader = csv.DictReader(lines)
    rows = list(reader)
    print(f"   Строк в файле: {len(rows)}")

    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_SQL)
    conn.commit()

    saved = 0
    skipped_year = 0
    skipped_no_odds = 0

    for row in rows:
        # Дата
        date_raw = row.get("Date", "").strip()
        match_date = parse_date(date_raw)
        if not match_date:
            continue

        # Фильтр по году
        year = int(match_date[:4])
        if year < from_year:
            skipped_year += 1
            continue

        # Фильтр — только завершённые матчи (есть счёт)
        hg = row.get("HG", "").strip()
        ag = row.get("AG", "").strip()
        if not hg or not ag:
            continue

        try:
            home_score = int(hg)
            away_score = int(ag)
        except Exception:
            continue

        home_team = row.get("Home", "").strip()
        away_team = row.get("Away", "").strip()
        if not home_team or not away_team:
            continue

        # Коэффициенты — берём средние (AvgCH/AvgCD/AvgCA) как основные
        odds_home = parse_odd(row.get("AvgCH", "") or row.get("B365CH", "") or row.get("PSCH", ""))
        odds_draw = parse_odd(row.get("AvgCD", "") or row.get("B365CD", "") or row.get("PSCD", ""))
        odds_away = parse_odd(row.get("AvgCA", "") or row.get("B365CA", "") or row.get("PSCA", ""))

        if not odds_home or not odds_draw or not odds_away:
            skipped_no_odds += 1
            continue

        # BTTS и тоталы — в этом формате не всегда есть, оставляем NULL
        try:
            conn.execute("""
                INSERT OR IGNORE INTO backtest_matches
                    (league, match_date, home_team, away_team,
                     home_score, away_score,
                     odds_home, odds_draw, odds_away,
                     source_url, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                league_name, match_date, home_team, away_team,
                home_score, away_score,
                odds_home, odds_draw, odds_away,
                url,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                saved += 1
        except Exception as e:
            print(f"   ⚠️ {home_team} vs {away_team}: {e}")

    conn.commit()
    conn.close()

    print(f"   ✅ Сохранено: {saved}")
    print(f"   ⏭️  Пропущено (до {from_year}г): {skipped_year}")
    print(f"   ⏭️  Пропущено (нет коэф): {skipped_no_odds}")
    return saved

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--leagues", nargs="+", default=list(LEAGUES.keys()),
                        choices=list(LEAGUES.keys()),
                        help="Лиги для загрузки")
    parser.add_argument("--from-year", type=int, default=2021,
                        help="Начиная с какого года (default: 2021)")
    parser.add_argument("--db", default=DB_PATH, help="Путь к БД")
    args = parser.parse_args()

    print(f"Загружаем лиги: {args.leagues}")
    print(f"Начиная с: {args.from_year}")
    print(f"БД: {args.db}")

    total = 0
    for code in args.leagues:
        league_name = LEAGUES[code]
        saved = download_league(code, league_name, args.from_year, args.db)
        total += saved

    print(f"\n{'='*50}")
    print(f"ИТОГО сохранено: {total} матчей")

    # Статистика по лигам
    conn = sqlite3.connect(args.db)
    rows = conn.execute("""
        SELECT league, COUNT(*) as n,
               MIN(match_date) as from_d,
               MAX(match_date) as to_d
        FROM backtest_matches
        WHERE league IN (
            'Норвегия. Элитесериен',
            'Швеция. Аллсвенскан',
            'Финляндия. Вейккаусліга',
            'Дания. Суперлига',
            'Ирландия. Премьер-лига'
        )
        GROUP BY league ORDER BY n DESC
    """).fetchall()
    conn.close()

    print("\n=== СТАТИСТИКА В БД ===")
    for r in rows:
        print(f"  {r[0]}: {r[1]} матчей ({r[2]} — {r[3]})")

if __name__ == "__main__":
    main()
