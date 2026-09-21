#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер исторических данных тенниса с betz.su
ATP 250/500/1000, WTA 250/500/1000. Без пар, челленджеров, ITF.
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
RESULTS_URL = "https://betz.su/res/result.php"
SPORT_NAME = "Теннис"

TARGET_LEAGUES = ["ATP 250", "ATP 500", "ATP 1000", "WTA 250", "WTA 500", "WTA 1000"]
SKIP_KEYWORDS = ["двойные", "эйсы", "Пары", "Челлендж", "Challenger", "ITF", "Юниоры", "Итого", "Статистика"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://betz.su/",
}

def fetch(url: str, session: requests.Session) -> str:
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                log.warning(f"Ошибка {url}: {e}")
                return ""
    return ""

def detect_surface(league_name: str) -> str:
    l = league_name.lower()
    if "clay" in l or "грунт" in l: return "clay"
    if "grass" in l or "трава" in l: return "grass"
    if "hard" in l or "хард" in l: return "hard"
    if "indoor" in l: return "indoor"
    return "unknown"

def detect_tour(league_name: str) -> str:
    if "WTA" in league_name: return "WTA"
    if "ATP" in league_name: return "ATP"
    return "unknown"

def detect_level(league_name: str) -> str:
    for level in ["1000", "500", "250"]:
        if level in league_name:
            return level
    return "unknown"

def parse_score(text: str) -> tuple:
    """Парсит счёт матча типа '2:1 (6:2, 4:6, 7:5)'"""
    m = re.match(r"(\d+):(\d+)", text or "")
    if not m:
        return None, None
    sets_w = int(m.group(1))
    sets_l = int(m.group(2))
    sets = re.findall(r"(\d+):(\d+)", text)
    return sets_w, sets_l

def parse_detail(html: str) -> dict:
    """Парсит детальную страницу матча."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    
    result = {
        "odds_p1": None,
        "odds_p2": None,
        "odds_total_over": None,
        "odds_total_under": None,
        "total_line": None,
        "odds_handicap_p1": None,
        "odds_handicap_p2": None,
        "handicap_line": None,
        "sets_winner": None,
        "sets_loser": None,
        "score_detail": None,
        "tiebreak": False,
        "surface": None,
    }
    
    # П1/П2
    m = re.search(r"П1\s*[-–]\s*([\d.]+)", text)
    if m: result["odds_p1"] = float(m.group(1))
    m = re.search(r"П2\s*[-–]\s*([\d.]+)", text)
    if m: result["odds_p2"] = float(m.group(1))
    
    # Тотал основной
    m = re.search(r"ТМ\s*\(([\d.]+)\)\s*[-–]\s*([\d.]+)", text)
    if m:
        result["total_line"] = float(m.group(1))
        result["odds_total_under"] = float(m.group(2))
    m = re.search(r"ТБ\s*\(([\d.]+)\)\s*[-–]\s*([\d.]+)", text)
    if m:
        result["total_line"] = float(m.group(1))
        result["odds_total_over"] = float(m.group(2))
    
    # Фора
    m = re.search(r"Ф1\s*\(([-\d.]+)\)\s*[-–]\s*([\d.]+)", text)
    if m:
        result["handicap_line"] = float(m.group(1))
        result["odds_handicap_p1"] = float(m.group(2))
    m = re.search(r"Ф2\s*\(([\d.]+)\)\s*[-–]\s*([\d.]+)", text)
    if m:
        result["odds_handicap_p2"] = float(m.group(2))
    
    # Счёт матча
    m = re.search(r"Результат матча.*?(\d+):(\d+)\s*\(([^)]+)\)", text)
    if m:
        result["sets_winner"] = int(m.group(1))
        result["sets_loser"] = int(m.group(2))
        result["score_detail"] = m.group(3)
    
    # Тай-брейк
    if "тай-брейк" in text.lower() and "не был" not in text.lower():
        result["tiebreak"] = True
    
    return result

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_tennis_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tour TEXT,
            level TEXT,
            tournament TEXT,
            surface TEXT,
            match_date TEXT,
            player1 TEXT,
            player2 TEXT,
            sets_winner INTEGER,
            sets_loser INTEGER,
            score_detail TEXT,
            tiebreak INTEGER DEFAULT 0,
            odds_p1 REAL,
            odds_p2 REAL,
            odds_total_over REAL,
            odds_total_under REAL,
            total_line REAL,
            odds_handicap_p1 REAL,
            odds_handicap_p2 REAL,
            handicap_line REAL,
            winner INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_date ON backtest_tennis_matches(match_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_tour ON backtest_tennis_matches(tour, level, surface)")
    conn.commit()

def save_match(conn, row: dict) -> bool:
    existing = conn.execute("""
        SELECT id FROM backtest_tennis_matches
        WHERE match_date=? AND player1=? AND player2=? AND tour=?
    """, (row["match_date"], row["player1"], row["player2"], row["tour"])).fetchone()
    if existing:
        return False
    conn.execute("""
        INSERT INTO backtest_tennis_matches
        (tour, level, tournament, surface, match_date, player1, player2,
         sets_winner, sets_loser, score_detail, tiebreak,
         odds_p1, odds_p2, odds_total_over, odds_total_under, total_line,
         odds_handicap_p1, odds_handicap_p2, handicap_line, winner)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        row["tour"], row["level"], row["tournament"], row["surface"],
        row["match_date"], row["player1"], row["player2"],
        row.get("sets_winner"), row.get("sets_loser"), row.get("score_detail"),
        1 if row.get("tiebreak") else 0,
        row.get("odds_p1"), row.get("odds_p2"),
        row.get("odds_total_over"), row.get("odds_total_under"), row.get("total_line"),
        row.get("odds_handicap_p1"), row.get("odds_handicap_p2"), row.get("handicap_line"),
        1  # winner всегда player1 (победитель всегда первый в betz.su)
    ))
    conn.commit()
    return True

