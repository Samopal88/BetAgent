#!/usr/bin/env python3
import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


def get_conn():
    """Get a connection to the database."""
    db_path = os.environ.get("BETAGENT_DB", "betagent.db")
    return sqlite3.connect(db_path)


def ensure_schema(conn: sqlite3.Connection):
    """Ensure the required schema exists in the database."""
    cursor = conn.cursor()
    
    # Create results_raw table if it doesn't exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS results_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT,
        match_date TEXT,
        kickoff TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        is_finished INTEGER DEFAULT 0,
        source TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()


def fetch_html(url: str) -> str:
    """Fetch HTML content from the given URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def find_match_blocks(soup: BeautifulSoup) -> List[str]:
    """Find potential match blocks in the HTML."""
    # Look for elements that might contain match information
    candidate_blocks = []
    
    # Look for divs that might contain match information
    match_divs = soup.find_all("div", class_=lambda c: c and ("match" in c.lower() or "game" in c.lower()))
    for div in match_divs[:5]:  # Limit to 5 candidates
        candidate_blocks.append(str(div))
    
    return candidate_blocks


def normalize_team(name: str) -> str:
    """Normalize team name to a standard format."""
    # Remove any trailing/leading whitespace and common suffixes
    name = name.strip()
    
    # Common replacements for KHL teams
    khl_replacements = {
        "СКА": "СКА",
        "ЦСКА": "ЦСКА",
        "Динамо М": "Динамо Москва",
        "Динамо Мн": "Динамо Минск",
        "Ак Барс": "Ак Барс",
        "Спартак": "Спартак",
        "Авангард": "Авангард",
        "Локомотив": "Локомотив",
        "Металлург Мг": "Металлург Магнитогорск",
        "Трактор": "Трактор",
        "Сибирь": "Сибирь",
        "Торпедо": "Торпедо",
        "Северсталь": "Северсталь",
        "Витязь": "Витязь",
        "Нефтехимик": "Нефтехимик",
        "Амур": "Амур",
        "Куньлунь": "Куньлунь Ред Стар",
        "Адмирал": "Адмирал",
        "Барыс": "Барыс",
        "Салават Юлаев": "Салават Юлаев",
    }
    
    # Common replacements for NHL teams - from English to Russian short format
    nhl_replacements = {
        # Russian to Russian (keep these)
        "Бостон": "Бостон",
        "Баффало": "Баффало",
        "Детройт": "Детройт",
        "Флорида": "Флорида",
        "Монреаль": "Монреаль",
        "Оттава": "Оттава",
        "Тампа-Бэй": "Тампа-Бэй",
        "Торонто": "Торонто",
        "Каролина": "Каролина",
        "Коламбус": "Коламбус",
        "Нью-Джерси": "Нью-Джерси",
        "Айлендерс": "Айлендерс",
        "Рейнджерс": "Рейнджерс",
        "Филадельфия": "Филадельфия",
        "Питтсбург": "Питтсбург",
        "Вашингтон": "Вашингтон",
        "Чикаго": "Чикаго",
        "Колорадо": "Колорадо",
        "Даллас": "Даллас",
        "Миннесота": "Миннесота",
        "Нэшвилл": "Нэшвилл",
        "Сент-Луис": "Сент-Луис",
        "Виннипег": "Виннипег",
        "Анахайм": "Анахайм",
        "Аризона": "Аризона",
        "Калгари": "Калгари",
        "Эдмонтон": "Эдмонтон",
        "Лос-Анджелес": "Лос-Анджелес",
        "Сан-Хосе": "Сан-Хосе",
        "Сиэтл": "Сиэтл",
        "Ванкувер": "Ванкувер",
        "Вегас": "Вегас",
        
        # English to Russian mappings
        "Boston Bruins": "Бостон",
        "Buffalo Sabres": "Баффало",
        "Detroit Red Wings": "Детройт",
        "Florida Panthers": "Флорида",
        "Montreal Canadiens": "Монреаль",
        "Ottawa Senators": "Оттава",
        "Tampa Bay Lightning": "Тампа-Бэй",
        "Toronto Maple Leafs": "Торонто",
        "Carolina Hurricanes": "Каролина",
        "Columbus Blue Jackets": "Коламбус",
        "New Jersey Devils": "Нью-Джерси",
        "New York Islanders": "Айлендерс",
        "New York Rangers": "Рейнджерс",
        "Philadelphia Flyers": "Филадельфия",
        "Pittsburgh Penguins": "Питтсбург",
        "Washington Capitals": "Вашингтон",
        "Chicago Blackhawks": "Чикаго",
        "Colorado Avalanche": "Колорадо",
        "Dallas Stars": "Даллас",
        "Minnesota Wild": "Миннесота",
        "Nashville Predators": "Нэшвилл",
        "St. Louis Blues": "Сент-Луис",
        "Winnipeg Jets": "Виннипег",
        "Anaheim Ducks": "Анахайм",
        "Arizona Coyotes": "Аризона",
        "Calgary Flames": "Калгари",
        "Edmonton Oilers": "Эдмонтон",
        "Los Angeles Kings": "Лос-Анджелес",
        "San Jose Sharks": "Сан-Хосе",
        "Seattle Kraken": "Сиэтл",
        "Vancouver Canucks": "Ванкувер",
        "Vegas Golden Knights": "Вегас",
        "Utah Hockey Club": "Юта",
        "Utah": "Юта",
    }
    
    # Combine both dictionaries
    all_replacements = {**khl_replacements, **nhl_replacements}
    return all_replacements.get(name, name)


def parse_hockey_matches(html: str, date_str: str, league: str, table_index: int) -> List[Dict]:
    """Parse hockey matches from the HTML for the specified league."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # Find the match center div
    match_center = soup.find("div", class_="match-center")
    if not match_center:
        print(f"Warning: Could not find match-center div for {league}")
        return results
    
    # Get the tables
    tables = match_center.find_all("table")
    if not tables or len(tables) <= table_index:
        print(f"Warning: No table found at index {table_index} for {league}")
        return results
    
    league_table = tables[table_index]
    
    # Find all match rows
    match_rows = league_table.find_all("tr", attrs={"data-match-id": True})
    
    for row in match_rows:
        try:
            # Check if the match is finished
            status_cell = row.find_all("td")[1]
            status = status_cell.get_text(strip=True)
            
            if "Завершен" not in status:
                continue
            
            # Get match details
            kickoff = row.find_all("td")[0].get_text(strip=True)
            
            home_team_cell = row.find("td", class_="owner-td")
            home_team = home_team_cell.find("a", class_="player").get_text(strip=True)
            
            score_cell = row.find("td", class_="score-td")
            score_text = score_cell.get_text(strip=True)
            
            # Try to get scores from span elements first (most reliable)
            score_left_elem = score_cell.find("span", class_="s-left")
            score_right_elem = score_cell.find("span", class_="s-right")
            
            if score_left_elem and score_right_elem:
                score_left = score_left_elem.get_text(strip=True)
                score_right = score_right_elem.get_text(strip=True)
            else:
                # Fallback: try to extract from score text (less reliable)
                score_match = re.search(r'(\d+)[^\d]+(\d+)', score_text)
                if score_match:
                    score_left = score_match.group(1)
                    score_right = score_match.group(2)
                else:
                    print(f"Warning: Could not parse score text: {score_text}")
                    continue
            
            away_team_cell = row.find("td", class_="guests-td")
            away_team = away_team_cell.find("a", class_="player").get_text(strip=True)
            
            # Parse scores
            try:
                home_score = int(score_left)
                away_score = int(score_right)
            except ValueError:
                print(f"Warning: Could not parse scores: {score_left}-{score_right}")
                continue
            
            # Create result entry
            result = {
                "league": league.lower(),
                "match_date": date_str,
                "kickoff": kickoff,
                "home_team": normalize_team(home_team),
                "away_team": normalize_team(away_team),
                "home_score": home_score,
                "away_score": away_score,
                "is_finished": 1,
                "source": f"https://www.sports.ru/hockey/match/{date_str}/"
            }
            
            results.append(result)
            
        except Exception as e:
            print(f"Error parsing {league} match row: {e}")
    
    return results


