#!/usr/bin/env python3
"""
Parse historical xG data from FBref via Wayback Machine for top European leagues.

Fetches schedule pages with xG columns from archived FBref pages,
extracts match-level xG data, and stores in betagent.db.

Pre-resolved Wayback URLs (CDX API is too slow for runtime lookup).
"""

import sqlite3
import re
import time
import urllib.request
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"

# Pre-resolved Wayback URLs: (comp_id, league, season, wayback_url)
# Some URLs return 404 from Wayback even though CDX lists them — those are skipped.
# Some pages have multiple tables (by round) — parser handles this.
WAYBACK_URLS = [
    # EPL (comp/9)
    (9,  "EPL", 2019, "https://web.archive.org/web/20221207162811/https://fbref.com/en/comps/9/2019-2020/schedule/2019-2020-Premier-League-Scores-and-Fixtures"),
    (9,  "EPL", 2020, "https://web.archive.org/web/20221002130707/https://fbref.com/en/comps/9/2020-2021/schedule/2020-2021-Premier-League-Scores-and-Fixtures"),
    # EPL 2021: CDX found but Wayback returns 404
    # EPL 2022: CDX found but Wayback returns 404
    # EPL 2023: NOT FOUND in Wayback
    (9,  "EPL", 2024, "https://web.archive.org/web/20250808165023/https://fbref.com/en/comps/9/2024-2025/schedule/2024-2025-Premier-League-Scores-and-Fixtures"),
    (9,  "EPL", 2025, "https://web.archive.org/web/20250826125255/https://fbref.com/en/comps/9/2025-2026/schedule/2025-2026-Premier-League-Scores-and-Fixtures"),

    # La Liga (comp/12)
    (12, "La Liga", 2019, "https://web.archive.org/web/20221001184731/https://fbref.com/en/comps/12/2019-2020/schedule/2019-2020-La-Liga-Scores-and-Fixtures"),
    # La Liga 2020: CDX found but Wayback returns 404
    # La Liga 2021: NOT FOUND in Wayback
    (12, "La Liga", 2022, "https://web.archive.org/web/20200930094819/https://fbref.com/en/comps/12/schedule/La-Liga-Scores-and-Fixtures"),
    (12, "La Liga", 2023, "https://web.archive.org/web/20241227164019/https://fbref.com/en/comps/12/2023-2024/schedule/2023-2024-La-Liga-Scores-and-Fixtures"),
    # La Liga 2024: CDX found but Wayback returns 404

    # Ligue 1 (comp/13)
    (13, "Ligue 1", 2019, "https://web.archive.org/web/20230208145729/https://fbref.com/en/comps/13/2019-2020/schedule/2019-2020-Ligue-1-Scores-and-Fixtures"),
    # Ligue 1 2020: CDX found but Wayback returns 404
    # Ligue 1 2021: page loads but xG in different table structure (multi-round)
    (13, "Ligue 1", 2021, "https://web.archive.org/web/20251105120315/https://fbref.com/en/comps/13/2021-2022/schedule/2021-2022-Ligue-1-Scores-and-Fixtures"),
    (13, "Ligue 1", 2022, "https://web.archive.org/web/20251116023033/https://fbref.com/en/comps/13/2022-2023/schedule/2022-2023-Ligue-1-Scores-and-Fixtures"),
    (13, "Ligue 1", 2023, "https://web.archive.org/web/20201028235314/https://fbref.com/en/comps/13/schedule/Ligue-1-Scores-and-Fixtures"),
    # Ligue 1 2024: page loads but xG in different table structure (multi-round)
    (13, "Ligue 1", 2024, "https://web.archive.org/web/20250814194017/https://fbref.com/en/comps/13/2024-2025/schedule/2024-2025-Ligue-1-Scores-and-Fixtures"),

    # Bundesliga (comp/20)
    # Bundesliga 2019: NOT FOUND in Wayback
    # Bundesliga 2020: page loads but xG in different table structure (multi-round)
    (20, "Bundesliga", 2020, "https://web.archive.org/web/20241112092330/https://fbref.com/en/comps/20/2020-2021/schedule/2020-2021-Bundesliga-Scores-and-Fixtures"),
    # Bundesliga 2021: page loads but xG in different table structure (multi-round)
    (20, "Bundesliga", 2021, "https://web.archive.org/web/20241113120218/https://fbref.com/en/comps/20/2021-2022/schedule/2021-2022-Bundesliga-Scores-and-Fixtures"),
    # Bundesliga 2022: CDX found but Wayback returns 404
    (20, "Bundesliga", 2023, "https://web.archive.org/web/20241202205333/https://fbref.com/en/comps/20/2023-2024/schedule/2023-2024-Bundesliga-Scores-and-Fixtures"),
    (20, "Bundesliga", 2024, "https://web.archive.org/web/20201026182629/https://fbref.com/en/comps/20/schedule/Bundesliga-Scores-and-Fixtures"),

    # Serie A (comp/11)
    # Serie A 2019: CDX found but Wayback returns 404
    (11, "Serie A", 2020, "https://web.archive.org/web/20200930113547/https://fbref.com/en/comps/11/schedule/Serie-A-Scores-and-Fixtures"),
    (11, "Serie A", 2021, "https://web.archive.org/web/20230224175727/https://fbref.com/en/comps/11/2021-2022/schedule/2021-2022-Serie-A-Scores-and-Fixtures"),
    # Serie A 2022: CDX found but Wayback returns 404
    # Serie A 2023: connection refused
    (11, "Serie A", 2024, "https://web.archive.org/web/20200930113547/https://fbref.com/en/comps/11/schedule/Serie-A-Scores-and-Fixtures"),

    # Eredivisie (comp/23)
    # Eredivisie 2019: CDX found but Wayback returns 404
    # Eredivisie 2020: connection refused
    # Eredivisie 2021: CDX found but Wayback returns 404
    # Eredivisie 2022: page loads but no xG in table
    # Eredivisie 2023: connection refused
    # Eredivisie 2024: connection refused

    # Primeira Liga (comp/32)
    (32, "Primeira Liga", 2019, "https://web.archive.org/web/20230530021720/https://fbref.com/en/comps/32/2019-2020/schedule/2019-2020-Primeira-Liga-Scores-and-Fixtures"),
    (32, "Primeira Liga", 2025, "https://web.archive.org/web/20250714232311/https://fbref.com/en/comps/32/2025-2026/schedule/2025-2026-Primeira-Liga-Scores-and-Fixtures"),
    # Primeira Liga 2020: connection refused
    # Primeira Liga 2021: connection refused
    # Primeira Liga 2022: CDX found but Wayback returns 404
    # Primeira Liga 2023: connection refused
    # Primeira Liga 2024: connection refused
]

