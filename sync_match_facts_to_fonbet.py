#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_match_facts_to_fonbet.py

Задача:
- взять match_facts, посчитанные на матчах TheSports KHL
- найти соответствующие upcoming-матчи Fonbet KHL
- скопировать/синхронизировать факты по home_team + away_team + дате
- чтобы agent_handoff_v4 видел не пустые факты на fonbet-матчах

Почему это нужно:
- сейчас enricher_from_the_sports.py пишет match_facts для match_id матчей TheSports
- agent_handoff_v4 анализирует match_id матчей Fonbet (с odds)
- match_id разные -> факты не находятся -> PASS

Запуск:
  python sync_match_facts_to_fonbet.py
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
THE_SPORTS_LEAGUE = "TheSports KHL"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def get_the_sports_with_facts(conn):
    return conn.execute("""
        SELECT
            m.id as match_id,
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
            mf.notes
        FROM matches m
        JOIN match_facts mf ON mf.match_id = m.id
        WHERE m.league = ?
    """, (THE_SPORTS_LEAGUE,)).fetchall()

def get_matching_fonbet_matches(conn, home_team, away_team, match_day):
    return conn.execute("""
        SELECT id, home_team, away_team, league, match_date
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
          AND home_team=?
          AND away_team=?
          AND substr(match_date, 1, 10)=?
    """, (home_team, away_team, match_day)).fetchall()

def upsert_match_fact_for_target(conn, target_match_id, source_row):
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_facts WHERE match_id=?", (target_match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_text = "synced_from_the_sports"

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

    source_rows = get_the_sports_with_facts(conn)
    if not source_rows:
        print("Нет TheSports match_facts для синхронизации.")
        print("Сначала запусти:")
        print("  python the_sports_khl_parser.py")
        print("  python enricher_from_the_sports.py")
        conn.close()
        return

    synced = 0
    missed = 0

    print(f"Найдено TheSports матчей с фактами: {len(source_rows)}\n")

    for row in source_rows:
        home = row["home_team"]
        away = row["away_team"]
        day = row["match_day"]

        targets = get_matching_fonbet_matches(conn, home, away, day)

        if not targets:
            missed += 1
            continue

        for t in targets:
            upsert_match_fact_for_target(conn, t["id"], row)
            synced += 1
            print(f"SYNC: {home} — {away} | {day} -> Fonbet match_id={t['id']}")

    conn.close()
    print("\n✅ Готово.")
    print(f"Синхронизировано записей: {synced}")
    print(f"Не найдено совпадений: {missed}")
    print("\nТеперь запускай:")
    print("  python agent_handoff_v4.py --dry-run --sport hockey --limit 5")

if __name__ == "__main__":
    main()