def parse_khl_matches(html: str, date_str: str) -> List[Dict]:
    """Parse KHL matches from the HTML."""
    return parse_hockey_matches(html, date_str, "khl", 0)  # KHL is in the first table


def parse_nhl_matches(html: str, date_str: str) -> List[Dict]:
    """Parse NHL matches from the HTML."""
    return parse_hockey_matches(html, date_str, "nhl", 1)  # NHL is in the second table


def debug_structure(html: str):
    """Debug the HTML structure to identify relevant elements."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Find lines containing key words
    keywords = ["Завершен", "Превью", "summary", "score", "match", "КХЛ", "НХЛ"]
    
    print("=" * 80)
    print("LINES CONTAINING KEYWORDS:")
    print("=" * 80)
    
    count = 0
    for line in html.splitlines():
        if any(keyword in line for keyword in keywords):
            print(line[:200] + "..." if len(line) > 200 else line)
            count += 1
            if count >= 80:
                break
    
    print("\n" + "=" * 80)
    print("MATCH CENTER STRUCTURE:")
    print("=" * 80)
    
    match_center = soup.find("div", class_="match-center")
    if match_center:
        tables = match_center.find_all("table")
        print(f"Found {len(tables)} tables in match-center")
        
        # Debug KHL table (first table)
        if len(tables) > 0:
            khl_table = tables[0]
            match_rows = khl_table.find_all("tr", attrs={"data-match-id": True})
            print(f"Found {len(match_rows)} match rows in first table (KHL)")
            
            if match_rows:
                sample_row = match_rows[0]
                print("\nSAMPLE KHL MATCH ROW:")
                print("-" * 40)
                print(sample_row.prettify()[:1000])
                print("-" * 40)
                
                # Try to extract key elements
                try:
                    cells = sample_row.find_all("td")
                    kickoff = cells[0].get_text(strip=True)
                    status = cells[1].get_text(strip=True)
                    
                    home_team_cell = sample_row.find("td", class_="owner-td")
                    home_team = home_team_cell.find("a", class_="player").get_text(strip=True)
                    
                    score_cell = sample_row.find("td", class_="score-td")
                    score_left = score_cell.find("span", class_="s-left").get_text(strip=True)
                    score_right = score_cell.find("span", class_="s-right").get_text(strip=True)
                    
                    away_team_cell = sample_row.find("td", class_="guests-td")
                    away_team = away_team_cell.find("a", class_="player").get_text(strip=True)
                    
                    print("\nEXTRACTED KHL DATA:")
                    print(f"Kickoff: {kickoff}")
                    print(f"Status: {status}")
                    print(f"Home Team: {home_team}")
                    print(f"Score: {score_left} - {score_right}")
                    print(f"Away Team: {away_team}")
                except Exception as e:
                    print(f"Error extracting KHL data: {e}")
        
        # Debug NHL table (second table)
        if len(tables) > 1:
            nhl_table = tables[1]
            match_rows = nhl_table.find_all("tr", attrs={"data-match-id": True})
            print(f"\nFound {len(match_rows)} match rows in second table (NHL)")
            
            if match_rows:
                sample_row = match_rows[0]
                print("\nSAMPLE NHL MATCH ROW:")
                print("-" * 40)
                print(sample_row.prettify()[:1000])
                print("-" * 40)
                
                # Try to extract key elements
                try:
                    cells = sample_row.find_all("td")
                    kickoff = cells[0].get_text(strip=True)
                    status = cells[1].get_text(strip=True)
                    
                    home_team_cell = sample_row.find("td", class_="owner-td")
                    home_team = home_team_cell.find("a", class_="player").get_text(strip=True)
                    
                    score_cell = sample_row.find("td", class_="score-td")
                    score_left = score_cell.find("span", class_="s-left").get_text(strip=True)
                    score_right = score_cell.find("span", class_="s-right").get_text(strip=True)
                    
                    away_team_cell = sample_row.find("td", class_="guests-td")
                    away_team = away_team_cell.find("a", class_="player").get_text(strip=True)
                    
                    print("\nEXTRACTED NHL DATA:")
                    print(f"Kickoff: {kickoff}")
                    print(f"Status: {status}")
                    print(f"Home Team: {home_team}")
                    print(f"Score: {score_left} - {score_right}")
                    print(f"Away Team: {away_team}")
                except Exception as e:
                    print(f"Error extracting NHL data: {e}")
    else:
        print("Could not find match-center div")


def save_results(conn: sqlite3.Connection, results: List[Dict], dry_run: bool = False):
    """Save parsed results to the database."""
    if dry_run:
        print(f"DRY RUN: Would save {len(results)} results to database")
        for result in results:
            print(f"  {result['home_team']} {result['home_score']} - {result['away_score']} {result['away_team']}")
        return
    
    cursor = conn.cursor()
    
    for result in results:
        # Check if this result already exists
        cursor.execute("""
        SELECT id FROM results_raw 
        WHERE league = ? AND match_date = ? AND home_team = ? AND away_team = ?
        """, (result["league"], result["match_date"], result["home_team"], result["away_team"]))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute("""
            UPDATE results_raw SET
                kickoff = ?,
                home_score = ?,
                away_score = ?,
                is_finished = ?,
                source = ?
            WHERE id = ?
            """, (
                result["kickoff"],
                result["home_score"],
                result["away_score"],
                result["is_finished"],
                result["source"],
                existing[0]
            ))
            print(f"Updated: {result['home_team']} {result['home_score']} - {result['away_score']} {result['away_team']}")
        else:
            # Insert new record
            cursor.execute("""
            INSERT INTO results_raw (
                league, match_date, kickoff, home_team, away_team,
                home_score, away_score, is_finished, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result["league"],
                result["match_date"],
                result["kickoff"],
                result["home_team"],
                result["away_team"],
                result["home_score"],
                result["away_score"],
                result["is_finished"],
                result["source"]
            ))
            print(f"Inserted: {result['home_team']} {result['home_score']} - {result['away_score']} {result['away_team']}")
    
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Parse hockey results from sports.ru")
    parser.add_argument("--debug-structure", action="store_true", help="Debug the HTML structure")
    parser.add_argument("--date", type=str, help="Date in YYYY-MM-DD format")
    parser.add_argument("--days", type=int, default=1, help="Number of days to parse (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    parser.add_argument("--league", type=str, choices=["khl", "nhl", "all"], default="all", 
                        help="League to parse (khl, nhl, or all) (default: all)")
    args = parser.parse_args()
    
    # Connect to the database
    conn = get_conn()
    ensure_schema(conn)
    
    # Set the date to parse
    if args.date:
        try:
            start_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid date format. Please use YYYY-MM-DD.")
            return 1
    else:
        # Default to yesterday
        start_date = (datetime.now() - timedelta(days=1)).date()
    
    # Process each day
    for day_offset in range(args.days):
        current_date = start_date - timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")
        url = f"https://www.sports.ru/hockey/match/{date_str}/"
        
        print(f"Fetching hockey results for {date_str} from sports.ru...")
        
        try:
            html = fetch_html(url)
            print(f"Successfully fetched HTML ({len(html)} bytes)")
            
            if args.debug_structure:
                print("Debug mode enabled. Analyzing HTML structure...")
                debug_structure(html)
                continue
            
            all_results = []
            
            # Parse KHL matches if requested
            if args.league in ["khl", "all"]:
                khl_results = parse_khl_matches(html, date_str)
                print(f"Found {len(khl_results)} finished KHL matches for {date_str}")
                all_results.extend(khl_results)
            
            # Parse NHL matches if requested
            if args.league in ["nhl", "all"]:
                nhl_results = parse_nhl_matches(html, date_str)
                print(f"Found {len(nhl_results)} finished NHL matches for {date_str}")
                all_results.extend(nhl_results)
            
            # Save results to database
            save_results(conn, all_results, args.dry_run)
            
        except Exception as e:
            print(f"Error processing {date_str}: {e}")
            if args.days > 1:
                print("Continuing with next date...")
                continue
            else:
                return 1
    
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