# Seasons that are missing or unreachable
MISSING = [
    ("EPL", 2021, "Wayback 404"),
    ("EPL", 2022, "Wayback 404"),
    ("EPL", 2023, "No Wayback capture"),
    ("La Liga", 2020, "Wayback 404"),
    ("La Liga", 2021, "No Wayback capture"),
    ("La Liga", 2024, "Wayback 404"),
    ("La Liga", 2025, "No Wayback capture"),
    ("Ligue 1", 2020, "Wayback 404"),
    ("Ligue 1", 2025, "No Wayback capture"),
    ("Bundesliga", 2019, "No Wayback capture"),
    ("Bundesliga", 2022, "Wayback 404"),
    ("Bundesliga", 2025, "No Wayback capture"),
    ("Serie A", 2019, "Wayback 404"),
    ("Serie A", 2022, "Wayback 404"),
    ("Serie A", 2023, "Connection refused"),
    ("Serie A", 2025, "No Wayback capture"),
    ("Eredivisie", 2019, "Wayback 404"),
    ("Eredivisie", 2020, "Connection refused"),
    ("Eredivisie", 2021, "Wayback 404"),
    ("Eredivisie", 2022, "No xG data"),
    ("Eredivisie", 2023, "Connection refused"),
    ("Eredivisie", 2024, "Connection refused"),
    ("Eredivisie", 2025, "No Wayback capture"),
    ("Primeira Liga", 2020, "Connection refused"),
    ("Primeira Liga", 2021, "Connection refused"),
    ("Primeira Liga", 2022, "Wayback 404"),
    ("Primeira Liga", 2023, "Connection refused"),
    ("Primeira Liga", 2024, "Connection refused"),
]


