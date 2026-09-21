#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enricher_from_the_sports_nhl.py

Обогащает НХЛ матчи данными из standings и results_raw.

Запуск:
  python enricher_from_the_sports_nhl.py
  python enricher_from_the_sports_nhl.py --limit 20
"""

import os
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Optional

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
LEAGUE = "nhl"
MATCHES_LEAGUE_NAME = "НХЛ. Регулярный сезон"

# Маппинг коротких названий Фонбета → полные названия в standings/results_raw
FONBET_TO_FULL = {
    "Оттава":        "Оттава Сенаторз",
    "Анахайм":       "Анахайм Дакс",
    "Вашингтон":     "Вашингтон Кэпиталз",
    "Бостон":        "Бостон Брюинз",
    "Виннипег":      "Виннипег Джетс",
    "Колорадо":      "Колорадо Эвеланш",
    "Миннесота":     "Миннесота Уайлд",
    "Рейнджерс":     "Нью-Йорк Рейнджерс",
    "Нью-Джерси":    "Нью-Джерси Девилз",
    "Лос-Анджелес":  "Лос-Анджелес Кингз",
    "Айлендерс":     "Нью-Йорк Айлендерс",
    "Калгари":       "Калгари Флэймз",
    "Тампа-Бэй":     "Тампа-Бэй Лайтнинг",
    "Каролина":      "Каролина Харрикейнз",
    "Монреаль":      "Монреаль Канадиенс",
    "Сан-Хосе":      "Сан-Хосе Шаркс",
    "Баффало":       "Баффало Сейбрз",
    "Торонто":       "Торонто Мэйпл Лифс",
    "Филадельфия":   "Филадельфия Флайерз",
    "Коламбус":      "Коламбус Блю Джекетс",
    "Даллас":        "Даллас Старз",
    "Детройт":       "Детройт Ред Уингз",
    "Юта":           "Юта Хоккей Клаб",
    "Сент-Луис":     "Сент-Луис Блюз",
    "Питтсбург":     "Питтсбург Пингвинз",
    "Вегас":         "Вегас Голден Найтс",
    "Чикаго":        "Чикаго Блэкхокс",
    "Ванкувер":      "Ванкувер Кэнакс",
    "Сиэтл":         "Сиэтл Кракен",
    "Сент-Луис":     "Сент-Луис Блюз",
    "Флорида":       "Флорида Пантерз",
    "Эдмонтон":      "Эдмонтон Ойлерз",
    "Нэшвилл":       "Нэшвилл Предаторз",
    "Аризона":       "Аризона Койотис",
}

def normalize_team(name: str) -> str:
    """Переводим короткое название Фонбета в полное для поиска в БД."""
    return FONBET_TO_FULL.get(name, name)

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

def get_upcoming_matches(conn: sqlite3.Connection, limit: int):
    return conn.execute("""
        SELECT id, home_team, away_team, match_date
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND league=?
        ORDER BY match_date ASC
        LIMIT ?
    """, (MATCHES_LEAGUE_NAME, limit)).fetchall()

def get_team_standing(conn: sqlite3.Connection, team_name: str):
    return conn.execute("""
        SELECT team_name, position, points, played, wins, draws, losses, goals_for, goals_against, goal_diff
        FROM standings
        WHERE league=?
          AND team_name=?
        LIMIT 1
    """, (LEAGUE, team_name)).fetchone()

def get_last_results(conn: sqlite3.Connection, team_name: str, n: int = 5):
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
    """, (LEAGUE, team_name, team_name, n)).fetchall()
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

def get_h2h(conn: sqlite3.Connection, home_team: str, away_team: str, n: int = 5):
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
    """, (LEAGUE, home_team, away_team, away_team, home_team, n)).fetchall()
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
    # НХЛ: топ-3 в дивизионе + wildcard (8 команд из 16 в конференции)
    if position <= 3:
        return f"Лидер дивизиона, борьба за посев (место {position})"
    if position <= 8:
        return f"Зона плей-офф, важно удержать место (место {position})"
    if position == 9:
        return f"Wildcard bubble — борьба за последнее место плей-офф (место {position})"
    if position >= 14:
        return f"Низ таблицы, мотивация на драфт-пик (место {position})"
    return f"Вне плей-офф зоны (место {position})"

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
        "TheSports NHL standings + results_raw",
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
    args = ap.parse_args()

    conn = get_conn()
    ensure_match_facts(conn)

    matches = get_upcoming_matches(conn, args.limit)
    if not matches:
        print("Нет upcoming матчей TheSports KHL.")
        conn.close()
        return

    print(f"Обновляем match_facts для {len(matches)} матчей НХЛ...\n")

    for m in matches:
        home = normalize_team(m["home_team"])
        away = normalize_team(m["away_team"])

        home_st = get_team_standing(conn, home)
        away_st = get_team_standing(conn, away)

        home_results = get_last_results(conn, home, 5)
        away_results = get_last_results(conn, away, 5)
        h2h_rows = get_h2h(conn, home, away, 5)

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
        )

        print(f"{home} — {away}")
        print(f"  форма: {home_form} vs {away_form}")
        print(f"  голы/5: {home_scored_avg}-{home_allowed_avg} vs {away_scored_avg}-{away_allowed_avg}")
        print(f"  H2H: {h2h_summary if h2h_summary else 'нет'}")
        print(f"  позиции: {home_pos}/{home_pts} vs {away_pos}/{away_pts}")
        print()

    conn.close()
    print("✅ Готово.")
    print("Дальше запускай:")
    print("  python agent_handoff_v7.py --dry-run --sport hockey --limit 20")

if __name__ == "__main__":
    main()
