#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sqlite3, argparse
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

DB_PATH = os.environ.get("BETAGENT_DB", "betagent.db")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUE_MAP = {
    "англия. премьер-лига": "epl",
    "германия. бундеслига": "bundesliga",
    "испания. ла лига": "laliga",
    "франция. лига 1": "ligue1",
    "италия. серия а": "seriea",
    "россия. премьер-лига": "rpl",
}

# Стоп-слова — если название лиги содержит их, сбрасываем текущую лигу
STOP_LEAGUES = [
    "нидерланд", "турци", "аргентин", "бразил", "португал", "шотланд",
    "бельги", "болгар", "хорват", "серби", "словак", "словен", "румын",
    "польш", "венгр", "чех", "австри", "швейцар", "швец", "финлянд",
    "дания", "норвег", "греци", "кипр", "израил", "япони", "корей",
    "китай", "таиланд", "индонез", "казахст", "узбекист", "беларус",
    "украин", "латви", "литв", "эстони", "люксембург", "македон",
    "албани", "черногор", "босни", "мексик", "колумби", "венесуэл",
    "перу", "чили", "уругвай", "парагвай", "боливи", "эквадор",
    "австрали", "гана", "тунис", "египет", "катар", "оаэ", "бахрейн",
    "жен", "молодёж", "u19", "u21", "резерв", "ii", " б ", "фарм",
    "лига наций", "лига конференций", "лига европы",
]

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def detect_league(text):
    t = text.lower().strip()
    # Сначала проверяем стоп-слова
    for stop in STOP_LEAGUES:
        if stop in t:
            return "STOP"
    for key, val in LEAGUE_MAP.items():
        if key in t:
            return val
    return None

def parse_results(html, date_str):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    current_league = None

    for el in soup.find_all(True):
        # Детектируем лигу по заголовкам
        if el.name in ("h2", "h3", "h4"):
            text = el.get_text(strip=True)
            league = detect_league(text)
            if league == "STOP":
                current_league = None
            elif league:
                current_league = league

        # Детектируем лигу по div/span с классами title/header
        if el.name in ("div", "span", "a"):
            cls = " ".join(el.get("class", []))
            if any(x in cls for x in ["title", "header", "caption", "group-title", "champ", "tournament"]):
                text = el.get_text(strip=True)
                league = detect_league(text)
                if league == "STOP":
                    current_league = None
                elif league:
                    current_league = league

        # Матч — строка с data-match-id
        if el.name == "tr" and el.get("data-match-id"):
            if not current_league:
                continue

            tds = el.find_all("td")
            if len(tds) < 2:
                continue

            # Хозяева и гости
            owner_td = el.find("td", class_="owner-td")
            guests_td = el.find("td", class_="guests-td")
            if not owner_td or not guests_td:
                continue

            home_a = owner_td.find("a", class_="player")
            away_a = guests_td.find("a", class_="player")
            if not home_a or not away_a:
                continue

            home_team = home_a.get_text(strip=True)
            away_team = away_a.get_text(strip=True)

            # Фильтр мусора
            skip_words = ["тайм", "период", "half", "quarter", " б", "-б", "ii", "резерв"]
            if any(w in home_team.lower() or w in away_team.lower() for w in skip_words):
                continue

            # Счёт — только из score-td
            score_td = el.find("td", class_="score-td")
            if not score_td:
                continue
            score_text = score_td.get_text(strip=True).split("(")[0].strip()

            m = re.match(r"(\d+):(\d+)", score_text or "")
            if not m:
                continue

            home_score = int(m.group(1))
            away_score = int(m.group(2))

            results.append({
                "league": current_league,
                "match_date": date_str,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
            })
            print(f"  [{current_league}] {home_team} {home_score}:{away_score} {away_team}")

    return results

def save_results(results):
    conn = get_conn()
    saved = 0
    for r in results:
        existing = conn.execute("""
            SELECT id FROM results_raw
            WHERE home_team=? AND away_team=? AND match_date=? AND is_finished=1
        """, (r["home_team"], r["away_team"], r["match_date"])).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO results_raw
            (league, match_date, home_team, away_team, home_score, away_score, is_finished, source, updated_at)
            VALUES (?,?,?,?,?,?,1,?,datetime('now'))
        """, (r["league"], r["match_date"], r["home_team"], r["away_team"],
              r["home_score"], r["away_score"], f"sportsru_football/{r['match_date']}"))
        saved += 1
    conn.commit()
    conn.close()
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()

    dates = [args.date] if args.date else [
        (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)
    ]

    total = 0
    for date_str in dates:
        url = f"https://www.sports.ru/football/match/{date_str}/"
        print(f"\nПарсим {date_str}...")
        try:
            html = fetch_html(url)
            results = parse_results(html, date_str)
            saved = save_results(results)
            print(f"  Найдено: {len(results)} | Сохранено: {saved}")
            total += saved
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")

    print(f"\n✅ Итого сохранено: {total}")

if __name__ == "__main__":
    main()
