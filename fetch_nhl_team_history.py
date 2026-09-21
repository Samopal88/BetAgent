#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_nhl_team_history.py

Загружает историю матчей каждой команды НХЛ
с персональных страниц TheSports (identity pages).

Структура страницы такая же как РПЛ:
<tr>
  <td class="tdcol-25">15 March 2026 - 17h00 Round N</td>
  <td>Boston Bruins (4)</td>
  <td class="tdcol-15 td-center">3 - 1</td>
  <td>Ottawa Senators (13)</td>
</tr>

Пишет в results_raw с league='nhl' (дополняет существующие данные).

Запуск:
  python fetch_nhl_team_history.py
  python fetch_nhl_team_history.py --limit 5   (тест на 5 командах)
  python fetch_nhl_team_history.py --matches 20
"""

import os, re, time, sqlite3, argparse
import requests, urllib3
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

urllib3.disable_warnings()

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BASE = "https://www.the-sports.org/"
LEAGUE_KEY = "nhl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

# Slugs команд НХЛ — правильные URLs с TheSports
TEAM_SLUGS = {
    "Анахайм Дакс":          "ice-hockey-anaheim-ducks-results-identity-equ184.html",
    "Бостон Брюинз":         "ice-hockey-boston-bruins-results-identity-equ183.html",
    "Баффало Сейбрз":        "ice-hockey-buffalo-sabres-results-identity-equ185.html",
    "Калгари Флэймз":        "ice-hockey-calgary-flames-results-identity-equ181.html",
    "Каролина Харрикейнз":   "ice-hockey-carolina-hurricanes-results-identity-equ200.html",
    "Чикаго Блэкхокс":       "ice-hockey-chicago-blackhawks-results-identity-equ195.html",
    "Колорадо Эвеланш":      "ice-hockey-colorado-avalanche-results-identity-equ180.html",
    "Коламбус Блю Джекетс":  "ice-hockey-columbus-blue-jackets-results-identity-equ193.html",
    "Даллас Старз":          "ice-hockey-dallas-stars-results-identity-equ204.html",
    "Детройт Ред Уингз":     "ice-hockey-detroit-red-wings-results-identity-equ199.html",
    "Эдмонтон Ойлерз":       "ice-hockey-edmonton-oilers-results-identity-equ182.html",
    "Флорида Пантерз":       "ice-hockey-florida-panthers-results-identity-equ190.html",
    "Лос-Анджелес Кингз":    "ice-hockey-los-angeles-kings-results-identity-equ196.html",
    "Миннесота Уайлд":       "ice-hockey-minnesota-wild-results-identity-equ207.html",
    "Монреаль Канадиенс":    "ice-hockey-montreal-canadiens-results-identity-equ188.html",
    "Нэшвилл Предаторз":     "ice-hockey-nashville-predators-results-identity-equ205.html",
    "Нью-Джерси Девилз":     "ice-hockey-new-jersey-devils-results-identity-equ206.html",
    "Нью-Йорк Айлендерс":    "ice-hockey-new-york-islanders-results-identity-equ203.html",
    "Нью-Йорк Рейнджерс":    "ice-hockey-new-york-rangers-results-identity-equ201.html",
    "Оттава Сенаторз":       "ice-hockey-ottawa-senators-results-identity-equ178.html",
    "Филадельфия Флайерз":   "ice-hockey-philadelphia-flyers-results-identity-equ189.html",
    "Питтсбург Пингвинз":    "ice-hockey-pittsburgh-penguins-results-identity-equ179.html",
    "Сан-Хосе Шаркс":        "ice-hockey-san-jose-sharks-results-identity-equ198.html",
    "Сиэтл Кракен":          "ice-hockey-seattle-kraken-results-identity-equ93588.html",
    "Сент-Луис Блюз":        "ice-hockey-st-louis-blues-results-identity-equ192.html",
    "Тампа-Бэй Лайтнинг":   "ice-hockey-tampa-bay-lightning-results-identity-equ202.html",
    "Торонто Мэйпл Лифс":   "ice-hockey-toronto-maple-leafs-results-identity-equ177.html",
    "Юта Хоккей Клаб":       "ice-hockey-utah-mammoth-results-identity-equ100958.html",
    "Ванкувер Кэнакс":       "ice-hockey-vancouver-canucks-results-identity-equ194.html",
    "Вегас Голден Найтс":    "ice-hockey-vegas-golden-knights-results-identity-equ68698.html",
    "Вашингтон Кэпиталз":    "ice-hockey-washington-capitals-results-identity-equ191.html",
    "Виннипег Джетс":        "ice-hockey-winnipeg-jets-results-identity-equ26901.html",
}

# Маппинг английских названий TheSports → русские в БД
TEAM_MAP = {
    "Anaheim Ducks":         "Анахайм Дакс",
    "Boston Bruins":         "Бостон Брюинз",
    "Buffalo Sabres":        "Баффало Сейбрз",
    "Calgary Flames":        "Калгари Флэймз",
    "Carolina Hurricanes":   "Каролина Харрикейнз",
    "Chicago Blackhawks":    "Чикаго Блэкхокс",
    "Colorado Avalanche":    "Колорадо Эвеланш",
    "Columbus Blue Jackets": "Коламбус Блю Джекетс",
    "Dallas Stars":          "Даллас Старз",
    "Detroit Red Wings":     "Детройт Ред Уингз",
    "Edmonton Oilers":       "Эдмонтон Ойлерз",
    "Florida Panthers":      "Флорида Пантерз",
    "Los Angeles Kings":     "Лос-Анджелес Кингз",
    "Minnesota Wild":        "Миннесота Уайлд",
    "Montreal Canadiens":    "Монреаль Канадиенс",
    "Nashville Predators":   "Нэшвилл Предаторз",
    "New Jersey Devils":     "Нью-Джерси Девилз",
    "New York Islanders":    "Нью-Йорк Айлендерс",
    "New York Rangers":      "Нью-Йорк Рейнджерс",
    "Ottawa Senators":       "Оттава Сенаторз",
    "Philadelphia Flyers":   "Филадельфия Флайерз",
    "Pittsburgh Penguins":   "Питтсбург Пингвинз",
    "San Jose Sharks":       "Сан-Хосе Шаркс",
    "Seattle Kraken":        "Сиэтл Кракен",
    "St. Louis Blues":       "Сент-Луис Блюз",
    "Tampa Bay Lightning":   "Тампа-Бэй Лайтнинг",
    "Toronto Maple Leafs":   "Торонто Мэйпл Лифс",
    "Vancouver Canucks":     "Ванкувер Кэнакс",
    "Vegas Golden Knights":  "Вегас Голден Найтс",
    "Washington Capitals":   "Вашингтон Кэпиталз",
    "Winnipeg Jets":         "Виннипег Джетс",
    "Utah Mammoth":          "Юта Хоккей Клаб",
    "Utah Hockey Club":      "Юта Хоккей Клаб",
    "St. Louis Blues":       "Сент-Луис Блюз",
    "St Louis Blues":        "Сент-Луис Блюз",
}

MONTHS = {
    "January":"01","February":"02","March":"03","April":"04",
    "May":"05","June":"06","July":"07","August":"08",
    "September":"09","October":"10","November":"11","December":"12",
}

def norm_team(name: str) -> str:
    name = re.sub(r"\s*\(\d+\)\s*$", "", (name or "").strip())
    return TEAM_MAP.get(name, name)

def parse_date(text: str):
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip())
    if not m:
        return None, None
    d, mon, y = m.groups()
    mm = MONTHS.get(mon)
    if not mm:
        return None, None
    date_str = f"{y}-{mm}-{int(d):02d}"
    tm = re.search(r"(\d{1,2})h(\d{2})", text)
    time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "00:00"
    return date_str, time_str

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_page(slug: str):
    url = BASE + slug
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        if r.status_code == 200 and len(r.text) > 5000:
            return r.text
        print(f"    ⚠️  status={r.status_code}")
    except Exception as e:
        print(f"    ❌ {e}")
    return None

def parse_team_results(html: str, n: int = 15):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for tr in soup.find_all("tr"):
        cols = tr.find_all("td")
        if len(cols) < 4:
            continue

        date_txt = cols[0].get_text(" ", strip=True)
        date, time_str = parse_date(date_txt)
        if not date:
            continue

        score_txt = cols[2].get_text(" ", strip=True)
        if "cancel" in score_txt.lower() or "postponed" in score_txt.lower():
            continue
        sm = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", score_txt)
        if not sm:
            continue

        home_raw = re.sub(r"\s*\(\d+\)\s*$", "", cols[1].get_text(" ", strip=True)).strip()
        away_raw = re.sub(r"\s*\(\d+\)\s*$", "", cols[3].get_text(" ", strip=True)).strip()

        home = norm_team(home_raw)
        away = norm_team(away_raw)

        if not home or not away or home == away:
            continue

        results.append({
            "match_date": date,
            "kickoff": f"{date} {time_str}",
            "home_team": home,
            "away_team": away,
            "home_score": int(sm.group(1)),
            "away_score": int(sm.group(2)),
        })

        if len(results) >= n:
            break

    return results

def save_results(conn, results: list) -> int:
    if not results:
        return 0
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    for r in results:
        exists = cur.execute("""
            SELECT id FROM results_raw
            WHERE league=? AND match_date=? AND home_team=? AND away_team=?
        """, (LEAGUE_KEY, r["match_date"], r["home_team"], r["away_team"])).fetchone()
        if not exists:
            cur.execute("""
                INSERT INTO results_raw (
                    league, match_date, kickoff, home_team, away_team,
                    home_score, away_score, is_finished, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'TheSports NHL team page', ?)
            """, (
                LEAGUE_KEY, r["match_date"], r["kickoff"],
                r["home_team"], r["away_team"],
                r["home_score"], r["away_score"], now
            ))
            saved += 1
    conn.commit()
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",   type=int, default=0,  help="Сколько команд (0=все)")
    ap.add_argument("--matches", type=int, default=15, help="Матчей на команду")
    args = ap.parse_args()

    conn = get_conn()
    teams = list(TEAM_SLUGS.items())
    if args.limit:
        teams = teams[:args.limit]

    print(f"Загружаем историю матчей для {len(teams)} команд НХЛ...\n")

    total_saved = 0
    for team_name, slug in teams:
        print(f"  {team_name}...")
        html = fetch_page(slug)
        if not html:
            continue
        results = parse_team_results(html, n=args.matches)
        saved = save_results(conn, results)
        total_saved += saved
        status = f"{len(results)} матчей, {saved} новых"
        if results:
            dates = [r["match_date"] for r in results]
            status += f" | {min(dates)} — {max(dates)}"
        print(f"    → {status}")
        time.sleep(0.8)

    total = conn.execute(
        "SELECT COUNT(*) as c FROM results_raw WHERE league=?", (LEAGUE_KEY,)
    ).fetchone()["c"]
    print(f"\n✅ Всего в БД (league='{LEAGUE_KEY}'): {total} матчей")
    print("\nТеперь запускай:")
    print("  python enricher_from_the_sports_nhl.py --limit 50")
    print("  python sync_match_facts_v3.py")
    conn.close()

if __name__ == "__main__":
    main()
