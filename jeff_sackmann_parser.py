#!/usr/bin/env python3
"""
Загружает исторические данные ATP/WTA:
1) Jeff Sackmann GitHub — основной источник
2) tennis-data.co.uk (HTTP CSV) — fallback для 2025/2026

Сохраняет в backtest_tennis_players.
"""
import sqlite3
import requests
import csv
import io
import logging
import time
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

YEARS = range(2021, 2027)
FALLBACK_YEARS = {2025, 2026}

JEFF_URLS = {
    "ATP": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv",
    "WTA": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv",
}

TENNIS_DATA_INDEX = "http://www.tennis-data.co.uk/alldata.php"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; betagent/1.0)"})


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_tennis_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tour TEXT, year INTEGER,
            tourney_name TEXT, surface TEXT, tourney_level TEXT,
            tourney_date TEXT, round TEXT,
            winner_name TEXT, winner_rank INTEGER, winner_rank_pts INTEGER,
            loser_name TEXT, loser_rank INTEGER, loser_rank_pts INTEGER,
            score TEXT, best_of INTEGER, minutes INTEGER,
            w_ace INTEGER, w_df INTEGER, w_1stIn INTEGER, w_1stWon INTEGER,
            w_2ndWon INTEGER, w_bpSaved INTEGER, w_bpFaced INTEGER,
            l_ace INTEGER, l_df INTEGER, l_1stIn INTEGER, l_1stWon INTEGER,
            l_2ndWon INTEGER, l_bpSaved INTEGER, l_bpFaced INTEGER,
            sets_winner INTEGER, sets_loser INTEGER,
            straight_sets INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tour, tourney_date, tourney_name, winner_name, loser_name)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_players_winner ON backtest_tennis_players(winner_name, tourney_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_players_loser ON backtest_tennis_players(loser_name, tourney_date)")
    conn.commit()


def parse_score(score: str):
    if not score or score in ("W/O", "DEF", "RET", ""):
        return None, None
    sets = re.findall(r"(\d+)-(\d+)", score)
    if not sets:
        return None, None
    w, l = 0, 0
    for sw, sl in sets:
        sw, sl = int(sw), int(sl)
        if sw > sl:
            w += 1
        else:
            l += 1
    return w, l


def safe_int(val):
    try:
        return int(float(val)) if val is not None and str(val).strip() else None
    except Exception:
        return None


def normalize_date(val: str):
    if not val:
        return None
    val = str(val).strip()
    if len(val) == 8 and val.isdigit():
        return f"{val[:4]}-{val[4:6]}-{val[6:8]}"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return val


def pick_ci(row: dict, *candidates):
    if not row:
        return None
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in lower:
            return lower[key]
    return None


def fetch_text(url: str, timeout: int = 30):
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def load_jeff_csv(tour: str, year: int, conn: sqlite3.Connection):
    url = JEFF_URLS[tour].format(year=year)
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 404:
            return False, 0
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Ошибка загрузки Jeff {tour} {year}: {e}")
        return False, 0

    reader = csv.DictReader(io.StringIO(r.text))
    inserted = 0

    for row in reader:
        score = row.get("score", "")
        if not score or score in ("W/O", "DEF", ""):
            continue

        sets_w, sets_l = parse_score(score)
        if sets_w is None:
            continue

        td = normalize_date(row.get("tourney_date", ""))

        try:
            # Try to get Russian name from mapping table
            rus_w = conn.execute(
                "SELECT rus_name FROM tennis_player_mapping WHERE LOWER(eng_name) = LOWER(?) LIMIT 1",
                (row.get("winner_name"),)
            ).fetchone()
            rus_l = conn.execute(
                "SELECT rus_name FROM tennis_player_mapping WHERE LOWER(eng_name) = LOWER(?) LIMIT 1",
                (row.get("loser_name"),)
            ).fetchone()

            conn.execute("""
                INSERT OR IGNORE INTO backtest_tennis_players
                (tour, year, tourney_name, surface, tourney_level, tourney_date, round,
                 winner_name, winner_rank, winner_rank_pts,
                 loser_name, loser_rank, loser_rank_pts,
                 score, best_of, minutes,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 sets_winner, sets_loser, straight_sets,
                 winner_rus_name, loser_rus_name)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                tour, year,
                row.get("tourney_name"), row.get("surface"), row.get("tourney_level"),
                td, row.get("round"),
                row.get("winner_name"), safe_int(row.get("winner_rank")), safe_int(row.get("winner_rank_points")),
                row.get("loser_name"), safe_int(row.get("loser_rank")), safe_int(row.get("loser_rank_points")),
                score, safe_int(row.get("best_of")), safe_int(row.get("minutes")),
                safe_int(row.get("w_ace")), safe_int(row.get("w_df")),
                safe_int(row.get("w_1stIn")), safe_int(row.get("w_1stWon")),
                safe_int(row.get("w_2ndWon")), safe_int(row.get("w_bpSaved")), safe_int(row.get("w_bpFaced")),
                safe_int(row.get("l_ace")), safe_int(row.get("l_df")),
                safe_int(row.get("l_1stIn")), safe_int(row.get("l_1stWon")),
                safe_int(row.get("l_2ndWon")), safe_int(row.get("l_bpSaved")), safe_int(row.get("l_bpFaced")),
                sets_w, sets_l, 1 if sets_l == 0 else 0,
                rus_w[0] if rus_w else None,
                rus_l[0] if rus_l else None,
            ))
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            log.debug(f"Jeff insert error: {e}")

    conn.commit()
    return True, inserted


_index_child_pages_cache = None

def get_tennis_data_child_pages():
    global _index_child_pages_cache
    if _index_child_pages_cache is not None:
        return _index_child_pages_cache

    html = fetch_text(TENNIS_DATA_INDEX, timeout=30)
    if not html:
        log.warning("Не удалось загрузить tennis-data index page")
        _index_child_pages_cache = []
        return _index_child_pages_cache

    soup = BeautifulSoup(html, "html.parser")
    pages = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(TENNIS_DATA_INDEX, href)
        if full.lower().endswith(".php"):
            pages.append(full)

    seen = set()
    deduped = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    log.info(f"tennis-data: найдено дочерних страниц {len(deduped)}")
    _index_child_pages_cache = deduped
    return deduped


def get_candidate_csv_links_from_page(page_url: str, year: int, tour: str):
    html = fetch_text(page_url, timeout=30)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    out = []

    if tour == "ATP":
        year_patterns = [f"/{year}/"]
    else:
        year_patterns = [f"/{year}w/"]

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(page_url, href)
        full_lower = full.lower()
        if ".csv" not in full_lower:
            continue
        if any(p in full_lower for p in year_patterns):
            out.append(full)

    return out


def get_tennis_data_csv_links(tour: str, year: int):
    pages = get_tennis_data_child_pages()
    links = []

    for page in pages:
        try:
            links.extend(get_candidate_csv_links_from_page(page, year, tour))
        except Exception as e:
            log.debug(f"Ошибка обхода страницы {page}: {e}")

    seen = set()
    deduped = []
    for link in links:
        if link not in seen:
            seen.add(link)
            deduped.append(link)

    return sorted(deduped)


def build_score_from_tennis_data_row(row: dict):
    direct = pick_ci(row, "score")
    if direct:
        s = str(direct).strip()
        if s and s.upper() not in {"RET", "W/O", "DEF"}:
            return s

    comment = str(pick_ci(row, "Comment") or "").strip().lower()
    if comment and comment not in {"completed", "finished"}:
        return None

    parts = []
    for i in range(1, 6):
        w = pick_ci(row, f"W{i}")
        l = pick_ci(row, f"L{i}")
        if w is None or l is None:
            continue
        w = str(w).strip()
        l = str(l).strip()
        if not w or not l:
            continue
        if w in {"", "0"} and l in {"", "0"}:
            continue
        parts.append(f"{w}-{l}")

    if not parts:
        return None
    return " ".join(parts)


def insert_tennis_data_row(conn: sqlite3.Connection, tour: str, year: int, row: dict):
    winner = pick_ci(row, "Winner")
    loser = pick_ci(row, "Loser")
    if not winner or not loser:
        return 0

    score = build_score_from_tennis_data_row(row)
    if not score:
        return 0

    sets_w, sets_l = parse_score(score)
    if sets_w is None:
        return 0

    td = normalize_date(pick_ci(row, "Date"))
    tourney_name = pick_ci(row, "Tournament", "Location")
    surface = pick_ci(row, "Surface")
    tourney_level = pick_ci(row, "Series", "Tier", "Tournament")
    round_ = pick_ci(row, "Round")
    best_of = safe_int(pick_ci(row, "Best of", "Best_of"))
    minutes = safe_int(pick_ci(row, "Minutes"))

    winner_rank = safe_int(pick_ci(row, "WRank", "winner_rank"))
    loser_rank = safe_int(pick_ci(row, "LRank", "loser_rank"))
    winner_rank_pts = safe_int(pick_ci(row, "WPts", "winner_rank_points"))
    loser_rank_pts = safe_int(pick_ci(row, "LPts", "loser_rank_points"))

    try:
        rus_w = conn.execute(
            "SELECT rus_name FROM tennis_player_mapping WHERE LOWER(eng_name) = LOWER(?) LIMIT 1",
            (winner,)
        ).fetchone()
        rus_l = conn.execute(
            "SELECT rus_name FROM tennis_player_mapping WHERE LOWER(eng_name) = LOWER(?) LIMIT 1",
            (loser,)
        ).fetchone()

        conn.execute("""
            INSERT OR IGNORE INTO backtest_tennis_players
            (tour, year, tourney_name, surface, tourney_level, tourney_date, round,
             winner_name, winner_rank, winner_rank_pts,
             loser_name, loser_rank, loser_rank_pts,
             score, best_of, minutes,
             w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
             l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
             sets_winner, sets_loser, straight_sets,
             winner_rus_name, loser_rus_name)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            tour, year,
            tourney_name, surface, tourney_level, td, round_,
            winner, winner_rank, winner_rank_pts,
            loser, loser_rank, loser_rank_pts,
            score, best_of, minutes,
            safe_int(pick_ci(row, "w_ace")), safe_int(pick_ci(row, "w_df")),
            safe_int(pick_ci(row, "w_1stin")), safe_int(pick_ci(row, "w_1stwon")),
            safe_int(pick_ci(row, "w_2ndwon")), safe_int(pick_ci(row, "w_bpsaved")), safe_int(pick_ci(row, "w_bpfaced")),
            safe_int(pick_ci(row, "l_ace")), safe_int(pick_ci(row, "l_df")),
            safe_int(pick_ci(row, "l_1stin")), safe_int(pick_ci(row, "l_1stwon")),
            safe_int(pick_ci(row, "l_2ndwon")), safe_int(pick_ci(row, "l_bpsaved")), safe_int(pick_ci(row, "l_bpfaced")),
            sets_w, sets_l, 1 if sets_l == 0 else 0,
            rus_w[0] if rus_w else None,
            rus_l[0] if rus_l else None,
        ))
        return conn.execute("SELECT changes()").fetchone()[0]
    except Exception as e:
        log.debug(f"tennis-data insert error: {e}")
        return 0


