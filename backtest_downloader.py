#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — backtest_downloader.py

Скачивает исторические данные с football-data.co.uk
для бэктеста системы.

Формат CSV:
  Div, Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR,
  B365H, B365D, B365A (коэффициенты Bet365)

Запуск:
  python backtest_downloader.py
  python backtest_downloader.py --leagues EPL BL1 SA
  python backtest_downloader.py --seasons 2023 2024
"""

import os, csv, requests, argparse, sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

# Лиги на football-data.co.uk
LEAGUES = {
    "EPL":  ("E0",  "Англия. Премьер-Лига"),
    "BL1":  ("D1",  "Германия. Бундеслига"),
    "SA":   ("I1",  "Италия. Серия А"),
    "PD":   ("SP1", "Испания. Примера дивизион"),
    "FL1":  ("F1",  "Франция. Лига 1"),
    "RPL":  ("R1",  "Россия. Премьер-Лига"),
    # Летние лиги (апрель-ноябрь)
    "NOR":  ("new/NOR", "Норвегия. Элитесериен"),
    "SWE":  ("new/SWE", "Швеция. Аллсвенскан"),
    "FIN":  ("new/FIN", "Финляндия. Вейккаусліга"),
    "DNK":  ("new/DNK", "Дания. Суперлига"),
    "IRL":  ("new/IRL", "Ирландия. Премьер-лига"),
}

SEASONS = {
    2025: "2526",
    2024: "2425",
    2023: "2324",
    2022: "2223",
    2021: "2122",
    2020: "2021",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"


def download_csv(league_code: str, season_code: str) -> list[dict]:
    url = BASE_URL.format(season=season_code, league=league_code)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"    ⚠️ {r.status_code}: {url}")
            return []
        lines = r.text.strip().split("\n")
        reader = csv.DictReader(lines)
        rows = list(reader)
        print(f"    ✅ {len(rows)} матчей: {url}")
        return rows
    except Exception as e:
        print(f"    ❌ {e}")
        return []


def ensure_backtest_table(conn):
    # Check if we need to add new columns
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(backtest_matches)").fetchall()]
    
    # Create table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT,
            league_name TEXT,
            season TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            result TEXT,  -- H/D/A
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            odds_over_2_5 REAL,
            odds_under_2_5 REAL,
            odds_over_3_5 REAL,
            odds_under_3_5 REAL,
            odds_btts_yes REAL,
            odds_btts_no REAL,
            source TEXT DEFAULT 'football-data.co.uk',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    
    # Add new columns if table exists but columns are missing
    if existing_columns:
        new_columns = [
            ("odds_over_2_5", "REAL"),
            ("odds_under_2_5", "REAL"),
            ("odds_over_3_5", "REAL"),
            ("odds_under_3_5", "REAL"),
            ("odds_btts_yes", "REAL"),
            ("odds_btts_no", "REAL")
        ]
        
        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE backtest_matches ADD COLUMN {col_name} {col_type}")
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bt_league
        ON backtest_matches(league, season)
    """)
    conn.commit()


def parse_date(date_str: str) -> str:
    """Конвертируем DD/MM/YY или DD/MM/YYYY в YYYY-MM-DD."""
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            continue
    return date_str


