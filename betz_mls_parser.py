#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер исторических данных MLS с betz.su
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
RESULTS_URL = "https://betz.su/res/result.php"
SPORT_NAME = "Футбол"
LEAGUE_FILTER = ["футбол. сша. mls. регулярный сезон"]

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

def parse_score(text: str):
    m = re.search(r"(\d+):(\d+)", text or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

def get_odd_from_soup(soup, selector: str) -> Optional[float]:
    el = soup.select_one(selector)
    if not el:
        return None
    b = el.select_one("b")
    text = b.get_text(strip=True) if b else el.get_text(strip=True)
    if " - " in text:
        text = text.split(" - ")[-1]
    try:
        val = float(text.strip().replace(",", "."))
        return val if val > 1.0 else None
    except:
        return None

def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    result = {
        "odds_home": get_odd_from_soup(soup, "span.p1"),
        "odds_draw": get_odd_from_soup(soup, "span.xx"),
        "odds_away": get_odd_from_soup(soup, "span.p2"),
        "odds_btts_yes": None,
        "odds_btts_no": None,
        "odds_over_1_5": None,
        "odds_under_1_5": None,
        "odds_over_2_5": None,
        "odds_under_2_5": None,
        "odds_over_3_5": None,
        "odds_under_3_5": None,
    }
    m = re.search(r"Обе забьют Да\s*[-–]\s*([\d.]+)", full_text)
    if m: result["odds_btts_yes"] = float(m.group(1))
    m = re.search(r"Обе забьют Нет\s*[-–]\s*([\d.]+)", full_text)
    if m: result["odds_btts_no"] = float(m.group(1))

    tm_el = soup.select_one("span.tm")
    tb_el = soup.select_one("span.tb")
    if tm_el:
        try:
            b = tm_el.select_one("b")
            val = float(b.get_text(strip=True)) if b else None
            lm = re.search(r"[(]([\.\d]+)[)]", tm_el.get_text(strip=True))
            if lm and val:
                line = lm.group(1)
                if line == "1.5": result["odds_under_1_5"] = val
                elif line == "2.5": result["odds_under_2_5"] = val
                elif line == "3.5": result["odds_under_3_5"] = val
        except: pass
    if tb_el:
        try:
            b = tb_el.select_one("b")
            val = float(b.get_text(strip=True)) if b else None
            lm = re.search(r"[(]([\.\d]+)[)]", tb_el.get_text(strip=True))
            if lm and val:
                line = lm.group(1)
                if line == "1.5": result["odds_over_1_5"] = val
                elif line == "2.5": result["odds_over_2_5"] = val
                elif line == "3.5": result["odds_over_3_5"] = val
        except: pass
    return result

def parse_day(html: str, date_str: str, session: requests.Session, delay: float) -> list:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    cc_divs = soup.find_all("div", id="cc")
    for league_div in cc_divs:
        league_name = league_div.get_text(strip=True)
        if not any(kw in league_name.lower() for kw in LEAGUE_FILTER):
            continue
        if "статистика" in league_name.lower():
            continue
        matches_div = league_div.find_next_sibling("div")
        if not matches_div:
            continue
        links = matches_div.find_all("a", href=re.compile(r"detail=\d+"))
        for link in links:
            teams_text = link.get_text(strip=True)
            if " - " not in teams_text:
                continue
            home, away = [x.strip() for x in teams_text.split(" - ", 1)]
            score_tag = link.find_next("u")
            score_text = score_tag.get_text(strip=True) if score_tag else ""
            hs, as_ = parse_score(score_text)
            try:
                year = int(date_str[:4])
                month = int(date_str[5:7])
                season = str(year) if month >= 3 else str(year - 1)
            except:
                season = "unknown"
            detail_url = f"https://betz.su{link['href']}"
            time.sleep(delay)
            detail_html = fetch(detail_url, session)
            odds = parse_detail(detail_html) if detail_html else {}
            row = {
                "league": "MLS",
                "league_name": "США. MLS",
                "season": season,
                "match_date": date_str,
                "home_team": home,
                "away_team": away,
                "home_score": hs,
                "away_score": as_,
                "result": ("H" if hs and as_ and hs > as_ else ("A" if hs and as_ and as_ > hs else "D")) if hs is not None and as_ is not None else None,
                **odds,
            }
            rows.append(row)
            log.info(f"  {home} {hs}:{as_} {away} | П1={odds.get('odds_home')} X={odds.get('odds_draw')} П2={odds.get('odds_away')} BTTS={odds.get('odds_btts_yes')}")
    return rows

def ensure_columns(conn):
    existing = [r[1] for r in conn.execute("PRAGMA table_info(backtest_matches)").fetchall()]
    for col in ["odds_btts_yes","odds_btts_no","odds_over_1_5","odds_under_1_5","odds_over_2_5","odds_under_2_5","odds_over_3_5","odds_under_3_5"]:
        if col not in existing:
            conn.execute(f"ALTER TABLE backtest_matches ADD COLUMN {col} REAL")
    conn.commit()

def save_to_results_raw(conn, rows: list) -> int:
    """Upsert MLS results into results_raw for settler consumption.

    Writes both the nominal match_date AND match_date+1 to handle late-night
    games (e.g. 23:30 kickoff) where the result appears the next calendar day
    on betz.su.
    """
    saved = 0
    for r in rows:
        if r.get("home_score") is None or r.get("away_score") is None:
            continue
        # Write result under both the scraped date and the previous day,
        # so settler LIKE 'YYYY-MM-DD%' finds it regardless of which date
        # the late-night match is stored under.
        try:
            dt = datetime.strptime(r["match_date"], "%Y-%m-%d")
            dates_to_write = [r["match_date"], (dt - timedelta(days=1)).strftime("%Y-%m-%d")]
        except Exception:
            dates_to_write = [r["match_date"]]

        for match_date in dates_to_write:
            existing = conn.execute("""
                SELECT id FROM results_raw
                WHERE home_team=? AND away_team=? AND match_date=? AND is_finished=1
            """, (r["home_team"], r["away_team"], match_date)).fetchone()
            if existing:
                continue
            conn.execute("""
                INSERT INTO results_raw
                    (league, match_date, home_team, away_team,
                     home_score, away_score, is_finished, source, updated_at)
                VALUES (?,?,?,?,?,?,1,?,datetime('now'))
            """, (
                "USA. MLS", match_date, r["home_team"], r["away_team"],
                r["home_score"], r["away_score"],
                f"betz_mls/{r['match_date']}",
            ))
            saved += 1
    conn.commit()
    return saved


def save_rows(conn, rows):
    inserted = updated = 0
    for r in rows:
        existing = conn.execute("""
            SELECT id FROM backtest_matches
            WHERE league=? AND season=? AND home_team=? AND away_team=? AND match_date=?
        """, ("MLS", r["season"], r["home_team"], r["away_team"], r["match_date"])).fetchone()
        if existing:
            conn.execute("""
                UPDATE backtest_matches SET home_score=?, away_score=?, result=?,
                odds_home=?, odds_draw=?, odds_away=?,
                odds_btts_yes=?, odds_btts_no=?,
                odds_over_1_5=?, odds_under_1_5=?,
                odds_over_2_5=?, odds_under_2_5=?,
                odds_over_3_5=?, odds_under_3_5=?
                WHERE id=?
            """, (r["home_score"], r["away_score"], r["result"],
                  r.get("odds_home"), r.get("odds_draw"), r.get("odds_away"),
                  r.get("odds_btts_yes"), r.get("odds_btts_no"),
                  r.get("odds_over_1_5"), r.get("odds_under_1_5"),
                  r.get("odds_over_2_5"), r.get("odds_under_2_5"),
                  r.get("odds_over_3_5"), r.get("odds_under_3_5"),
                  existing[0]))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO backtest_matches
                (league, league_name, season, match_date, home_team, away_team,
                 home_score, away_score, result, odds_home, odds_draw, odds_away,
                 odds_btts_yes, odds_btts_no,
                 odds_over_1_5, odds_under_1_5,
                 odds_over_2_5, odds_under_2_5,
                 odds_over_3_5, odds_under_3_5)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (r["league"], r["league_name"], r["season"], r["match_date"],
                  r["home_team"], r["away_team"], r["home_score"], r["away_score"],
                  r["result"], r.get("odds_home"), r.get("odds_draw"), r.get("odds_away"),
                  r.get("odds_btts_yes"), r.get("odds_btts_no"),
                  r.get("odds_over_1_5"), r.get("odds_under_1_5"),
                  r.get("odds_over_2_5"), r.get("odds_under_2_5"),
                  r.get("odds_over_3_5"), r.get("odds_under_3_5")))
            inserted += 1
    conn.commit()
    return inserted, updated

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-from", default="2021-03-01")
    ap.add_argument("--date-to", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--delay", type=float, default=0.5)
    # --days N: shortcut to fetch last N days into results_raw (for pipeline use)
    ap.add_argument("--days", type=int, default=None,
                    help="Fetch last N days and write to results_raw (for settlement pipeline)")
    args = ap.parse_args()

    if args.days is not None:
        args.date_to = datetime.now().strftime("%Y-%m-%d")
        args.date_from = (datetime.now() - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    session = requests.Session()
    session.headers.update(HEADERS)

    dt = datetime.strptime(args.date_from, "%Y-%m-%d")
    dt_end = datetime.strptime(args.date_to, "%Y-%m-%d")

    total_ins = total_upd = 0
    total_raw = 0
    while dt <= dt_end:
        date_str_req = dt.strftime("%d.%m.%Y")
        date_str_db = dt.strftime("%Y-%m-%d")
        url = f"{RESULTS_URL}?date={quote(date_str_req)}&sport={quote(SPORT_NAME)}"
        html = fetch(url, session)
        if html:
            rows = parse_day(html, date_str_db, session, args.delay)
            if rows:
                ins, upd = save_rows(conn, rows)
                total_ins += ins
                total_upd += upd
                # Always mirror into results_raw for settler
                raw_saved = save_to_results_raw(conn, rows)
                total_raw += raw_saved
                log.info(f"{date_str_req}: backtest +{ins}/~{upd}, results_raw +{raw_saved}")
        dt += timedelta(days=1)
        time.sleep(args.delay)

    conn.close()
    log.info(f"Готово! backtest: +{total_ins}/~{total_upd}, results_raw: +{total_raw}")

if __name__ == "__main__":
    main()
