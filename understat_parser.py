#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Understat xG Parser — Fetches match-level xG data from understat.com
and stores it in betagent.db (understat_matches table).

Leagues: EPL, La_liga, Bundesliga, Serie_A, Ligue_1, RFPL
Seasons: 2019–2025

Usage:
    python understat_parser.py
    python understat_parser.py --league EPL --season 2024
"""
import argparse
import json
import logging
import re
import sqlite3
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
}

LEAGUES = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"]
SEASONS = list(range(2019, 2026))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("understat")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS understat_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            understat_id TEXT UNIQUE,
            league TEXT,
            season INTEGER,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            home_xg REAL,
            away_xg REAL,
            home_xg_diff REAL,
            away_xg_diff REAL,
            total_xg REAL,
            result TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_understat_league_season ON understat_matches(league, season)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_understat_date ON understat_matches(match_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_understat_teams ON understat_matches(home_team, away_team)")
    conn.commit()


def fetch_league_data(league: str, season: int) -> list[dict]:
    """Fetch match data from Understat's AJAX endpoint."""
    url = f"https://understat.com/getLeagueData/{league}/{season}"
    for attempt in range(3):
        try:
            # First visit the league page to set session cookies
            session = requests.Session()
            session.headers.update(HEADERS)
            session.get(f"https://understat.com/league/{league}/{season}", timeout=20)
            # Then fetch the JSON data
            r = session.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
            dates = data.get("dates", [])
            return dates if isinstance(dates, list) else []
        except Exception as e:
            if attempt < 2:
                wait = 3 * (attempt + 1)
                log.warning(f"Fetch error {url}: {e}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"Failed to fetch {url}: {e}")
                return []
    return []


def parse_match(m: dict) -> dict | None:
    """Parse a single match dict from datesData."""
    if not m.get("isResult"):
        return None

    understat_id = str(m.get("id", ""))
    if not understat_id:
        return None

    home_team = m.get("h", {})
    away_team = m.get("a", {})
    if not home_team or not away_team:
        return None

    # API returns team objects with 'title' field
    if isinstance(home_team, dict):
        home_team = home_team.get("title", "")
    if isinstance(away_team, dict):
        away_team = away_team.get("title", "")
    if not home_team or not away_team:
        return None

    match_date = m.get("datetime", "")[:10]  # YYYY-MM-DD

    try:
        home_goals = int(m.get("goals", {}).get("h", 0))
        away_goals = int(m.get("goals", {}).get("a", 0))
    except (ValueError, TypeError):
        home_goals = 0
        away_goals = 0

    try:
        home_xg = float(m.get("xG", {}).get("h", 0))
        away_xg = float(m.get("xG", {}).get("a", 0))
    except (ValueError, TypeError):
        return None

    home_xg_diff = round(home_goals - home_xg, 4)
    away_xg_diff = round(away_goals - away_xg, 4)
    total_xg = round(home_xg + away_xg, 4)

    if home_goals > away_goals:
        result = "H"
    elif home_goals < away_goals:
        result = "A"
    else:
        result = "D"

    return {
        "understat_id": understat_id,
        "home_team": home_team,
        "away_team": away_team,
        "match_date": match_date,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_xg_diff": home_xg_diff,
        "away_xg_diff": away_xg_diff,
        "total_xg": total_xg,
        "result": result,
    }


def save_matches(conn: sqlite3.Connection, matches: list[dict], league: str, season: int) -> int:
    """Insert matches, skip duplicates. Returns count of new entries."""
    saved = 0
    for m in matches:
        existing = conn.execute(
            "SELECT id FROM understat_matches WHERE understat_id = ?",
            (m["understat_id"],),
        ).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT INTO understat_matches
            (understat_id, league, season, match_date, home_team, away_team,
             home_goals, away_goals, home_xg, away_xg,
             home_xg_diff, away_xg_diff, total_xg, result)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            m["understat_id"], league, season, m["match_date"],
            m["home_team"], m["away_team"],
            m["home_goals"], m["away_goals"],
            m["home_xg"], m["away_xg"],
            m["home_xg_diff"], m["away_xg_diff"],
            m["total_xg"], m["result"],
        ))
        saved += 1
    conn.commit()
    return saved


def fetch_and_save(conn: sqlite3.Connection, league: str, season: int) -> int:
    """Fetch one league-season via API, parse, save. Returns new match count."""
    log.info(f"Fetching {league}/{season}...")
    raw_matches = fetch_league_data(league, season)
    if not raw_matches:
        log.warning(f"  No data found for {league}/{season}")
        return 0

    parsed = []
    for m in raw_matches:
        p = parse_match(m)
        if p:
            parsed.append(p)

    if not parsed:
        log.info(f"  {league}/{season}: 0 result matches")
        return 0

    saved = save_matches(conn, parsed, league, season)
    log.info(f"  {league}/{season}: {len(parsed)} matches found, {saved} new")
    return saved


def print_summary(conn: sqlite3.Connection):
    """Print summary statistics."""
    print("\n" + "=" * 70)
    print("UNDERSTAT xG DATA SUMMARY")
    print("=" * 70)

    total = conn.execute("SELECT COUNT(*) FROM understat_matches").fetchone()[0]
    print(f"\nTotal matches: {total}")

    rows = conn.execute("""
        SELECT league,
               COUNT(*) as n,
               MIN(match_date) as first_date,
               MAX(match_date) as last_date,
               ROUND(AVG(home_xg), 3) as avg_home_xg,
               ROUND(AVG(away_xg), 3) as avg_away_xg,
               ROUND(AVG(home_xg + away_xg), 3) as avg_total_xg,
               ROUND(AVG(home_goals), 3) as avg_home_goals,
               ROUND(AVG(away_goals), 3) as avg_away_goals
        FROM understat_matches
        GROUP BY league
        ORDER BY league
    """).fetchall()

    print(f"\n{'League':<12} {'Matches':>7} {'Date Range':<24} {'Avg xG H':>8} {'Avg xG A':>8} {'Avg Total xG':>12}")
    print("-" * 75)
    for r in rows:
        print(f"{r[0]:<12} {r[1]:>7} {r[2]} – {r[3]:<10} {r[4]:>8} {r[5]:>8} {r[6]:>12}")

    print(f"\n{'League':<12} {'Avg Goals H':>11} {'Avg Goals A':>11}")
    print("-" * 38)
    for r in rows:
        print(f"{r[0]:<12} {r[7]:>11} {r[8]:>11}")

    print("=" * 70)


def main():
    ap = argparse.ArgumentParser(description="Understat xG Parser")
    ap.add_argument("--league", default=None, choices=LEAGUES, help="Single league to fetch")
    ap.add_argument("--season", type=int, default=None, help="Single season to fetch")
    args = ap.parse_args()

    conn = get_conn()
    ensure_table(conn)

    if args.league and args.season:
        leagues = [args.league]
        seasons = [args.season]
    elif args.league:
        leagues = [args.league]
        seasons = SEASONS
    elif args.season:
        leagues = LEAGUES
        seasons = [args.season]
    else:
        leagues = LEAGUES
        seasons = SEASONS

    total_saved = 0
    for league in leagues:
        for season in seasons:
            saved = fetch_and_save(conn, league, season)
            total_saved += saved
            time.sleep(1.5)  # Rate limit delay

    conn.close()
    log.info(f"Done: {total_saved} new matches saved")

    # Re-open for summary
    conn = get_conn()
    print_summary(conn)
    conn.close()


if __name__ == "__main__":
    main()