def create_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fbref_xg (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fbref_match_id TEXT,
            league TEXT,
            comp_id INTEGER,
            season INTEGER,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_xg REAL,
            away_xg REAL,
            source_url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(league, season, match_date, home_team, away_team)
        )
    """)
    conn.commit()


def fetch_page(wayback_url, retries=2):
    """Fetch page content from Wayback Machine."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                wayback_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            resp = urllib.request.urlopen(req, timeout=45)
            return resp.read().decode("utf-8", errors="replace"), None
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            return None, str(e)
    return None, "max retries"


def clean_cell(html):
    """Strip HTML tags and clean up cell text."""
    text = re.sub(r'<[^>]+>', '', html).strip()
    text = re.sub(r'\[[a-z0-9]+\]', '', text).strip()
    text = text.replace('&ndash;', '-').replace('&mdash;', '-')
    return text


def parse_row(cells):
    """Parse a single row of cells into match data. Returns dict or None."""
    if len(cells) < 9:
        return None

    # Column mapping:
    # [0]Wk, [1]Day, [2]Date, [3]Time, [4]Home, [5]xG(Home), [6]Score, [7]xG(Away), [8]Away, ...
    date_str = clean_cell(cells[2])
    home_team = clean_cell(cells[4])
    home_xg_str = clean_cell(cells[5])
    score_str = clean_cell(cells[6])
    away_xg_str = clean_cell(cells[7])
    away_team = clean_cell(cells[8])

    if not home_team or not away_team:
        return None

    # Parse score
    score_match = re.match(r'(\d+)\s*[-\u2013\u2014]\s*(\d+)', score_str)
    if not score_match:
        return None

    home_score = int(score_match.group(1))
    away_score = int(score_match.group(2))

    # Parse xG
    home_xg = None
    away_xg = None
    if home_xg_str:
        try:
            home_xg = float(home_xg_str)
        except ValueError:
            pass
    if away_xg_str:
        try:
            away_xg = float(away_xg_str)
        except ValueError:
            pass

    if home_xg is None and away_xg is None:
        return None

    match_date = normalize_date(date_str)
    fbref_match_id = f"{home_team}_{away_team}_{match_date}"

    return {
        "fbref_match_id": fbref_match_id,
        "match_date": match_date,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "home_xg": home_xg,
        "away_xg": away_xg,
    }


def parse_xg_table(html_content):
    """
    Parse ALL schedule tables from FBref page and extract match data with xG.

    FBref pages can have multiple tables:
    - sched_all: aggregate table (all rounds combined)
    - sched_YYYY_N_1: round 1
    - sched_YYYY_N_2: round 2
    - etc.

    Each data row has: 1 <th> (week number) + many <td> cells.
    Header row has: many <th> cells, no <td>.
    """
    # Find all tables with xG data
    all_tables = re.findall(
        r'<table[^>]*id="(sched_[^"]+)"[^>]*>(.*?)</table>',
        html_content, re.DOTALL
    )

    matches = []
    seen_ids = set()

    for table_id, table_html in all_tables:
        # Skip if no xG
        if 'data-name="xG' not in table_html:
            continue

        # Extract rows
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

        for row in rows:
            # Skip header rows (many <th>, no <td>)
            th_count = len(re.findall(r'<th', row))
            td_count = len(re.findall(r'<td', row))
            if th_count > 1 and td_count == 0:
                continue
            if 'class="thead"' in row:
                continue

            # Get all cells (both th and td)
            all_cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
            if len(all_cells) < 9:
                continue

            result = parse_row(all_cells)
            if result is None:
                continue

            # Deduplicate across tables
            if result["fbref_match_id"] in seen_ids:
                continue
            seen_ids.add(result["fbref_match_id"])
            matches.append(result)

    return matches


