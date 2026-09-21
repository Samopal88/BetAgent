#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_match_facts_to_fonbet_v2.py

Улучшенный матчинг TheSports -> Fonbet:
- матчим по home_team + away_team
- дата допускается с окном +/- 1 день
- если несколько кандидатов, берём ближайший по дате
- можно синхронизировать даже если TheSports и Fonbet разошлись на день из-за timezone

Запуск:
  python sync_match_facts_to_fonbet_v2.py
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
THE_SPORTS_SOURCE_TOKEN = "TheSports"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def parse_day(s: str):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()

def ensure_match_facts(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS match_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER UNIQUE,
        home_form TEXT,
        away_form TEXT,
        home_position INTEGER,
        away_position INTEGER,
        home_points INTEGER,
        away_points INTEGER,
        h2h_summary TEXT,
        home_goals_scored_avg REAL,
        away_goals_scored_avg REAL,
        home_goals_allowed_avg REAL,
        away_goals_allowed_avg REAL,
        home_motivation TEXT,
        away_motivation TEXT,
        notes TEXT,
        source TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()

def get_source_fact_rows(conn):
    """
    Берём все match_facts, которые пришли из TheSports enrichment.
    Не полагаемся на league='TheSports KHL', а на source.
    """
    rows = conn.execute("""
        SELECT
            mf.match_id,
            m.home_team,
            m.away_team,
            substr(m.match_date, 1, 10) as match_day,
            mf.home_form,
            mf.away_form,
            mf.home_position,
            mf.away_position,
            mf.home_points,
            mf.away_points,
            mf.h2h_summary,
            mf.home_goals_scored_avg,
            mf.away_goals_scored_avg,
            mf.home_goals_allowed_avg,
            mf.away_goals_allowed_avg,
            mf.home_motivation,
            mf.away_motivation,
            mf.notes,
            mf.source
        FROM match_facts mf
        JOIN matches m ON m.id = mf.match_id
        WHERE mf.source LIKE ?
    """, (f"%{THE_SPORTS_SOURCE_TOKEN}%",)).fetchall()
    return rows

def get_fonbet_candidates(conn, home_team, away_team):
    """
    Кандидаты только среди upcoming хоккея с odds.
    """
    rows = conn.execute("""
        SELECT
            id,
            home_team,
            away_team,
            league,
            match_date,
            substr(match_date, 1, 10) as match_day,
            odds_home,
            odds_away
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
          AND home_team=?
          AND away_team=?
    """, (home_team, away_team)).fetchall()
    return rows

def pick_best_candidate(source_day, candidates):
    """
    Выбираем кандидата с минимальным расстоянием по дате.
    Разрешаем окно +/- 1 день.
    """
    if not candidates:
        return None

    src = parse_day(source_day)
    scored = []
    for c in candidates:
        d = parse_day(c["match_day"])
        delta = abs((d - src).days)
        if delta <= 1:
            scored.append((delta, c))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0])
    return scored[0][1]

def upsert_target_fact(conn, target_match_id, source_row):
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_facts WHERE match_id=?", (target_match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_text = "synced_from_the_sports_v2"

    values = (
        source_row["home_form"],
        source_row["away_form"],
        source_row["home_position"],
        source_row["away_position"],
        source_row["home_points"],
        source_row["away_points"],
        source_row["h2h_summary"],
        source_row["home_goals_scored_avg"],
        source_row["away_goals_scored_avg"],
        source_row["home_goals_allowed_avg"],
        source_row["away_goals_allowed_avg"],
        source_row["home_motivation"],
        source_row["away_motivation"],
        source_row["notes"],
        source_text,
        now,
        target_match_id,
    )

    if existing:
        cur.execute("""
            UPDATE match_facts
            SET home_form=?,
                away_form=?,
                home_position=?,
                away_position=?,
                home_points=?,
                away_points=?,
                h2h_summary=?,
                home_goals_scored_avg=?,
                away_goals_scored_avg=?,
                home_goals_allowed_avg=?,
                away_goals_allowed_avg=?,
                home_motivation=?,
                away_motivation=?,
                notes=?,
                source=?,
                updated_at=?
            WHERE match_id=?
        """, values)
    else:
        cur.execute("""
            INSERT INTO match_facts (
                home_form, away_form, home_position, away_position,
                home_points, away_points, h2h_summary,
                home_goals_scored_avg, away_goals_scored_avg,
                home_goals_allowed_avg, away_goals_allowed_avg,
                home_motivation, away_motivation, notes,
                source, updated_at, match_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)

    conn.commit()

def main():
    conn = get_conn()
    ensure_match_facts(conn)

    source_rows = get_source_fact_rows(conn)
    if not source_rows:
        print("Не найдено source match_facts от TheSports.")
        print("Сначала запусти:")
        print("  python the_sports_khl_parser.py")
        print("  python enricher_from_the_sports.py")
        conn.close()
        return

    print(f"Найдено source match_facts: {len(source_rows)}\n")

    synced = 0
    missed = 0

    for row in source_rows:
        candidates = get_fonbet_candidates(conn, row["home_team"], row["away_team"])
        best = pick_best_candidate(row["match_day"], candidates)

        if not best:
            missed += 1
            continue

        upsert_target_fact(conn, best["id"], row)
        synced += 1
        print(
            f"SYNC: {row['home_team']} — {row['away_team']} | "
            f"TheSports={row['match_day']} -> Fonbet={best['match_day']} | match_id={best['id']}"
        )

    conn.close()
    print("\n✅ Готово.")
    print(f"Синхронизировано: {synced}")
    print(f"Не найдено: {missed}")
    print("\nТеперь запускай:")
    print("  python agent_handoff_v4.py --dry-run --sport hockey --limit 5")

if __name__ == "__main__":
    main()
