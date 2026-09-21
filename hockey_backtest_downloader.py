#!/usr/bin/env python3
"""
Hockey Backtest Downloader

Downloads historical hockey match data from betz.su for backtesting purposes.
Focuses on scraping hockey matches and storing them in a SQLite database.

Usage:
    python3 hockey_backtest_downloader.py --date-from 2023-03-01 --date-to 2023-03-10
    python3 hockey_backtest_downloader.py --date-from 2022-09-01 --date-to 2025-04-30
"""

import argparse
import datetime
import logging
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple, Any

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Constants
DB_PATH = "data.db"
BASE_URL = "https://betz.su/line/"
REQUEST_DELAY = 2  # seconds between requests
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_backtest_table(conn: sqlite3.Connection) -> None:
    """Ensure the backtest_hockey_matches table exists with proper schema."""
    cursor = conn.cursor()
    
    # Create the table if it doesn't exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS backtest_hockey_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        season TEXT NOT NULL,
        match_date TEXT NOT NULL,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        home_score INTEGER,
        away_score INTEGER,
        result TEXT,
        odds_home REAL,
        odds_draw REAL,
        odds_away REAL,
        source TEXT NOT NULL,
        source_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(match_date, home_team, away_team)
    )
    """)
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hockey_league_season ON backtest_hockey_matches (league, season)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hockey_match_date ON backtest_hockey_matches (match_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hockey_teams ON backtest_hockey_matches (home_team, away_team)")
    
    conn.commit()

def determine_season(match_date: str, league: str) -> str:
    """
    Determine the season based on match date and league.
    For hockey, typically seasons span across two years (e.g., 2022/2023).
    """
    try:
        date_obj = datetime.datetime.strptime(match_date, "%Y-%m-%d")
        month = date_obj.month
        year = date_obj.year
        
        # For most hockey leagues, season starts in September/October and ends in April/May
        if month >= 9:  # September or later
            return f"{year}/{year+1}"
        else:  # January to August
            return f"{year-1}/{year}"
    except Exception as e:
        logger.error(f"Error determining season: {e}")
        return str(datetime.datetime.now().year)  # Fallback to current year

def format_date_for_url(date_str: str) -> str:
    """Convert YYYY-MM-DD to DD.MM.YYYY format for URL."""
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%d.%m.%Y")
    except Exception as e:
        logger.error(f"Error formatting date: {e}")
        return ""

def fetch_page(date_str: str) -> Optional[str]:
    """Fetch the HTML page for a specific date using Playwright."""
    formatted_date = format_date_for_url(date_str)
    if not formatted_date:
        return None
    
    url = f"{BASE_URL}?mode=started&date={formatted_date}&sport=Хоккей"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            
            # Navigate to the URL
            page.goto(url, wait_until="networkidle")
            
            # Wait for content to load
            page.wait_for_selector("body", timeout=30000)
            
            # Get the page content after JavaScript execution
            html_content = page.content()
            
            # Close the browser
            browser.close()
            
            return html_content
    except Exception as e:
        logger.error(f"Error fetching page for {date_str} with Playwright: {e}")
        return None

def parse_hockey_matches(html: str, date_str: str) -> List[Dict]:
    """Parse hockey matches from the HTML content."""
    if not html:
        return []
    
    matches = []
    soup = BeautifulSoup(html, "html.parser")
    
    # Find all match rows
    # Note: This is a placeholder pattern - you'll need to adjust based on actual HTML structure
    match_rows = soup.select("table.matches tr")
    
    for row in match_rows:
        try:
            # Extract match details
            # These selectors need to be adjusted based on actual HTML structure
            league_elem = row.select_one(".league")
            teams_elem = row.select_one(".teams")
            score_elem = row.select_one(".score")
            odds_elems = row.select(".odds")
            
            if not teams_elem:
                continue
            
            # Extract league
            league = league_elem.text.strip() if league_elem else "Unknown"
            
            # Extract teams
            teams_text = teams_elem.text.strip() if teams_elem else ""
            teams_match = re.match(r"(.+?)\s*-\s*(.+)", teams_text)
            if not teams_match:
                continue
                
            home_team = teams_match.group(1).strip()
            away_team = teams_match.group(2).strip()
            
            # Extract score
            score_text = score_elem.text.strip() if score_elem else ""
            score_match = re.match(r"(\d+)\s*:\s*(\d+)", score_text)
            
            home_score = int(score_match.group(1)) if score_match else None
            away_score = int(score_match.group(2)) if score_match else None
            
            # Determine result
            result = ""
            if home_score is not None and away_score is not None:
                if home_score > away_score:
                    result = "home_win"
                elif away_score > home_score:
                    result = "away_win"
                else:
                    result = "draw"
            
            # Extract odds
            odds_home = None
            odds_draw = None
            odds_away = None
            
            if odds_elems and len(odds_elems) >= 3:
                try:
                    odds_home = float(odds_elems[0].text.strip())
                except (ValueError, TypeError):
                    pass
                
                try:
                    odds_draw = float(odds_elems[1].text.strip())
                except (ValueError, TypeError):
                    pass
                
                try:
                    odds_away = float(odds_elems[2].text.strip())
                except (ValueError, TypeError):
                    pass
            
            # Create match record
            match = {
                "league": league,
                "season": determine_season(date_str, league),
                "match_date": date_str,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "result": result,
                "odds_home": odds_home,
                "odds_draw": odds_draw,
                "odds_away": odds_away,
                "source": "betz.su",
                "source_url": f"{BASE_URL}?mode=started&date={format_date_for_url(date_str)}&sport=Хоккей",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            matches.append(match)
            
        except Exception as e:
            logger.error(f"Error parsing match: {e}")
            continue
    
    return matches

def save_matches(conn: sqlite3.Connection, matches: List[Dict]) -> Tuple[int, int, int]:
    """
    Save matches to the database.
    Returns tuple of (inserted, updated, skipped) counts.
    """
    cursor = conn.cursor()
    inserted = 0
    updated = 0
    skipped = 0
    
    for match in matches:
        if not match or not match.get("home_team") or not match.get("away_team"):
            skipped += 1
            continue
        
        # Check if match already exists
        cursor.execute(
            """
            SELECT id FROM backtest_hockey_matches 
            WHERE match_date = ? AND home_team = ? AND away_team = ?
            """,
            (match["match_date"], match["home_team"], match["away_team"])
        )
        existing = cursor.fetchone()
        
        if existing:
            # Update existing match
            cursor.execute(
                """
                UPDATE backtest_hockey_matches SET
                league = ?,
                season = ?,
                home_score = ?,
                away_score = ?,
                result = ?,
                odds_home = ?,
                odds_draw = ?,
                odds_away = ?,
                source = ?,
                source_url = ?
                WHERE id = ?
                """,
                (
                    match["league"],
                    match["season"],
                    match["home_score"],
                    match["away_score"],
                    match["result"],
                    match["odds_home"],
                    match["odds_draw"],
                    match["odds_away"],
                    match["source"],
                    match["source_url"],
                    existing["id"]
                )
            )
            updated += 1
        else:
            # Insert new match
            try:
                cursor.execute(
                    """
                    INSERT INTO backtest_hockey_matches
                    (league, season, match_date, home_team, away_team, home_score, away_score, 
                    result, odds_home, odds_draw, odds_away, source, source_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match["league"],
                        match["season"],
                        match["match_date"],
                        match["home_team"],
                        match["away_team"],
                        match["home_score"],
                        match["away_score"],
                        match["result"],
                        match["odds_home"],
                        match["odds_draw"],
                        match["odds_away"],
                        match["source"],
                        match["source_url"],
                        match["created_at"]
                    )
                )
                inserted += 1
            except sqlite3.IntegrityError:
                # This should not happen due to our check above, but just in case
                skipped += 1
    
    conn.commit()
    return inserted, updated, skipped

