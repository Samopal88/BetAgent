#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
the_sports_khl_parser.py

Парсит страницу TheSports по КХЛ без pandas:
- standings (общая таблица)
- recent results (сыгранные матчи)
- upcoming fixtures (будущие матчи)

Пишет в betagent.db:
- standings
- matches (upsert по home/away/date/league)
- results_raw (история результатов/расписания для формы)

Запуск:
  python the_sports_khl_parser.py --html the_sports_standings.html
  python the_sports_khl_parser.py
"""

import os
import re
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

import requests
from bs4 import BeautifulSoup

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
DEFAULT_URL = "https://www.the-sports.org/ice-hockey-kontinental-hockey-league-khl-2025-2026-results-eprd137186.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

TEAM_MAP = {
    "Admiral Vladivostok": "Адмирал",
    "AK Bars Kazan": "Ак Барс",
    "Amur Khabarovsk": "Амур",
    "Avangard Omsk": "Авангард",
    "Avtomobilist Yekaterinburg": "Автомобилист",
    "Barys Nur-Sultan": "Барыс",
    "CSKA Moscow": "ЦСКА",
    "Dynamo Moscow": "Динамо Москва",
    "HC Dinamo Minsk": "Динамо Минск",
    "HC Sochi": "ХК Сочи",
    "Lada Togliatti": "Лада",
    "Lokomotiv Yaroslavl": "Локомотив Ярославль",
    "Metallurg Magnitogorsk": "Металлург Мг",
    "Neftekhimik Nizhnekamsk": "Нефтехимик",
    "Salavat Yulaev Ufa": "Салават Юлаев",
    "Severstal Cherepovets": "Северсталь",
    "Shanghai": "Шанхай Дрэгонс",
    "Sibir Novosibirsk": "Сибирь",
    "SKA Saint-Petersburg": "СКА",
    "Spartak Moscow": "Спартак",
    "Torpedo Nizhny Novgorod": "Торпедо НН",
    "Traktor Chelyabinsk": "Трактор",
}

LEAGUE = "khl"
LEAGUE_NAME = "TheSports KHL"

def normalize_team(name: str) -> str:
    name = re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name).strip()
    return TEAM_MAP.get(name, name)

def parse_date(date_str: str) -> Optional[str]:
    # "13 March 2026"
    try:
        dt = datetime.strptime(date_str.strip(), "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def get_html(html_path: Optional[str]) -> str:
    if html_path:
        return Path(html_path).read_text(encoding="utf-8", errors="ignore")
    return fetch_html(DEFAULT_URL)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_schema(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS standings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        team_name TEXT NOT NULL,
        position INTEGER,
        points INTEGER,
        played INTEGER,
        wins INTEGER,
        draws INTEGER,
        losses INTEGER,
        goals_for INTEGER,
        goals_against INTEGER,
        goal_diff INTEGER,
        source TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS results_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        match_date TEXT,
        kickoff TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        is_finished INTEGER DEFAULT 0,
        source TEXT,
        updated_at TEXT
    )
    """)

    # matches table expected by current project; create only if missing
    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fonbet_id TEXT,
        sport TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        match_date TEXT,
        odds_home REAL,
        odds_draw REAL,
        odds_away REAL,
        status TEXT DEFAULT 'upcoming',
        home_score INTEGER,
        away_score INTEGER,
        updated_at TEXT
    )
    """)
    conn.commit()

def safe_int(text: str) -> Optional[int]:
    text = text.strip().replace("+", "")
    if text == "-" or text == "":
        return None
    try:
        return int(text)
    except Exception:
        return None

def parse_standings(soup: BeautifulSoup) -> List[Tuple]:
    title = soup.find("h3", string=re.compile(r"Standings", re.I))
    if not title:
        raise RuntimeError("Не найден блок standings")

    table = title.find_next("table")
    if not table:
        raise RuntimeError("Не найдена standings table")

    rows = []
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    trs = table.find_all("tr")
    for tr in trs[1:]:
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue

        position = safe_int(tds[0].get_text(" ", strip=True))
        team_name = normalize_team(tds[1].get_text(" ", strip=True))
        points = safe_int(tds[2].get_text(" ", strip=True))
        played = safe_int(tds[3].get_text(" ", strip=True))
        wins = safe_int(tds[4].get_text(" ", strip=True))
        draws = safe_int(tds[5].get_text(" ", strip=True)) or 0
        losses = safe_int(tds[6].get_text(" ", strip=True))
        goals_for = safe_int(tds[7].get_text(" ", strip=True))
        goals_against = safe_int(tds[8].get_text(" ", strip=True))
        goal_diff = safe_int(tds[9].get_text(" ", strip=True))

        if not team_name or position is None:
            continue

        rows.append((
            LEAGUE,
            team_name,
            position,
            points,
            played,
            wins,
            draws,
            losses,
            goals_for,
            goals_against,
            goal_diff,
            DEFAULT_URL,
            updated_at,
        ))
    return rows

def parse_results_and_fixtures(soup: BeautifulSoup, debug_scores: bool = False) -> List[Tuple]:
    """
    Ищем все строки матчей до блока standings.
    Формат кортежа:
      (match_date, kickoff, home_team, away_team, home_score, away_score, is_finished)
    """
    rows = []
    current_date = None

    # Берём большой блок main content
    content = soup.find("div", class_="tab-container")
    if content is None:
        content = soup

    for tr in content.find_all("tr"):
        # дата
        h6 = tr.find("h6", class_="daterenc")
        if h6:
            current_date = parse_date(h6.get_text(" ", strip=True))
            continue

        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        # типичный матч: kickoff | home | score | away
        kickoff = tds[0].get_text(" ", strip=True)

        # пропускаем строки не похожие на матч
        if not re.match(r"^\d{1,2}h\d{2}$", kickoff):
            continue

        home_team = normalize_team(tds[1].get_text(" ", strip=True))
        score_text = tds[2].get_text(" ", strip=True)
        away_team = normalize_team(tds[3].get_text(" ", strip=True))

        if not home_team or not away_team:
            continue

        # Debug output for specific dates
        if debug_scores and current_date in ["2026-03-16", "2026-03-17"]:
            print(f"DEBUG: {current_date} | {kickoff} | {home_team} | '{score_text}' | {away_team}")

        # played "3 - 2", "3-2", "3:2", "3–2", "3-2 OT", "3-2 (SO)", etc.
        m = re.search(r"(\d+)\s*[-–:]\s*(\d+)(?:\s*(?:OT|SO|\(OT\)|\(SO\))?)", score_text)
        if m:
            home_score = int(m.group(1))
            away_score = int(m.group(2))
            is_finished = 1
        else:
            home_score = None
            away_score = None
            is_finished = 0

        rows.append((
            current_date,
            kickoff,
            home_team,
            away_team,
            home_score,
            away_score,
            is_finished,
        ))
    return rows

def save_standings(conn: sqlite3.Connection, rows: List[Tuple]):
    cur = conn.cursor()
    cur.execute("DELETE FROM standings WHERE league=?", (LEAGUE,))
    cur.executemany("""
        INSERT INTO standings (
            league, team_name, position, points, played,
            wins, draws, losses, goals_for, goals_against,
            goal_diff, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

def save_results_raw(conn: sqlite3.Connection, rows: List[Tuple]):
    cur = conn.cursor()
    cur.execute("DELETE FROM results_raw WHERE league=?", (LEAGUE,))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = [
        (LEAGUE, r[0], r[1], r[2], r[3], r[4], r[5], r[6], DEFAULT_URL, now)
        for r in rows
    ]
    cur.executemany("""
        INSERT INTO results_raw (
            league, match_date, kickoff, home_team, away_team,
            home_score, away_score, is_finished, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, payload)
    conn.commit()

def upsert_matches(conn: sqlite3.Connection, rows: List[Tuple]):
    """
    Обновляем matches из future/played матчей TheSports.
    Если матч уже есть — обновляем status и score.
    Если нет — вставляем.
    """
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for match_date, kickoff, home_team, away_team, home_score, away_score, is_finished in rows:
        if not match_date:
            continue

        dt = f"{match_date} {kickoff.replace('h', ':')}:00"
        status = "finished" if is_finished else "upcoming"

        existing = cur.execute("""
            SELECT id FROM matches
            WHERE sport='hockey'
              AND league=?
              AND home_team=?
              AND away_team=?
              AND substr(match_date,1,10)=?
            LIMIT 1
        """, (LEAGUE_NAME, home_team, away_team, match_date)).fetchone()

        if existing:
            cur.execute("""
                UPDATE matches
                SET status=?,
                    home_score=?,
                    away_score=?,
                    updated_at=?
                WHERE id=?
            """, (status, home_score, away_score, now, existing["id"]))
        else:
            cur.execute("""
                INSERT INTO matches (
                    fonbet_id, sport, league, home_team, away_team,
                    match_date, odds_home, odds_draw, odds_away,
                    status, home_score, away_score, updated_at
                ) VALUES (?, 'hockey', ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """, (
                None, LEAGUE_NAME, home_team, away_team, dt,
                status, home_score, away_score, now
            ))
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=None, help="путь к сохранённому HTML")
    ap.add_argument("--debug-scores", action="store_true", help="отладка парсинга счёта")
    args = ap.parse_args()

    html = get_html(args.html)
    soup = BeautifulSoup(html, "html.parser")

    standings_rows = parse_standings(soup)
    result_rows = parse_results_and_fixtures(soup, args.debug_scores)

    conn = get_conn()
    ensure_schema(conn)
    save_standings(conn, standings_rows)
    save_results_raw(conn, result_rows)
    upsert_matches(conn, result_rows)
    conn.close()

    finished = sum(1 for r in result_rows if r[6] == 1)
    upcoming = sum(1 for r in result_rows if r[6] == 0)

    print(f"✅ Standings saved: {len(standings_rows)}")
    print(f"✅ Results/fixtures saved: {len(result_rows)}")
    print(f"   finished: {finished}")
    print(f"   upcoming: {upcoming}")
    print("Top 5 standings:")
    for r in standings_rows[:5]:
        print(f"  {r[2]}. {r[1]} — {r[3]} pts, {r[8]}:{r[9]}")

if __name__ == "__main__":
    main()
