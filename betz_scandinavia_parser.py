#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер исторических данных скандинавских футбольных лиг с betz.su
Лиги: Швеция Allsvenskan, Норвегия Eliteserien, Дания Superliga,
      Финляндия Veikkausliiga, MLS (США)

Запуск:
  python3 betz_scandinavia_parser.py --date-from 2021-04-01 --date-to 2021-11-30
  python3 betz_scandinavia_parser.py --date-from 2022-04-01 --date-to 2022-11-30
  python3 betz_scandinavia_parser.py --leagues sweden norway --date-from 2021-04-01 --date-to 2024-11-30
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
RESULTS_URL = "https://betz.su/res/result.php"
SPORT_NAME = "Футбол"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://betz.su/",
}

# Лиги для поиска (lowercase подстроки названий на betz.su)
LEAGUE_GROUPS = {
    "sweden":  ["швеция. алл", "швеция. allsvenskan", "швеция. высший"],
    "norway":  ["норвегия. элите", "норвегия. eliteserien", "норвегия. высший"],
    "denmark": ["дания. супер", "дания. superliga", "дания. высший"],
    "finland": ["финляндия. вейккаус", "финляндия. veikkausliiga", "финляндия. высший"],
    "mls":     ["сша. mls", "major league soccer", "сша. мажор"],
}