def date_range(start_date: str, end_date: str) -> List[str]:
    """Generate a list of dates between start_date and end_date (inclusive)."""
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    
    date_list = []
    current = start
    
    while current <= end:
        date_list.append(current.strftime("%Y-%m-%d"))
        current += datetime.timedelta(days=1)
    
    return date_list

def main() -> int:
    """Main function to run the downloader."""
    parser = argparse.ArgumentParser(description="Download historical hockey match data for backtesting")
    parser.add_argument("--date-from", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--date-to", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--db-path", default=DB_PATH, help=f"Path to SQLite database (default: {DB_PATH})")
    parser.add_argument("--delay", type=int, default=REQUEST_DELAY, help=f"Delay between requests in seconds (default: {REQUEST_DELAY})")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode")
    
    args = parser.parse_args()
    
    # Validate dates
    try:
        datetime.datetime.strptime(args.date_from, "%Y-%m-%d")
        datetime.datetime.strptime(args.date_to, "%Y-%m-%d")
    except ValueError:
        logger.error("Invalid date format. Please use YYYY-MM-DD")
        return 1
    
    # Connect to database and ensure table exists
    conn = get_conn(args.db_path)
    ensure_backtest_table(conn)
    
    # Generate date range
    dates = date_range(args.date_from, args.date_to)
    
    # Initialize counters
    total_dates = len(dates)
    total_matches = 0
    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    
    logger.info(f"Starting download for {total_dates} dates from {args.date_from} to {args.date_to}")
    
    # Process each date
    for i, date_str in enumerate(dates, 1):
        logger.info(f"Processing date {i}/{total_dates}: {date_str}")
        
        # Fetch page
        html = fetch_page(date_str)
        if not html:
            logger.warning(f"No data found for {date_str}, skipping")
            continue
        
        # Parse matches
        matches = parse_hockey_matches(html, date_str)
        matches_count = len(matches)
        total_matches += matches_count
        
        logger.info(f"Found {matches_count} matches for {date_str}")
        
        # Save matches
        inserted, updated, skipped = save_matches(conn, matches)
        total_inserted += inserted
        total_updated += updated
        total_skipped += skipped
        
        logger.info(f"Date {date_str}: {inserted} inserted, {updated} updated, {skipped} skipped")
        
        # Polite delay between requests
        if i < total_dates:
            time.sleep(args.delay)
    
    # Print final summary
    logger.info("=" * 50)
    logger.info("Download completed")
    logger.info(f"Total dates processed: {total_dates}")
    logger.info(f"Total matches found: {total_matches}")
    logger.info(f"Total inserted: {total_inserted}")
    logger.info(f"Total updated: {total_updated}")
    logger.info(f"Total skipped: {total_skipped}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
