#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Парсер результатов скандинавских футбольных лиг с liveresult.ru -> results_raw."""
import os, re, sqlite3, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DB_PATH = os.environ.get("BETAGENT_DB", "betagent.db")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUES = {
    "dnk": "https://www.liveresult.ru/football/denmark/superliga/results/",
    "swe": "https://www.liveresult.ru/football/sweden/allsvenskan/results/",
    "fin": "https://www.liveresult.ru/football/finland/veikkausliiga/results/",
    "nor": "https://www.liveresult.ru/football/norway/eliteserien/results/",
    "irl": "https://www.liveresult.ru/football/ireland/premier-division/results/",
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def parse_results(league_code, url):
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"  Ошибка загрузки {url}: {e}")
        return []
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for row in soup.find_all("tr", class_=re.compile(r"match|result", re.I)):
        try:
            # Ищем финальный счёт
            score_el = row.find(class_=re.compile(r"score|result", re.I))
            if not score_el:
                continue
            score_text = score_el.get_text(strip=True)
            m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score_text)
            if not m:
                continue
            home_score, away_score = int(m.group(1)), int(m.group(2))

            # Команды
            teams = row.find_all(class_=re.compile(r"team|home|away", re.I))
            if len(teams) < 2:
                continue
            home_team = teams[0].get_text(strip=True).lower()
            away_team = teams[-1].get_text(strip=True).lower()

            # Дата
            date_el = row.find(class_=re.compile(r"date|time", re.I))
            if date_el:
                date_text = date_el.get_text(strip=True)
                try:
                    match_date = datetime.strptime(date_text, "%d.%m.%Y").strftime("%Y-%m-%d")
                except:
                    match_date = datetime.now().strftime("%Y-%m-%d")
            else:
                match_date = datetime.now().strftime("%Y-%m-%d")

            results.append({
                "league": league_code,
                "home_team": home_team,
                "away_team": away_team,
                "match_date": match_date,
                "home_score": home_score,
                "away_score": away_score,
            })
        except Exception:
            continue
    return results

def save_results(conn, results):
    saved = 0
    cur = conn.cursor()
    for r in results:
        existing = cur.execute("""
            SELECT id FROM results_raw
            WHERE league=? AND home_team=? AND away_team=? AND match_date=? AND is_finished=1
        """, (r["league"], r["home_team"], r["away_team"], r["match_date"])).fetchone()
        if existing:
            cur.execute("""
                UPDATE results_raw SET home_score=?, away_score=?
                WHERE id=?
            """, (r["home_score"], r["away_score"], existing["id"]))
        else:
            cur.execute("""
                INSERT INTO results_raw (league, match_date, home_team, away_team, home_score, away_score, is_finished, source)
                VALUES (?,?,?,?,?,?,1,'liveresult.ru')
            """, (r["league"], r["match_date"], r["home_team"], r["away_team"], r["home_score"], r["away_score"]))
            saved += 1
    conn.commit()
    return saved

def main():
    conn = get_conn()
    total = 0
    for league_code, url in LEAGUES.items():
        print(f"Парсим {league_code}...")
        results = parse_results(league_code, url)
        print(f"  Найдено: {len(results)}")
        saved = save_results(conn, results)
        print(f"  Сохранено: {saved}")
        total += saved
        time.sleep(1)
    conn.close()
    print(f"Done. Total saved: {total}")

if __name__ == "__main__":
    main()
