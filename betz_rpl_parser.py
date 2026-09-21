#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер исторических данных РПЛ с betz.su
Заходит на страницу каждого матча и берёт 1X2, BTTS, тоталы.
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, quote
import requests
from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
RESULTS_URL = "https://betz.su/res/result.php"
SPORT_NAME = "Футбол"
LEAGUE_FILTER = ["россия. премьер-лига"]

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
    """Парсит детальную страницу матча."""
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
    
    # BTTS
    m = re.search(r"Обе забьют Да\s*[-–]\s*([\d.]+)", full_text)
    if m: result["odds_btts_yes"] = float(m.group(1))
    m = re.search(r"Обе забьют Нет\s*[-–]\s*([\d.]+)", full_text)
    if m: result["odds_btts_no"] = float(m.group(1))
    
    # Тоталы из основной линии (span.tm / span.tb)
    # Основная линия содержит один тотал — 1.5 или 2.5 в зависимости от матча
    tm_el = soup.select_one("span.tm")
    tb_el = soup.select_one("span.tb")
    if tm_el:
        try:
            b = tm_el.select_one("b")
            val = float(b.get_text(strip=True)) if b else None
            tm_text = tm_el.get_text(strip=True)
            import re as _re
            lm = _re.search(r"[(]([\.\d]+)[)]", tm_text)
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
            tb_text = tb_el.get_text(strip=True)
            import re as _re
            lm = _re.search(r"[(]([\.\d]+)[)]", tb_text)
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

        # Берём все ссылки на матчи
        links = matches_div.find_all("a", href=re.compile(r"detail=\d+"))
        scores_text = matches_div.get_text("\n", strip=True)
        
        for i, link in enumerate(links):
            teams_text = link.get_text(strip=True)
            if " - " not in teams_text:
                continue
            home, away = [x.strip() for x in teams_text.split(" - ", 1)]
            
            # Счёт берём из тега u после ссылки
            score_tag = link.find_next("u")
            score_text = score_tag.get_text(strip=True) if score_tag else ""
            hs, as_ = parse_score(score_text)
            
            # Дата
            match_date = date_str
            try:
                year = int(match_date[:4])
                month = int(match_date[5:7])
                season = str(year) if month >= 7 else str(year - 1)
            except:
                season = "unknown"
            
            # Заходим на детальную страницу
            detail_url = f"https://betz.su{link['href']}"
            time.sleep(delay)
            detail_html = fetch(detail_url, session)
            odds = parse_detail(detail_html) if detail_html else {}
            
            row = {
                "league": "RPL",
                "league_name": "Россия. Премьер-Лига",
                "season": season,
                "match_date": match_date,
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
    for col in ["odds_btts_yes", "odds_btts_no", "odds_over_1_5", "odds_under_1_5", "odds_over_2_5", "odds_under_2_5", "odds_over_3_5", "odds_under_3_5"]:
        if col not in existing:
            conn.execute(f"ALTER TABLE backtest_matches ADD COLUMN {col} REAL")
    conn.commit()

def save_rows(conn, rows):
    inserted = updated = 0
    for r in rows:
        existing = conn.execute("""
            SELECT id FROM backtest_matches
            WHERE league=? AND season=? AND home_team=? AND away_team=? AND match_date=?
        """, ("RPL", r["season"], r["home_team"], r["away_team"], r["match_date"])).fetchone()

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
    ap.add_argument("--date-from", default="2024-07-01")
    ap.add_argument("--date-to", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    session = requests.Session()
    session.headers.update(HEADERS)

    dt = datetime.strptime(args.date_from, "%Y-%m-%d")
    dt_end = datetime.strptime(args.date_to, "%Y-%m-%d")

    total_ins = total_upd = 0
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
                log.info(f"{date_str_req}: +{ins} новых, ~{upd} обновлено")
        
        dt += timedelta(days=1)
        time.sleep(args.delay)

    conn.close()
    log.info(f"Готово! Всего: +{total_ins} новых, ~{total_upd} обновлено")

if __name__ == "__main__":
    main()