def save_matches(conn, rows: list, league: str, league_name: str, season: str):
    inserted = 0
    updated = 0
    skipped = 0
    totals_2_5_count = 0
    totals_3_5_count = 0
    btts_count = 0
    
    for r in rows:
        try:
            home = r.get("HomeTeam", "").strip()
            away = r.get("AwayTeam", "").strip()
            if not home or not away:
                continue

            date_str = parse_date(r.get("Date", ""))
            hg = r.get("FTHG", "")
            ag = r.get("FTAG", "")
            result = r.get("FTR", "")  # H/D/A

            # Коэффициенты 1X2 — пробуем разные источники
            oh = float(r.get("B365H") or r.get("BbAvH") or r.get("AvgH") or 0)
            od = float(r.get("B365D") or r.get("BbAvD") or r.get("AvgD") or 0)
            oa = float(r.get("B365A") or r.get("BbAvA") or r.get("AvgA") or 0)

            if oh == 0 or od == 0 or oa == 0:
                skipped += 1
                continue

            # Тоталы 2.5 - приоритет: Bet365 > Pinnacle > Average > Max
            over_2_5 = None
            under_2_5 = None
            try:
                if r.get("B365>2.5") and r.get("B365<2.5"):
                    over_2_5 = float(r.get("B365>2.5"))
                    under_2_5 = float(r.get("B365<2.5"))
                elif r.get("P>2.5") and r.get("P<2.5"):
                    over_2_5 = float(r.get("P>2.5"))
                    under_2_5 = float(r.get("P<2.5"))
                elif r.get("Avg>2.5") and r.get("Avg<2.5"):
                    over_2_5 = float(r.get("Avg>2.5"))
                    under_2_5 = float(r.get("Avg<2.5"))
                elif r.get("Max>2.5") and r.get("Max<2.5"):
                    over_2_5 = float(r.get("Max>2.5"))
                    under_2_5 = float(r.get("Max<2.5"))
                
                if over_2_5 and under_2_5:
                    totals_2_5_count += 1
            except:
                over_2_5 = None
                under_2_5 = None

            # Тоталы 3.5 - приоритет: Bet365 > Pinnacle > Average > Max
            over_3_5 = None
            under_3_5 = None
            try:
                if r.get("B365>3.5") and r.get("B365<3.5"):
                    over_3_5 = float(r.get("B365>3.5"))
                    under_3_5 = float(r.get("B365<3.5"))
                elif r.get("P>3.5") and r.get("P<3.5"):
                    over_3_5 = float(r.get("P>3.5"))
                    under_3_5 = float(r.get("P<3.5"))
                elif r.get("Avg>3.5") and r.get("Avg<3.5"):
                    over_3_5 = float(r.get("Avg>3.5"))
                    under_3_5 = float(r.get("Avg<3.5"))
                elif r.get("Max>3.5") and r.get("Max<3.5"):
                    over_3_5 = float(r.get("Max>3.5"))
                    under_3_5 = float(r.get("Max<3.5"))
                
                if over_3_5 and under_3_5:
                    totals_3_5_count += 1
            except:
                over_3_5 = None
                under_3_5 = None

            # BTTS (Both Teams To Score) - приоритет: Bet365 > Pinnacle > Average > Max
            btts_yes = None
            btts_no = None
            try:
                if r.get("B365BTTS") and r.get("B365BTTSN"):
                    btts_yes = float(r.get("B365BTTS"))
                    btts_no = float(r.get("B365BTTSN"))
                elif r.get("B365CS") and r.get("B365CA"):
                    btts_yes = float(r.get("B365CS"))
                    btts_no = float(r.get("B365CA"))
                elif r.get("PCAHH") and r.get("PCAHA"):
                    btts_yes = float(r.get("PCAHH"))
                    btts_no = float(r.get("PCAHA"))
                elif r.get("AvgCAHH") and r.get("AvgCAHA"):
                    btts_yes = float(r.get("AvgCAHH"))
                    btts_no = float(r.get("AvgCAHA"))
                elif r.get("MaxCAHH") and r.get("MaxCAHA"):
                    btts_yes = float(r.get("MaxCAHH"))
                    btts_no = float(r.get("MaxCAHA"))
                
                if btts_yes and btts_no:
                    btts_count += 1
            except:
                btts_yes = None
                btts_no = None

            # Проверяем существование матча
            existing = conn.execute("""
                SELECT id, odds_home, odds_draw, odds_away 
                FROM backtest_matches
                WHERE league=? AND season=? AND home_team=? AND away_team=? AND match_date=?
            """, (league, season, home, away, date_str)).fetchone()
            
            if existing:
                # Обновляем существующий матч с новыми данными тоталов и BTTS
                # Сохраняем существующие коэффициенты 1X2, если они есть
                existing_oh = existing['odds_home'] if existing['odds_home'] else oh
                existing_od = existing['odds_draw'] if existing['odds_draw'] else od
                existing_oa = existing['odds_away'] if existing['odds_away'] else oa
                
                conn.execute("""
                    UPDATE backtest_matches
                    SET odds_home=?, odds_draw=?, odds_away=?,
                        odds_over_2_5=?, odds_under_2_5=?,
                        odds_over_3_5=?, odds_under_3_5=?,
                        odds_btts_yes=?, odds_btts_no=?
                    WHERE id=?
                """, (existing_oh, existing_od, existing_oa,
                      over_2_5, under_2_5, over_3_5, under_3_5,
                      btts_yes, btts_no, existing['id']))
                updated += 1
            else:
                # Вставляем новый матч
                conn.execute("""
                    INSERT INTO backtest_matches
                    (league, league_name, season, match_date, home_team, away_team,
                     home_score, away_score, result, odds_home, odds_draw, odds_away,
                     odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
                     odds_btts_yes, odds_btts_no)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (league, league_name, season, date_str, home, away,
                      int(hg) if hg else None, int(ag) if ag else None,
                      result, oh, od, oa, over_2_5, under_2_5, over_3_5, under_3_5,
                      btts_yes, btts_no))
                inserted += 1
        except Exception as e:
            skipped += 1
            continue

    conn.commit()
    print(f"    💾 Новых: {inserted} | Обновлено: {updated} | Пропущено: {skipped}")
    print(f"       Тоталы 2.5: {totals_2_5_count} | Тоталы 3.5: {totals_3_5_count} | BTTS: {btts_count}")
    return inserted + updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="+", default=list(LEAGUES.keys()),
                    help="Лиги: EPL BL1 SA PD FL1 RPL")
    ap.add_argument("--seasons", nargs="+", type=int, default=[2024, 2023, 2022],
                    help="Сезоны: 2024 2023 2022")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_backtest_table(conn)

    total = 0
    for league_key in args.leagues:
        if league_key not in LEAGUES:
            print(f"⚠️ Неизвестная лига: {league_key}")
            continue
        league_code, league_name = LEAGUES[league_key]
        print(f"\n📥 {league_name} ({league_key}):")

        for season_year in args.seasons:
            if season_year not in SEASONS:
                continue
            season_code = SEASONS[season_year]
            print(f"  Сезон {season_year}/{season_year+1}:")

            rows = download_csv(league_code, season_code)
            if rows:
                saved = save_matches(conn, rows, league_key, league_name,
                                     str(season_year))
                total += saved

    conn.close()
    print(f"\n✅ Всего обработано: {total} исторических матчей")
    print("Теперь запускай:")
    print("  python backtest.py")

if __name__ == "__main__":
    main()