# Нормализованные названия для БД
LEAGUE_NAMES = {
    "sweden":  "Швеция. Алссвенскан",
    "norway":  "Норвегия. Элитесериен",
    "denmark": "Дания. Суперлига",
    "finland": "Финляндия. Вейккаусліга",
    "mls":     "США. MLS",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT,
    match_date TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    odds_home REAL,
    odds_draw REAL,
    odds_away REAL,
    odds_btts_yes REAL,
    odds_btts_no REAL,
    odds_over_2_5 REAL,
    odds_under_2_5 REAL,
    odds_over_1_5 REAL,
    odds_under_1_5 REAL,
    source_url TEXT,
    created_at TEXT,
    UNIQUE(match_date, home_team, away_team)
)
"""

def fetch(url: str, session: requests.Session, delay: float = 0.5) -> str:
    time.sleep(delay)
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                log.warning(f"Ошибка {url}: {e}")
                return ""
    return ""

def parse_score(text: str):
    m = re.search(r"(\d+):(\d+)", text or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

def get_odd(soup, selector: str) -> Optional[float]:
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
    except Exception:
        return None

def detect_league_group(league_str: str) -> Optional[str]:
    """Определить группу лиги по названию."""
    ls = league_str.lower().strip()
    for group, keywords in LEAGUE_GROUPS.items():
        for kw in keywords:
            if kw in ls:
                return group
    return None

def fetch_match_details(match_url: str, session: requests.Session) -> dict:
    """Получить детали матча — BTTS и тоталы."""
    result = {
        "odds_btts_yes": None, "odds_btts_no": None,
        "odds_over_2_5": None, "odds_under_2_5": None,
        "odds_over_1_5": None, "odds_under_1_5": None,
    }
    html = fetch(match_url, session, delay=0.3)
    if not html:
        return result
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True).lower()

    # Ищем BTTS (обе забьют)
    for line in soup.find_all(string=re.compile(r"обе.*забь|oba.*zab|both.*score", re.I)):
        parent = line.parent
        if parent:
            odds_els = parent.find_all(class_=re.compile(r"p1|p2"))
            if len(odds_els) >= 2:
                try:
                    result["odds_btts_yes"] = float(odds_els[0].get_text(strip=True).replace(",", "."))
                    result["odds_btts_no"] = float(odds_els[1].get_text(strip=True).replace(",", "."))
                except Exception:
                    pass

    # Ищем тоталы через span с классами
    for el in soup.find_all("span", class_=re.compile(r"p1|p2")):
        parent_text = el.parent.get_text(" ", strip=True).lower() if el.parent else ""
        if "тотал больше" in parent_text or "total over" in parent_text:
            try:
                val = float(el.get_text(strip=True).replace(",", "."))
                if "2.5" in parent_text:
                    if "больше" in parent_text or "over" in parent_text:
                        result["odds_over_2_5"] = val
                    elif "меньше" in parent_text or "under" in parent_text:
                        result["odds_under_2_5"] = val
                elif "1.5" in parent_text:
                    if "больше" in parent_text or "over" in parent_text:
                        result["odds_over_1_5"] = val
                    elif "меньше" in parent_text or "under" in parent_text:
                        result["odds_under_1_5"] = val
            except Exception:
                pass

    return result

def parse_results_page(html: str, target_groups: set) -> list[dict]:
    """Парсим страницу результатов betz.su."""
    soup = BeautifulSoup(html, "html.parser")
    sport_line = soup.select_one("ul.sport_line")
    if not sport_line:
        return []

    matches = []
    current_league = None
    current_league_group = None
    current_date = None

    for li in sport_line.find_all("li", recursive=False):
        classes = set(li.get("class", []))

        # Дата
        if "sport_info" in classes:
            txt = li.get_text(" ", strip=True)
            if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", txt):
                current_date = txt
            continue

        # Лига
        if "sport_info_2" in classes:
            current_league = li.get_text(" ", strip=True).strip()
            current_league_group = detect_league_group(current_league)
            continue

        # Матч
        if li.get("itemscope") is None:
            continue

        if not current_league_group or current_league_group not in target_groups:
            continue

        # Команды
        ha = li.select_one("span.sport_ha")
        if not ha:
            continue
        teams_text = ha.get_text(" ", strip=True)
        if " - " not in teams_text:
            continue
        home_team, away_team = [x.strip() for x in teams_text.split(" - ", 1)]

        # Счёт
        res_el = li.select_one("span.sport_res")
        score_text = res_el.get_text(strip=True) if res_el else ""
        home_score, away_score = parse_score(score_text)

        # Дата матча
        match_date = None
        if current_date:
            try:
                match_date = datetime.strptime(current_date, "%d.%m.%Y").strftime("%Y-%m-%d")
            except Exception:
                pass

        if not match_date:
            continue

        # Коэффициенты 1X2
        odds_home = None
        odds_draw = None
        odds_away = None
        try:
            p1 = li.select_one("span.p1")
            xx = li.select_one("span.xx")
            p2 = li.select_one("span.p2")
            if p1:
                odds_home = float(p1.get_text(strip=True).replace(",", "."))
            if xx:
                odds_draw = float(xx.get_text(strip=True).replace(",", "."))
            if p2:
                odds_away = float(p2.get_text(strip=True).replace(",", "."))
        except Exception:
            pass

        # Ссылка на матч
        link_el = li.select_one("a[href]")
        match_url = None
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("/"):
                match_url = f"https://betz.su{href}"
            elif href.startswith("http"):
                match_url = href

        matches.append({
            "league_group": current_league_group,
            "league_raw": current_league,
            "match_date": match_date,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "odds_home": odds_home,
            "odds_draw": odds_draw,
            "odds_away": odds_away,
            "match_url": match_url,
        })

    return matches

def save_matches(conn: sqlite3.Connection, matches: list[dict]) -> int:
    saved = 0
    cur = conn.cursor()
    for m in matches:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO backtest_matches
                    (league, match_date, home_team, away_team,
                     home_score, away_score,
                     odds_home, odds_draw, odds_away,
                     odds_btts_yes, odds_btts_no,
                     odds_over_2_5, odds_under_2_5,
                     odds_over_1_5, odds_under_1_5,
                     source_url, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                m["league"], m["match_date"], m["home_team"], m["away_team"],
                m["home_score"], m["away_score"],
                m["odds_home"], m["odds_draw"], m["odds_away"],
                m.get("odds_btts_yes"), m.get("odds_btts_no"),
                m.get("odds_over_2_5"), m.get("odds_under_2_5"),
                m.get("odds_over_1_5"), m.get("odds_under_1_5"),
                m.get("match_url"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
            if cur.rowcount > 0:
                saved += 1
        except Exception as e:
            log.debug(f"Skip {m['home_team']} vs {m['away_team']}: {e}")
    conn.commit()
    return saved

def daterange(date_from: str, date_to: str):
    """Генератор дат."""
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")
    cur = start
    while cur <= end:
        yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)

def main():
    parser = argparse.ArgumentParser(description="Парсер скандинавских лиг с betz.su")
    parser.add_argument("--date-from", default="2021-04-01", help="Начало периода YYYY-MM-DD")
    parser.add_argument("--date-to",   default="2021-11-30", help="Конец периода YYYY-MM-DD")
    parser.add_argument("--leagues", nargs="+",
                        choices=["sweden", "norway", "denmark", "finland", "mls", "all"],
                        default=["all"], help="Какие лиги качать")
    parser.add_argument("--no-details", action="store_true",
                        help="Не заходить на страницы матчей (только 1X2)")
    parser.add_argument("--delay", type=float, default=0.5, help="Задержка между запросами")
    parser.add_argument("--db", default=DB_PATH, help="Путь к БД")
    args = parser.parse_args()

    # Определяем целевые группы
    if "all" in args.leagues:
        target_groups = set(LEAGUE_GROUPS.keys())
    else:
        target_groups = set(args.leagues)

    log.info(f"Лиги: {target_groups}")
    log.info(f"Период: {args.date_from} — {args.date_to}")

    conn = sqlite3.connect(args.db)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()

    session = requests.Session()
    session.headers.update(HEADERS)

    total_saved = 0
    dates = list(daterange(args.date_from, args.date_to))
    log.info(f"Дней для обхода: {len(dates)}")

    for i, date_str in enumerate(dates):
        # Форматируем дату для betz.su: DD.MM.YYYY
        date_betz = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

        params = {
            "mode": "started",
            "date": date_betz,
            "sport": SPORT_NAME,
        }
        url = f"https://betz.su/line/?{urlencode(params)}"

        html = fetch(url, session, delay=args.delay)
        if not html:
            continue

        matches = parse_results_page(html, target_groups)

        if not matches:
            if i % 30 == 0:
                log.info(f"{date_str}: нет матчей нужных лиг")
            continue

        # Нормализуем название лиги
        for m in matches:
            m["league"] = LEAGUE_NAMES.get(m["league_group"], m["league_raw"])

        # Загружаем детали (BTTS, тоталы) если не отключено
        if not args.no_details:
            for m in matches:
                if m.get("match_url"):
                    details = fetch_match_details(m["match_url"], session)
                    m.update(details)

        saved = save_matches(conn, matches)
        total_saved += saved

        if matches:
            log.info(f"{date_str}: найдено {len(matches)}, сохранено {saved}")

    conn.close()
    log.info(f"Готово! Всего сохранено: {total_saved} матчей")

    # Итоговая статистика
    conn = sqlite3.connect(args.db)
    rows = conn.execute("""
        SELECT league, COUNT(*) as n,
               MIN(match_date) as from_d,
               MAX(match_date) as to_d
        FROM backtest_matches
        WHERE league LIKE '%Швеци%'
           OR league LIKE '%Норвег%'
           OR league LIKE '%Дани%'
           OR league LIKE '%Финл%'
           OR league LIKE '%MLS%'
        GROUP BY league ORDER BY n DESC
    """).fetchall()
    conn.close()

    print("\n=== ИТОГ ===")
    for r in rows:
        print(f"  {r[0]}: {r[1]} матчей ({r[2]} — {r[3]})")

if __name__ == "__main__":
    main()