def parse_day(html: str, date_str: str, session: requests.Session, delay: float) -> int:
    soup = BeautifulSoup(html, "html.parser")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)
    
    saved = 0
    cc_divs = soup.find_all("div", id="cc")
    
    for league_div in cc_divs:
        league_name = league_div.get_text(strip=True)
        
        if any(kw in league_name for kw in SKIP_KEYWORDS):
            continue
        if not any(tl in league_name for tl in TARGET_LEAGUES):
            continue
        
        surface = detect_surface(league_name)
        tour = detect_tour(league_name)
        level = detect_level(league_name)
        tournament = re.sub(r"Теннис\.\s*", "", league_name).strip()
        
        matches_div = league_div.find_next_sibling("div")
        if not matches_div:
            continue
        
        links = matches_div.find_all("a", href=re.compile(r"detail=\d+"))
        for link in links:
            teams_text = link.get_text(strip=True)
            if " - " not in teams_text:
                continue
            player1, player2 = [x.strip() for x in teams_text.split(" - ", 1)]
            
            detail_url = f"https://betz.su{link['href']}"
            time.sleep(delay)
            detail_html = fetch(detail_url, session)
            if not detail_html:
                continue
            
            odds = parse_detail(detail_html)
            row = {
                "tour": tour,
                "level": level,
                "tournament": tournament,
                "surface": surface,
                "match_date": date_str,
                "player1": player1,
                "player2": player2,
                **odds,
            }
            
            if save_match(conn, row):
                saved += 1
                log.info(f"  [{tour}{level}][{surface}] {player1} vs {player2} | П1={odds.get('odds_p1')} П2={odds.get('odds_p2')} ТБ={odds.get('odds_total_over')}")
    
    conn.close()
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-from", default="2021-01-01")
    ap.add_argument("--date-to", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)

    dt = datetime.strptime(args.date_from, "%Y-%m-%d")
    dt_end = datetime.strptime(args.date_to, "%Y-%m-%d")

    total = 0
    while dt <= dt_end:
        date_str_req = dt.strftime("%d.%m.%Y")
        date_str_db = dt.strftime("%Y-%m-%d")
        url = f"{RESULTS_URL}?date={quote(date_str_req)}&sport={quote(SPORT_NAME)}"
        
        session2 = requests.Session()
        session2.headers.update(HEADERS)
        html = fetch(url, session2)
        
        if html:
            saved = parse_day(html, date_str_db, session, args.delay)
            if saved:
                log.info(f"{date_str_req}: +{saved} матчей")
            total += saved
        
        dt += timedelta(days=1)
        time.sleep(args.delay)

    log.info(f"Готово! Всего: +{total} матчей")

if __name__ == "__main__":
    main()