def load_tennis_data_year(tour: str, year: int, conn: sqlite3.Connection):
    links = get_tennis_data_csv_links(tour, year)
    if not links:
        log.warning(f"tennis-data: не найдены CSV links для {tour} {year}")
        return 0

    inserted = 0
    for url in links:
        try:
            r = session.get(url, timeout=30, allow_redirects=True)
            if r.status_code != 200:
                log.warning(f"tennis-data {tour} {year}: {url} -> HTTP {r.status_code}")
                continue

            reader = csv.DictReader(io.StringIO(r.text))
            file_inserted = 0
            for row in reader:
                file_inserted += insert_tennis_data_row(conn, tour, year, row)

            conn.commit()
            inserted += file_inserted
            log.info(f"tennis-data {tour} {year}: {url} -> +{file_inserted}")
            time.sleep(0.1)
        except Exception as e:
            log.warning(f"tennis-data {tour} {year}: ошибка {url}: {e}")

    return inserted


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    total = 0
    for tour in ["ATP", "WTA"]:
        for year in YEARS:
            found_jeff, n = load_jeff_csv(tour, year, conn)
            if found_jeff:
                log.info(f"Jeff {tour} {year}: +{n} матчей")
                total += n
                time.sleep(0.1)
                continue

            if year in FALLBACK_YEARS:
                log.info(f"Jeff {tour} {year}: нет файла, пробую tennis-data fallback")
                n = load_tennis_data_year(tour, year, conn)
                log.info(f"Fallback {tour} {year}: +{n} матчей")
                total += n
                time.sleep(0.1)
            else:
                log.info(f"{tour} {year}: источник отсутствует, пропускаю")

    log.info(f"Готово! Всего: +{total} матчей")
    conn.close()


if __name__ == "__main__":
    main()
