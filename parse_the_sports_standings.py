#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_the_sports_standings.py

Задача:
- брать таблицу standings с TheSports
- сохранять её в betagent.db -> standings
- работать либо с live URL, либо с уже сохранённым HTML файлом

Почему так:
- сначала узко тестируем один надёжный кусок (standings)
- но сам файл уже сделан расширяемым под другие лиги

Примеры запуска:
    python parse_the_sports_standings.py --league khl
    python parse_the_sports_standings.py --league khl --html the_sports_standings.html
    python parse_the_sports_standings.py --league nhl --url "https://..."
"""

import os
import re
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

DEFAULT_URLS = {
    "khl": "https://www.the-sports.org/ice-hockey-kontinental-hockey-league-khl-2025-2026-results-eprd137186.html",
    # для NHL / футбола потом можно просто добавить URL сюда
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    return conn

def ensure_table(conn):
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
    conn.commit()

def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def load_html(html_path: str | None, url: str) -> str:
    if html_path:
        return Path(html_path).read_text(encoding="utf-8", errors="ignore")
    return fetch_html(url)

def pick_standings_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Ищем общую таблицу standings по колонкам Team / Pts / MP / GF / GA.
    """
    best = None
    best_score = -1

    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        score = 0
        for token in ["Team", "Pts", "MP", "GF", "GA"]:
            if token in cols:
                score += 1
        if len(df) >= 8:
            score += 1
        if score > best_score:
            best_score = score
            best = df

    if best is None or best_score < 4:
        raise RuntimeError("Не удалось найти standings-таблицу в HTML")

    return best.copy()

def normalize_team(name: str) -> str:
    if not isinstance(name, str):
        return ""
    # убираем "(RUS)" и подобные хвосты
    name = re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name).strip()
    # выравниваем некоторые названия под ваш проект
    mapping = {
        "Dynamo Moscow": "Динамо Москва",
        "AK Bars Kazan": "Ак Барс",
        "Avangard Omsk": "Авангард",
        "Metallurg Magnitogorsk": "Металлург Мг",
        "Lokomotiv Yaroslavl": "Локомотив Ярославль",
        "Severstal Cherepovets": "Северсталь",
        "Salavat Yulaev Ufa": "Салават Юлаев",
        "Sibir Novosibirsk": "Сибирь",
        "Admiral Vladivostok": "Адмирал",
        "Barys Astana": "Барыс",
        "HC Sochi": "ХК Сочи",
        "Kunlun Red Star": "Шанхай Дрэгонс",
        "Torpedo Nizhny Novgorod": "Торпедо НН",
        "Traktor Chelyabinsk": "Трактор",
        "CSKA Moscow": "ЦСКА",
        "SKA St. Petersburg": "СКА",
        "Dynamo Minsk": "Динамо Минск",
        "Neftekhimik Nizhnekamsk": "Нефтехимик",
        "Lada Togliatti": "Лада",
        "Amur Khabarovsk": "Амур",
        "Spartak Moscow": "Спартак",
    }
    return mapping.get(name, name)

def prepare_rows(df: pd.DataFrame, league: str, source: str) -> list[tuple]:
    # ожидаемые колонки:
    # ['Unnamed: 0','Team','Pts','MP','W','D','L','GF','GA','diff']
    cols = {str(c).strip(): c for c in df.columns}

    required = ["Team", "Pts", "MP", "W", "L", "GF", "GA"]
    for col in required:
        if col not in cols:
            raise RuntimeError(f"В выбранной таблице нет колонки {col}")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for idx, row in df.iterrows():
        team_raw = row[cols["Team"]]
        team_name = normalize_team(str(team_raw))
        if not team_name:
            continue

        try:
            position = int(row[cols.get("Unnamed: 0")] if "Unnamed: 0" in cols else idx + 1)
        except Exception:
            position = idx + 1

        def to_int(v):
            try:
                return int(v)
            except Exception:
                return None

        points = to_int(row[cols["Pts"]])
        played = to_int(row[cols["MP"]])
        wins = to_int(row[cols["W"]])
        draws = to_int(row[cols["D"]]) if "D" in cols else 0
        losses = to_int(row[cols["L"]])
        goals_for = to_int(row[cols["GF"]])
        goals_against = to_int(row[cols["GA"]])
        goal_diff = to_int(row[cols["diff"]]) if "diff" in cols else None

        rows.append((
            league,
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
            source,
            updated_at,
        ))

    return rows

def save_rows(conn, league: str, rows: list[tuple]):
    cur = conn.cursor()
    cur.execute("DELETE FROM standings WHERE league = ?", (league,))
    cur.executemany("""
        INSERT INTO standings (
            league, team_name, position, points, played,
            wins, draws, losses, goals_for, goals_against,
            goal_diff, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, help="например: khl")
    ap.add_argument("--url", default=None, help="URL страницы standings/results")
    ap.add_argument("--html", default=None, help="путь к сохранённому HTML файлу")
    args = ap.parse_args()

    league = args.league.lower()
    url = args.url or DEFAULT_URLS.get(league)
    if not url and not args.html:
        raise SystemExit("Нужно указать --url или --html")

    html = load_html(args.html, url)
    tables = pd.read_html(html)
    table = pick_standings_table(tables)
    rows = prepare_rows(table, league=league, source=args.html or url)

    conn = get_conn()
    ensure_table(conn)
    save_rows(conn, league, rows)
    conn.close()

    print(f"✅ Сохранено команд: {len(rows)}")
    print(f"Лига: {league}")
    print(f"Источник: {args.html or url}")
    print("Первые 5 команд:")
    for r in rows[:5]:
        print(f"  {r[2]}. {r[1]} — {r[3]} pts, {r[8]}:{r[9]}")

if __name__ == "__main__":
    main()
