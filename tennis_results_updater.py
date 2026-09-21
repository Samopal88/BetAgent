#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — Tennis Live Results Updater

Fetches completed tennis match results from betz.su (daily updated,
Russian player names matching Fonbet format) and stores them in
`tennis_live_results` table for live settlement.

Usage:
    python tennis_results_updater.py              # today
    python tennis_results_updater.py --days 3     # last 3 days
    python tennis_results_updater.py --date 2026-04-10
"""
import argparse
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://betz.su/",
}

# Only parse top-tier tournaments for settlement quality
TARGET_LEVELS = ["ATP 250", "ATP 500", "ATP 1000", "ATP Мастерс", "WTA 250", "WTA 500", "WTA 1000", "Challenger"]
SKIP_KEYWORDS = [
    "двойные", "эйсы", "Пары",
    "ITF", "Юниоры", "Итого", "Статистика",
]
# Qualifying and Challenger are allowed — results coverage is broader than betting universe.
# Betting pipeline blocks Challenger/ITF/qualifying via _BLOCKED_TOUR_KEYWORDS in tennis_live_pipeline.py.

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tennis_results")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn: sqlite3.Connection):
    """Create tennis_live_results if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_live_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tour TEXT,
            level TEXT,
            tournament TEXT,
            surface TEXT,
            match_date TEXT,
            winner_name TEXT,
            loser_name TEXT,
            sets_winner INTEGER,
            sets_loser INTEGER,
            score_detail TEXT,
            source TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_live_results_date ON tennis_live_results(match_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_live_results_winner ON tennis_live_results(winner_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_live_results_loser ON tennis_live_results(loser_name)")
    conn.commit()

    # Migrate old columns if they exist
    cols = [row[1] for row in conn.execute("PRAGMA table_info(tennis_live_results)").fetchall()]
    if "player1" in cols and "winner_name" not in cols:
        # Old schema: rename player1->winner_name, player2->loser_name, drop winner/loser
        conn.execute("ALTER TABLE tennis_live_results RENAME COLUMN player1 TO winner_name")
        conn.execute("ALTER TABLE tennis_live_results RENAME COLUMN player2 TO loser_name")
        conn.execute("DROP INDEX IF EXISTS idx_tennis_live_results_players")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_live_results_winner ON tennis_live_results(winner_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_live_results_loser ON tennis_live_results(loser_name)")
        conn.commit()
        log.info("Migrated tennis_live_results: player1->winner_name, player2->loser_name")


def fetch_html(url: str) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                log.warning(f"Fetch error {url}: {e}")
                return ""
    return ""


def parse_score(text: str) -> tuple:
    """Parse match score like '2:1 (6:2, 4:6, 7:5)'."""
    m = re.match(r"(\d+):(\d+)", text or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def detect_surface(league_name: str) -> str:
    l = league_name.lower()
    if "clay" in l or "грунт" in l:
        return "clay"
    if "grass" in l or "трава" in l:
        return "grass"
    if "hard" in l or "хард" in l:
        return "hard"
    if "indoor" in l:
        return "indoor"
    return "unknown"


def detect_tour(league_name: str) -> str:
    if "WTA" in league_name:
        return "WTA"
    if "ATP" in league_name:
        return "ATP"
    return "unknown"


def detect_level(league_name: str) -> str:
    for level in ["1000", "500", "250"]:
        if level in league_name:
            return level
    return "unknown"


def parse_day(html: str, date_str: str) -> list[dict]:
    """Parse one day of tennis results from betz.su HTML.

    betz.su HTML structure per match:
        <a href="/line/?detail=...">Player1 - Player2</a>
        <u>sets_score (set1, set2, ...)</u>
        <br>

    The first player is NOT always the winner — the score determines it.
    Score format: "2:0 (6:4, 6:2)" means player1 won 2 sets to 0.
    Score format: "0:2 (2:6, 1:6)" means player2 won 2 sets to 0.
    Score format: "1:2 (6:4, 4:6, 4:6)" means player2 won 2 sets to 1.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    cc_divs = soup.find_all("div", id="cc")

    for league_div in cc_divs:
        league_name = league_div.get_text(strip=True)

        # Skip non-target leagues
        if any(kw in league_name for kw in SKIP_KEYWORDS):
            continue
        if not any(tl in league_name for tl in TARGET_LEVELS):
            continue

        surface = detect_surface(league_name)
        tour = detect_tour(league_name)
        level = detect_level(league_name)
        tournament = re.sub(r"Теннис\.\s*", "", league_name).strip()

        matches_div = league_div.find_next_sibling("div")
        if not matches_div:
            continue

        # Get <a> and <u> elements in document order
        all_elements = matches_div.find_all(["a", "u"])

        i = 0
        while i < len(all_elements):
            el = all_elements[i]
            if el.name != "a":
                i += 1
                continue

            teams_text = el.get_text(strip=True)
            if " - " not in teams_text:
                i += 1
                continue

            player1, player2 = [x.strip() for x in teams_text.split(" - ", 1)]

            # Look for score in the next <u> element
            score_text = None
            if i + 1 < len(all_elements) and all_elements[i + 1].name == "u":
                score_text = all_elements[i + 1].get_text(strip=True)

            # Determine winner from score
            sets_winner = None
            sets_loser = None
            score_detail = None

            if score_text:
                # Check for cancelled match first
                if 'отмена' in score_text.lower() or 'не состоялся' in score_text.lower():
                    results.append({
                        "tour": tour,
                        "level": level,
                        "tournament": tournament,
                        "surface": surface,
                        "match_date": date_str,
                        "winner_name": player1,
                        "loser_name": player2,
                        "sets_winner": None,
                        "sets_loser": None,
                        "score_detail": score_text,
                        "source": "betz_su",
                        "cancelled": True,
                    })
                    i += 1
                    continue

                m = re.match(r"(\d+):(\d+)", score_text)
                if m:
                    s1 = int(m.group(1))
                    s2 = int(m.group(2))
                    sets_winner = max(s1, s2)
                    sets_loser = min(s1, s2)
                    score_detail = score_text

                    # Winner is the player whose set count is higher
                    if s1 > s2:
                        winner = player1
                        loser = player2
                    elif s2 > s1:
                        winner = player2
                        loser = player1
                    else:
                        # Tie in sets — shouldn't happen in tennis, but handle gracefully
                        winner = player1
                        loser = player2
                else:
                    # Score present but unparseable — skip this match
                    i += 1
                    continue
            else:
                # No score found — skip this match (can't determine winner)
                i += 1
                continue

            results.append({
                "tour": tour,
                "level": level,
                "tournament": tournament,
                "surface": surface,
                "match_date": date_str,
                "winner_name": winner,
                "loser_name": loser,
                "sets_winner": sets_winner,
                "sets_loser": sets_loser,
                "score_detail": score_detail,
                "source": "betz_su",
            })

            i += 1

    return results


def save_results(conn: sqlite3.Connection, results: list[dict]) -> int:
    """Insert results, skip duplicates. Returns count of new entries."""
    saved = 0
    for r in results:
        existing = conn.execute("""
            SELECT id FROM tennis_live_results
            WHERE match_date=? AND winner_name=? AND loser_name=? AND tour=?
        """, (r["match_date"], r["winner_name"], r["loser_name"], r["tour"])).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT INTO tennis_live_results
            (tour, level, tournament, surface, match_date, winner_name, loser_name,
             sets_winner, sets_loser, score_detail, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["tour"], r["level"], r["tournament"], r["surface"],
            r["match_date"], r["winner_name"], r["loser_name"],
            r.get("sets_winner"), r.get("sets_loser"), r.get("score_detail"),
            r["source"],
        ))
        saved += 1
        if r.get("cancelled"):
            log.info(f"  [{r['tour']}{r['level']}][{r['surface']}] CANCELLED: {r['winner_name']} vs {r['loser_name']} ({r.get('score_detail', '?')})")
        else:
            log.info(f"  [{r['tour']}{r['level']}][{r['surface']}] {r['winner_name']} beat {r['loser_name']} ({r.get('score_detail', '?')})")
    conn.commit()
    return saved


def fetch_results(date_from: str, date_to: str) -> int:
    """Fetch tennis results for a date range. Returns total new entries."""
    conn = get_conn()
    ensure_table(conn)

    dt = datetime.strptime(date_from, "%Y-%m-%d")
    dt_end = datetime.strptime(date_to, "%Y-%m-%d")
    total = 0

    while dt <= dt_end:
        date_str_req = dt.strftime("%d.%m.%Y")
        date_str_db = dt.strftime("%Y-%m-%d")
        url = f"https://betz.su/res/result.php?date={quote(date_str_req)}&sport=%D0%A2%D0%B5%D0%BD%D0%BD%D0%B8%D1%81"

        log.info(f"Fetching {date_str_db}...")
        html = fetch_html(url)

        if html:
            results = parse_day(html, date_str_db)
            if results:
                saved = save_results(conn, results)
                log.info(f"  {date_str_db}: {len(results)} found, {saved} new")
                total += saved

        dt += timedelta(days=1)
        time.sleep(0.3)

    conn.close()
    return total


def lookup_result(conn: sqlite3.Connection, p1_eng: str, p2_eng: str,
                   match_date: str, name_map: dict | None = None) -> str | None:
    """
    Look up a tennis match result in tennis_live_results.
    Returns 'p1_won', 'p2_won', or None if not found.

    Uses English player names from the signal and maps them to Russian
    names via the tennis_player_mapping table for lookup.
    Compares the bet pick against explicit winner_name — not player positions.

    Uses COLLATE NOCASE for Cyrillic-aware matching (SQLite LOWER() doesn't
    handle Cyrillic characters).
    """
    # Build reverse mapping: English -> Russian
    rus_p1 = None
    rus_p2 = None

    if name_map:
        # name_map is Russian -> English, reverse it
        eng_to_rus = {v: k for k, v in name_map.items()}
        rus_p1 = eng_to_rus.get(p1_eng)
        rus_p2 = eng_to_rus.get(p2_eng)

    def _extract_surname(rus_name: str) -> str:
        if not rus_name:
            return ""
        parts = rus_name.strip().replace('.', '').split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    # Try matching with Russian names (surname-based, handles format differences)
    if rus_p1 and rus_p2:
        s1 = _extract_surname(rus_p1)
        s2 = _extract_surname(rus_p2)
        row = conn.execute("""
            SELECT winner_name FROM tennis_live_results
            WHERE match_date = ?
              AND (
                  (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                   AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                  OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                      AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
              )
            LIMIT 1
        """, (match_date, s1, s2, s2, s1)).fetchone()
        if row:
            winner_rus = row[0]
            if s1.lower() in winner_rus.lower():
                return "p1_won"
            return "p2_won"
    elif rus_p1:
        s1 = _extract_surname(rus_p1)
        row = conn.execute("""
            SELECT winner_name FROM tennis_live_results
            WHERE match_date = ?
              AND (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                   OR loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
            LIMIT 1
        """, (match_date, s1, s1)).fetchone()
        if row:
            winner_rus = row[0]
            if s1.lower() in winner_rus.lower():
                return "p1_won"
            return "p2_won"
    elif rus_p2:
        s2 = _extract_surname(rus_p2)
        row = conn.execute("""
            SELECT winner_name FROM tennis_live_results
            WHERE match_date = ?
              AND (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                   OR loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
            LIMIT 1
        """, (match_date, s2, s2)).fetchone()
        if row:
            winner_rus = row[0]
            if s2.lower() in winner_rus.lower():
                return "p2_won"
            return "p1_won"

    return None


def main():
    ap = argparse.ArgumentParser(description="Tennis Live Results Updater")
    ap.add_argument("--date", default=None, help="Specific date (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, default=3, help="Number of days to fetch (default: 3)")
    args = ap.parse_args()

    if args.date:
        date_from = args.date
        date_to = args.date
    else:
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")

    total = fetch_results(date_from, date_to)
    log.info(f"Done: {total} new results saved ({date_from} to {date_to})")


if __name__ == "__main__":
    main()
