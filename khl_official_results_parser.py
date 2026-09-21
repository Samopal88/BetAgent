#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
khl_official_results_parser.py

Parses the official KHL website to get match results:
- Fetches the KHL calendar page using Playwright
- Extracts information about completed matches and their scores directly from the calendar
- Writes data to the results_raw table

Usage:
  python khl_official_results_parser.py
  python khl_official_results_parser.py --days 7  # parse results for the last 7 days
  python khl_official_results_parser.py --dry-run  # don't write to DB
"""

import os
import re
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
LEAGUE = "khl"

# Mapping of team names from the official KHL site to our names
TEAM_MAP = {
    "Admiral": "Адмирал",
    "Ak Bars": "Ак Барс",
    "Amur": "Амур",
    "Avangard": "Авангард",
    "Avtomobilist": "Автомобилист",
    "Barys": "Барыс",
    "CSKA": "ЦСКА",
    "Dinamo Msk": "Динамо Москва",
    "Dinamo Mn": "Динамо Минск",
    "HC Sochi": "ХК Сочи",
    "Lada": "Лада",
    "Lokomotiv": "Локомотив Ярославль",
    "Metallurg Mg": "Металлург Мг",
    "Neftekhimik": "Нефтехимик",
    "Salavat Yulaev": "Салават Юлаев",
    "Severstal": "Северсталь",
    "Kunlun RS": "Шанхай Дрэгонс",
    "Sibir": "Сибирь",
    "SKA": "СКА",
    "Spartak": "Спартак",
    "Torpedo": "Торпедо НН",
    "Traktor": "Трактор",
}

# URL
KHL_CALENDAR_URL = "https://en.khl.ru/calendar/"


def get_conn():
    """Connect to the database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection):
    """Check for required tables"""
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS results_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        match_date TEXT,
        kickoff TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        is_finished INTEGER DEFAULT 0,
        source TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()


def normalize_team(name: str) -> str:
    """Normalize team name"""
    return TEAM_MAP.get(name, name)


def fetch_calendar_with_playwright(days_back: int = 3) -> str:
    """Fetch the KHL calendar page using Playwright"""
    print(f"Fetching KHL calendar for the last {days_back} days using Playwright")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(KHL_CALENDAR_URL, timeout=60000)
            # Wait for the calendar to load
            page.wait_for_selector(".calendar-match", timeout=30000)
            html_content = page.content()
            browser.close()
            return html_content
        except Exception as e:
            print(f"❌ Error fetching KHL calendar: {e}")
            browser.close()
            return ""


def extract_finished_matches(html: str, days_back: int = 3) -> List[Dict]:
    """Extract finished matches directly from the calendar HTML"""
    if not html:
        return []
    
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # Calculate the date range we're interested in
    today = datetime.now()
    start_date = today - timedelta(days=days_back)
    
    # Find all game blocks in the calendar
    game_blocks = soup.select("a.calendar-match")
    
    for block in game_blocks:
        # Check if the game has a result (finished)
        score_elem = block.select_one(".calendar-match__score")
        if not score_elem:
            continue
        
        # Extract date
        date_elem = block.select_one(".calendar-match__date")
        if not date_elem:
            continue
            
        try:
            # Format: "17.03.2026"
            date_text = date_elem.text.strip()
            game_date = datetime.strptime(date_text, "%d.%m.%Y")
            
            # Skip if the game is outside our date range
            if game_date < start_date:
                continue
                
            match_date = game_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue
        
        # Extract teams
        home_team_elem = block.select_one(".calendar-match__team--home .calendar-match__team-name")
        away_team_elem = block.select_one(".calendar-match__team--away .calendar-match__team-name")
        
        if not home_team_elem or not away_team_elem:
            continue
            
        home_team = home_team_elem.text.strip()
        away_team = away_team_elem.text.strip()
        
        # Extract scores
        score_text = score_elem.text.strip()
        score_match = re.search(r"(\d+):(\d+)", score_text)
        if not score_match:
            continue
            
        try:
            home_score = int(score_match.group(1))
            away_score = int(score_match.group(2))
        except ValueError:
            continue
        
        # Extract time if available
        time_elem = block.select_one(".calendar-match__time")
        kickoff = time_elem.text.strip() if time_elem else ""
        
        # Format kickoff as "HHhMM" if it's in "HH:MM" format
        if kickoff and re.match(r"\d{1,2}:\d{2}", kickoff):
            hour, minute = kickoff.split(":")
            kickoff = f"{int(hour):02d}h{minute}"
        
        # Get the URL as source
        href = block.get("href", "")
        source = f"https://en.khl.ru{href}" if href else KHL_CALENDAR_URL
        
        results.append({
            "home_team": normalize_team(home_team),
            "away_team": normalize_team(away_team),
            "home_score": home_score,
            "away_score": away_score,
            "match_date": match_date,
            "kickoff": kickoff,
            "is_finished": 1,
            "source": source
        })
    
    print(f"Found {len(results)} finished games with results")
    return results


def save_results_raw(conn: sqlite3.Connection, results: List[Dict], dry_run: bool = False):
    """Save results to the results_raw table"""
    if dry_run:
        print("DRY RUN: Data will not be saved to DB")
        return
    
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for result in results:
        # Check if this match already exists
        existing = cur.execute("""
            SELECT id FROM results_raw
            WHERE league = ?
              AND home_team = ?
              AND away_team = ?
              AND match_date = ?
            LIMIT 1
        """, (LEAGUE, result["home_team"], result["away_team"], result["match_date"])).fetchone()
        
        if existing:
            # Update existing record
            cur.execute("""
                UPDATE results_raw
                SET home_score = ?,
                    away_score = ?,
                    is_finished = 1,
                    source = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                result["home_score"],
                result["away_score"],
                result["source"],
                now,
                existing["id"]
            ))
        else:
            # Insert new record
            cur.execute("""
                INSERT INTO results_raw (
                    league, match_date, kickoff, home_team, away_team,
                    home_score, away_score, is_finished, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                LEAGUE,
                result["match_date"],
                result["kickoff"],
                result["home_team"],
                result["away_team"],
                result["home_score"],
                result["away_score"],
                result["source"],
                now
            ))
    
    conn.commit()
    print(f"✅ Saved/updated {len(results)} matches in results_raw")


def main():
    parser = argparse.ArgumentParser(description="KHL Official Results Parser")
    parser.add_argument("--days", type=int, default=3, help="Number of days back to parse (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write data to DB")
    args = parser.parse_args()
    
    print(f"🏒 KHL Official Results Parser (days_back={args.days})")
    print("=" * 50)
    
    # Fetch the calendar page using Playwright
    calendar_html = fetch_calendar_with_playwright(days_back=args.days)
    if not calendar_html:
        print("❌ Failed to fetch KHL calendar")
        return 1
    
    # Extract finished matches directly from the calendar
    results = extract_finished_matches(calendar_html, days_back=args.days)
    
    if not results:
        print("❌ No finished games with results")
        return 0
    
    # Display found results
    print("\nFound results:")
    for r in results:
        print(f"  {r['match_date']} | {r['kickoff']} | {r['home_team']} {r['home_score']}:{r['away_score']} {r['away_team']}")
    
    # Connect to DB and save results
    conn = get_conn()
    ensure_schema(conn)
    
    save_results_raw(conn, results, dry_run=args.dry_run)
    
    conn.close()
    
    print("\nNext step:")
    print("  python updater_results.py --settle")
    
    return 0


if __name__ == "__main__":
    exit(main())
