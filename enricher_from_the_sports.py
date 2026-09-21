#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enricher_from_the_sports.py

Берёт данные из:
- standings
- results_raw
- matches

И заполняет/обновляет match_facts для upcoming матчей:
- home_form / away_form (последние 5: W/L)
- home_goals_scored_avg / away_goals_scored_avg (по последним 5)
- home_goals_allowed_avg / away_goals_allowed_avg (по последним 5)
- h2h_summary
- home_position / away_position
- home_points / away_points
- home_motivation / away_motivation
- notes
- updated_at / source

Запуск:
  python enricher_from_the_sports.py
  python enricher_from_the_sports.py --limit 20
  python enricher_from_the_sports.py --league czech
  python enricher_from_the_sports.py --league nhl
"""

import os
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

# Shared hockey league configuration
HOCKEY_SOURCE_CONFIG = {
    "KHL": {
        "league_key": "khl",
        "matches_league_name": "TheSports KHL",
        "source_name": "TheSports KHL standings + results_raw",
    },
    "NHL": {
        "league_key": "nhl",
        "matches_league_name": "TheSports NHL",
        "source_name": "TheSports NHL standings + results_raw",
    },
    "CZECH": {
        "league_key": "czech",
        "matches_league_name": "TheSports Czech",
        "source_name": "TheSports Czech standings + results_raw",
    }
}

# Default to KHL for backward compatibility
LEAGUE = HOCKEY_SOURCE_CONFIG["KHL"]["league_key"]
MATCHES_LEAGUE_NAME = HOCKEY_SOURCE_CONFIG["KHL"]["matches_league_name"]

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_match_facts(conn: sqlite3.Connection):
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

def get_upcoming_matches(conn: sqlite3.Connection, league: str, limit: int):
    return conn.execute("""
        SELECT id, home_team, away_team, match_date
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND league=?
        ORDER BY match_date ASC
        LIMIT ?
    """, (league, limit)).fetchall()

def get_team_standing(conn: sqlite3.Connection, team_name: str, league: str):
    return conn.execute("""
        SELECT team_name, position, points, played, wins, draws, losses, goals_for, goals_against, goal_diff
        FROM standings
        WHERE league=?
          AND team_name=?
        LIMIT 1
    """, (league, team_name)).fetchone()

def get_last_results(conn: sqlite3.Connection, team_name: str, league: str, n: int = 5):
    """
    Последние finished матчи команды из results_raw
    """
    rows = conn.execute("""
        SELECT match_date, kickoff, home_team, away_team, home_score, away_score
        FROM results_raw
        WHERE league=?
          AND is_finished=1
          AND (home_team=? OR away_team=?)
        ORDER BY match_date DESC, kickoff DESC
        LIMIT ?
    """, (league, team_name, team_name, n)).fetchall()
    return rows

def form_from_results(team_name: str, rows) -> List[str]:
    form = []
    for r in rows:
        if r["home_team"] == team_name:
            if r["home_score"] > r["away_score"]:
                form.append("W")
            else:
                form.append("L")
        elif r["away_team"] == team_name:
            if r["away_score"] > r["home_score"]:
                form.append("W")
            else:
                form.append("L")
    return form

def goals_avg_from_results(team_name: str, rows):
    scored = []
    allowed = []
    for r in rows:
        if r["home_team"] == team_name:
            scored.append(r["home_score"])
            allowed.append(r["away_score"])
        elif r["away_team"] == team_name:
            scored.append(r["away_score"])
            allowed.append(r["home_score"])
    if not scored:
        return None, None
    return round(sum(scored) / len(scored), 2), round(sum(allowed) / len(allowed), 2)

def get_h2h(conn: sqlite3.Connection, home_team: str, away_team: str, league: str, n: int = 5):
    rows = conn.execute("""
        SELECT match_date, home_team, away_team, home_score, away_score
        FROM results_raw
        WHERE league=?
          AND is_finished=1
          AND (
            (home_team=? AND away_team=?)
            OR
            (home_team=? AND away_team=?)
          )
        ORDER BY match_date DESC
        LIMIT ?
    """, (league, home_team, away_team, away_team, home_team, n)).fetchall()
    return rows

def build_h2h_summary(home_team: str, away_team: str, rows) -> str:
    if not rows:
        return ""
    home_wins = 0
    away_wins = 0
    scores = []
    for r in rows:
        hs, a_s = r["home_score"], r["away_score"]
        if r["home_team"] == home_team:
            if hs > a_s:
                home_wins += 1
            elif a_s > hs:
                away_wins += 1
            scores.append(f"{hs}:{a_s}")
        else:
            # инвертируем к перспективе home_team текущего матча
            if a_s > hs:
                home_wins += 1
            elif hs > a_s:
                away_wins += 1
            scores.append(f"{a_s}:{hs}")
    return f"H2H last {len(rows)}: {home_team} {home_wins} wins, {away_team} {away_wins} wins | scores: {', '.join(scores)}"

def get_motivation(position: Optional[int], points: Optional[int]) -> str:
    if position is None:
        return ""
    if position <= 4:
        return f"Топ зоны таблицы, борьба за высокий посев (место {position})"
    if position <= 8:
        return f"Зона плей-офф, важно удержать место (место {position})"
    if position <= 12:
        return f"Пограничная зона / борьба за плей-офф (место {position})"
    if position <= 18:
        return f"Нижняя середина таблицы, мотивация зависит от дистанции до топ-8 (место {position})"
    return f"Низ таблицы, турнирная мотивация ограничена (место {position})"

def upsert_match_fact(
    conn: sqlite3.Connection,
    match_id: int,
    home_form: List[str],
    away_form: List[str],
    home_pos: Optional[int],
    away_pos: Optional[int],
    home_pts: Optional[int],
    away_pts: Optional[int],
    h2h_summary: str,
    home_scored_avg: Optional[float],
    away_scored_avg: Optional[float],
    home_allowed_avg: Optional[float],
    away_allowed_avg: Optional[float],
    home_motivation: str,
    away_motivation: str,
    notes: str,
    source_name: str,
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_facts WHERE match_id=?", (match_id,)).fetchone()

    payload = (
        json.dumps(home_form, ensure_ascii=False),
        json.dumps(away_form, ensure_ascii=False),
        home_pos,
        away_pos,
        home_pts,
        away_pts,
        h2h_summary,
        home_scored_avg,
        away_scored_avg,
        home_allowed_avg,
        away_allowed_avg,
        home_motivation,
        away_motivation,
        notes,
        source_name,
        now,
        match_id,
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
        """, payload)
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
        """, payload)
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--league", type=str, default="khl", choices=["khl", "nhl", "czech"], 
                    help="Hockey league to process (khl, nhl, czech)")
    args = ap.parse_args()

    # Set league configuration based on argument
    league_key = args.league.upper()
    if league_key not in HOCKEY_SOURCE_CONFIG:
        print(f"Unsupported league: {args.league}")
        return
    
    league_config = HOCKEY_SOURCE_CONFIG[league_key]
    league = league_config["league_key"]
    matches_league_name = league_config["matches_league_name"]
    source_name = league_config["source_name"]
    
    print(f"[HOCKEY SOURCE] league_key={league_key}, db_key={league}, matches_name={matches_league_name}")

    conn = get_conn()
    ensure_match_facts(conn)

    matches = get_upcoming_matches(conn, league=matches_league_name, limit=args.limit)
    if not matches:
        print(f"Нет upcoming матчей {matches_league_name}.")
        conn.close()
        return

    print(f"Обновляем match_facts для {len(matches)} матчей лиги {league_key}...\n")

    for m in matches:
        home = m["home_team"]
        away = m["away_team"]
        
        # Log league detection for Czech matches
        if league_key == "CZECH":
            print(f"[CZECH ENRICHMENT] Processing {home} vs {away}")

        home_st = get_team_standing(conn, home, league)
        away_st = get_team_standing(conn, away, league)

        home_results = get_last_results(conn, home, league, 5)
        away_results = get_last_results(conn, away, league, 5)
        h2h_rows = get_h2h(conn, home, away, league, 5)

        home_form = form_from_results(home, home_results)
        away_form = form_from_results(away, away_results)

        home_scored_avg, home_allowed_avg = goals_avg_from_results(home, home_results)
        away_scored_avg, away_allowed_avg = goals_avg_from_results(away, away_results)

        h2h_summary = build_h2h_summary(home, away, h2h_rows)

        home_pos = home_st["position"] if home_st else None
        away_pos = away_st["position"] if away_st else None
        home_pts = home_st["points"] if home_st else None
        away_pts = away_st["points"] if away_st else None

        home_motivation = get_motivation(home_pos, home_pts)
        away_motivation = get_motivation(away_pos, away_pts)

        notes = []
        if len(home_form) < 5:
            notes.append(f"У {home} найдено только {len(home_form)} матчей формы")
        if len(away_form) < 5:
            notes.append(f"У {away} найдено только {len(away_form)} матчей формы")
        if not h2h_summary:
            notes.append("H2H пустой")

        upsert_match_fact(
            conn=conn,
            match_id=m["id"],
            home_form=home_form,
            away_form=away_form,
            home_pos=home_pos,
            away_pos=away_pos,
            home_pts=home_pts,
            away_pts=away_pts,
            h2h_summary=h2h_summary,
            home_scored_avg=home_scored_avg,
            away_scored_avg=away_scored_avg,
            home_allowed_avg=home_allowed_avg,
            away_allowed_avg=away_allowed_avg,
            home_motivation=home_motivation,
            away_motivation=away_motivation,
            notes=" | ".join(notes),
            source_name=source_name,
        )

        print(f"{home} — {away}")
        print(f"  форма: {home_form} vs {away_form}")
        print(f"  голы/5: {home_scored_avg}-{home_allowed_avg} vs {away_scored_avg}-{away_allowed_avg}")
        print(f"  H2H: {h2h_summary if h2h_summary else 'нет'}")
        print(f"  позиции: {home_pos}/{home_pts} vs {away_pos}/{away_pts}")
        
        # Additional logging for Czech matches
        if league_key == "CZECH":
            print(f"  [CZECH FACTS] Updated for match_id={m['id']}")
        print()

    conn.close()
    print("✅ Готово.")
    print("Дальше запускай:")
    if league_key == "CZECH":
        print("  python sync_match_facts_v3.py")
        print("  python agent_handoff_v7.py --dry-run --sport hockey --league czech --limit 5")
    else:
        print("  python agent_handoff_v7.py --dry-run --sport hockey --limit 5")

if __name__ == "__main__":
    main()