def normalize_date(date_str):
    """Normalize date string to YYYY-MM-DD format."""
    if not date_str:
        return ""

    formats = [
        "%a %Y-%m-%d",     # Fri 2024-08-16
        "%Y-%m-%d",         # 2024-08-16
        "%a %d %b %Y",     # Fri 16 Aug 2024
        "%d %b %Y",         # 16 Aug 2024
        "%b %d, %Y",        # Aug 16, 2024
        "%d %B %Y",         # 16 August 2024
        "%B %d, %Y",        # August 16, 2024
        "%a %b %d %Y",     # Fri Aug 16 2024
        "%a, %b %d, %Y",   # Fri, Aug 16, 2024
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str.strip()


def save_matches(conn, matches, league, comp_id, season, source_url):
    """Save matches to database, return (inserted, skipped, xg_count, total)."""
    inserted = 0
    skipped = 0
    xg_count = 0
    total = len(matches)

    for m in matches:
        if m["home_xg"] is not None or m["away_xg"] is not None:
            xg_count += 1

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fbref_xg
                   (fbref_match_id, league, comp_id, season, match_date,
                    home_team, away_team, home_score, away_score,
                    home_xg, away_xg, source_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m["fbref_match_id"], league, comp_id, season,
                    m["match_date"], m["home_team"], m["away_team"],
                    m["home_score"], m["away_score"],
                    m["home_xg"], m["away_xg"], source_url,
                )
            )
            inserted += 1
        except Exception:
            skipped += 1

    conn.commit()
    return inserted, skipped, xg_count, total


def main():
    conn = sqlite3.connect(DB_PATH)
    create_table(conn)

    results = []  # (league, season, url, inserted, skipped, xg_matches, total_matches)

    # Record missing/unreachable seasons
    for league_name, season, reason in MISSING:
        print(f"  SKIP: {league_name} {season} ({reason})")
        results.append((league_name, season, None, 0, 0, 0, 0))

    # Process each resolved URL
    for comp_id, league_name, season, wayback_url in WAYBACK_URLS:
        print(f"\n{'='*60}")
        print(f"Processing: {league_name} season {season} (comp/{comp_id})")
        print(f"  URL: {wayback_url[:100]}...")

        # Fetch page
        html, error = fetch_page(wayback_url)
        if html is None:
            print(f"  FAILED to fetch page: {error}")
            results.append((league_name, season, wayback_url, 0, 0, 0, 0))
            time.sleep(2)
            continue

        print(f"  Page size: {len(html):,} bytes")

        # Parse xG data
        matches = parse_xg_table(html)
        if not matches:
            print(f"  No xG data found in any table")
            results.append((league_name, season, wayback_url, 0, 0, 0, 0))
            time.sleep(2)
            continue

        # Save to DB
        inserted, skipped, xg_count, total = save_matches(
            conn, matches, league_name, comp_id, season, wayback_url
        )

        coverage = (xg_count / total * 100) if total > 0 else 0
        print(f"  Parsed {total} matches, {xg_count} with xG ({coverage:.0f}%), "
              f"inserted {inserted}, skipped {skipped}")

        results.append((league_name, season, wayback_url, inserted, skipped, xg_count, total))

        # Rate limiting between requests
        time.sleep(2)

    # Print summary
    print(f"\n\n{'='*60}")
    print("SUMMARY: FBref xG Data Loaded")
    print(f"{'='*60}")

    all_leagues = ["EPL", "La Liga", "Ligue 1", "Bundesliga", "Serie A", "Eredivisie", "Primeira Liga"]
    for league_name in all_leagues:
        league_results = [r for r in results if r[0] == league_name]
        total_matches = sum(r[6] for r in league_results)
        total_xg = sum(r[5] for r in league_results)
        total_inserted = sum(r[3] for r in league_results)
        coverage = (total_xg / total_matches * 100) if total_matches > 0 else 0

        print(f"\n{league_name}:")
        print(f"  Total matches: {total_matches}")
        print(f"  With xG data:  {total_xg} ({coverage:.0f}%)")
        print(f"  Inserted:      {total_inserted}")

        for _, season, url, inserted, skipped, xg, total in league_results:
            if total > 0:
                cov = (xg / total * 100)
                status = f"{xg}/{total} xG ({cov:.0f}%)"
            else:
                status = "no data" if url else "MISSING"
            print(f"    {season}: {status} (inserted {inserted})")

    # Overall summary
    total_all = sum(r[6] for r in results)
    xg_all = sum(r[5] for r in results)
    inserted_all = sum(r[3] for r in results)
    overall_coverage = (xg_all / total_all * 100) if total_all > 0 else 0

    print(f"\n{'='*60}")
    print(f"OVERALL: {total_all} matches, {xg_all} with xG ({overall_coverage:.0f}%), "
          f"{inserted_all} inserted into DB")
    print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
