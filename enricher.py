#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — enricher.py

Задача:
- Обогащает матчи данными о форме, таблице, H2H
- Сохраняет данные в таблицу match_facts в betagent.db
- agent_handoff.py читает эти данные и добавляет в payload

Источники данных:
1. football-data.org (бесплатный API, футбол)
2. Прямой парсинг таблиц с открытых источников
3. Фонбет API (статистика если доступна)

Запуск:
  python enricher.py              # все предстоящие матчи
  python enricher.py --sport football
  python enricher.py --sport hockey
  python enricher.py --match-id 5
"""

import os
import re
import sqlite3
import json
import time
import urllib3
import requests
from datetime import datetime, timedelta
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

# football-data.org — бесплатный API для футбола
# Регистрация: https://www.football-data.org/client/register
# Бесплатный план: 10 запросов/мин, топ-5 лиг
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

# Маппинг наших лиг → коды football-data.org
LEAGUE_CODES = {
    "Россия. Премьер-Лига. Сезон 25/26": "PL_RU",       # нет в бесплатном
    "Англия. Премьер-Лига. Сезон 25/26": "PL",
    "Германия. Бундеслига. Сезон 25/26": "BL1",
    "Испания. Примера дивизион. Сезон 25/26": "PD",
    "Италия. Серия А. Сезон 25/26": "SA",
    "Франция. Лига 1. Сезон 25/26": "FL1",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


# ============================================
# БАЗА ДАННЫХ
# ============================================

def ensure_schema(conn: sqlite3.Connection):
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
            home_goals_conceded_avg REAL,
            away_goals_scored_avg REAL,
            away_goals_conceded_avg REAL,
            home_motivation TEXT,
            away_motivation TEXT,
            notes TEXT,
            source TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_upcoming_matches(conn, sport=None, match_id=None, limit=50):
    cur = conn.cursor()
    q = "SELECT * FROM matches WHERE status='upcoming'"
    params = []
    if sport:
        q += " AND sport=?"
        params.append(sport)
    if match_id:
        q += " AND id=?"
        params.append(match_id)
    q += " ORDER BY match_date ASC LIMIT ?"
    params.append(limit)
    return cur.execute(q, params).fetchall()


# ============================================
# FOOTBALL-DATA.ORG API
# ============================================

def get_standings_football_data(league_code: str) -> dict:
    """Получаем таблицу через football-data.org"""
    if not FOOTBALL_DATA_API_KEY:
        return {}

    url = f"https://api.football-data.org/v4/competitions/{league_code}/standings"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            standings = {}
            for table in data.get("standings", []):
                if table.get("type") == "TOTAL":
                    for row in table.get("table", []):
                        team_name = row["team"]["name"]
                        standings[team_name] = {
                            "position": row["position"],
                            "points": row["points"],
                            "played": row["playedGames"],
                            "won": row["won"],
                            "draw": row["draw"],
                            "lost": row["lost"],
                            "goals_for": row["goalsFor"],
                            "goals_against": row["goalsAgainst"],
                        }
            return standings
    except Exception as e:
        print(f"  ⚠️  football-data.org ошибка: {e}")
    return {}


def get_team_form_football_data(team_id: int, league_code: str) -> list:
    """Получаем последние 5 матчей команды"""
    if not FOOTBALL_DATA_API_KEY:
        return []

    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit=5"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            form = []
            for match in data.get("matches", [])[-5:]:
                score = match.get("score", {}).get("fullTime", {})
                home = match["homeTeam"]["name"]
                away = match["awayTeam"]["name"]
                gh = score.get("home", 0)
                ga = score.get("away", 0)
                form.append(f"{home} {gh}:{ga} {away}")
            return form
    except Exception as e:
        print(f"  ⚠️  form ошибка: {e}")
    return []


# ============================================
# ПРОСТОЙ ENRICHER БЕЗ API КЛЮЧА
# Использует открытые данные
# ============================================

def enrich_from_fonbet(match_row) -> dict:
    """
    Пробуем получить статистику прямо из Фонбет.
    Фонбет иногда передаёт статистику в eventMiscs.
    """
    facts = {
        "home_form": [],
        "away_form": [],
        "home_position": None,
        "away_position": None,
        "home_points": None,
        "away_points": None,
        "h2h_summary": "",
        "home_goals_scored_avg": None,
        "home_goals_conceded_avg": None,
        "away_goals_scored_avg": None,
        "away_goals_conceded_avg": None,
        "home_motivation": "",
        "away_motivation": "",
        "notes": "",
        "source": "none",
    }
    return facts



def get_standing_from_db(conn, team_name, league):
    """Ищем команду в таблице standings"""
    cur = conn.cursor()
    name_lower = team_name.lower()
    rows = cur.execute("SELECT * FROM standings WHERE league=?", (league,)).fetchall()
    for row in rows:
        db_name = row["team_name"].lower()
        if name_lower in db_name or db_name in name_lower:
            return dict(row)
        if name_lower.split()[0] in db_name or db_name.split()[0] in name_lower:
            return dict(row)
    return None

def enrich_football(match_row, standings_cache: dict, conn=None) -> dict:
    """Обогащаем футбольный матч через football-data.org"""

    facts = enrich_from_fonbet(match_row)
    league = match_row["league"]
    league_code = LEAGUE_CODES.get(league)

    if not league_code or not FOOTBALL_DATA_API_KEY:
        facts["notes"] = "FOOTBALL_DATA_API_KEY не задан. Регистрация: football-data.org/client/register (бесплатно)"

        # Пробуем взять из локальной БД standings
        home_data = get_standing_from_db(conn, match_row["home_team"], "rpl")
        away_data = get_standing_from_db(conn, match_row["away_team"], "rpl")
        if home_data:
            facts["home_position"] = home_data["position"]
            facts["home_points"] = home_data["points"]
            facts["source"] = "local_db"
            facts["notes"] = ""
        if away_data:
            facts["away_position"] = away_data["position"]
            facts["away_points"] = away_data["points"]
            facts["source"] = "local_db"
            facts["notes"] = ""
        return facts

    # Таблица
    if league_code not in standings_cache:
        print(f"  📊 Загружаем таблицу {league_code}...")
        standings_cache[league_code] = get_standings_football_data(league_code)
        time.sleep(6)  # 10 запросов/мин лимит

    standings = standings_cache.get(league_code, {})

    home = match_row["home_team"]
    away = match_row["away_team"]

    # Ищем команду в таблице (fuzzy match)
    def find_team(name, standings):
        name_lower = name.lower()
        for team_name, data in standings.items():
            if name_lower in team_name.lower() or team_name.lower() in name_lower:
                return data
        return None

    home_data = find_team(home, standings)
    away_data = find_team(away, standings)

    if home_data:
        facts["home_position"] = home_data["position"]
        facts["home_points"] = home_data["points"]
        gp = home_data["played"] or 1
        facts["home_goals_scored_avg"] = round(home_data["goals_for"] / gp, 2)
        facts["home_goals_conceded_avg"] = round(home_data["goals_against"] / gp, 2)
        facts["source"] = "football-data.org"

    if away_data:
        facts["away_position"] = away_data["position"]
        facts["away_points"] = away_data["points"]
        gp = away_data["played"] or 1
        facts["away_goals_scored_avg"] = round(away_data["goals_for"] / gp, 2)
        facts["away_goals_conceded_avg"] = round(away_data["goals_against"] / gp, 2)
        facts["source"] = "football-data.org"

    # Мотивация
    if home_data and away_data:
        hp = home_data["position"]
        ap = away_data["position"]

        if hp <= 4:
            facts["home_motivation"] = f"{home} борется за топ-4 (место {hp})"
        elif hp >= 16:
            facts["home_motivation"] = f"{home} в зоне вылета (место {hp})"

        if ap <= 4:
            facts["away_motivation"] = f"{away} борется за топ-4 (место {ap})"
        elif ap >= 16:
            facts["away_motivation"] = f"{away} в зоне вылета (место {ap})"

        diff = abs(hp - ap)
        if diff >= 10:
            leader = home if hp < ap else away
            outsider = away if hp < ap else home
            facts["notes"] = f"Большая разница в таблице: {leader} (#{min(hp,ap)}) vs {outsider} (#{max(hp,ap)})"

    return facts


def enrich_hockey(match_row, conn=None) -> dict:
    """
    КХЛ — нет бесплатного API.
    Пока возвращаем пустые факты с подсказкой.
    TODO: парсинг khl.ru или другого источника.
    """
    facts = enrich_from_fonbet(match_row)
    # Берём из локальной БД standings
    home_data = get_standing_from_db(conn, match_row["home_team"], "khl")
    away_data = get_standing_from_db(conn, match_row["away_team"], "khl")
    if home_data:
        facts["home_position"] = home_data["position"]
        facts["home_points"] = home_data["points"]
        facts["source"] = "local_db"
    if away_data:
        facts["away_position"] = away_data["position"]
        facts["away_points"] = away_data["points"]
        facts["source"] = "local_db"
    if not home_data and not away_data:
        facts["notes"] = "Команды не найдены в таблице. Запусти: python standings_parser.py"
    return facts


# ============================================
# СОХРАНЕНИЕ В БАЗУ
# ============================================

def save_facts(conn, match_id: int, facts: dict):
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT OR REPLACE INTO match_facts (
            match_id, home_form, away_form,
            home_position, away_position,
            home_points, away_points,
            h2h_summary,
            home_goals_scored_avg, home_goals_conceded_avg,
            away_goals_scored_avg, away_goals_conceded_avg,
            home_motivation, away_motivation,
            notes, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        json.dumps(facts["home_form"], ensure_ascii=False),
        json.dumps(facts["away_form"], ensure_ascii=False),
        facts["home_position"],
        facts["away_position"],
        facts["home_points"],
        facts["away_points"],
        facts["h2h_summary"],
        facts["home_goals_scored_avg"],
        facts["home_goals_conceded_avg"],
        facts["away_goals_scored_avg"],
        facts["away_goals_conceded_avg"],
        facts["home_motivation"],
        facts["away_motivation"],
        facts["notes"],
        facts["source"],
        now,
    ))
    conn.commit()


def print_facts(match_row, facts: dict):
    home = match_row["home_team"]
    away = match_row["away_team"]
    print(f"\n  {home} — {away}")
    print(f"  Источник: {facts['source']}")

    if facts["home_position"]:
        print(f"  {home}: место {facts['home_position']}, {facts['home_points']} очков")
    if facts["away_position"]:
        print(f"  {away}: место {facts['away_position']}, {facts['away_points']} очков")
    if facts["home_motivation"]:
        print(f"  Мотивация дома: {facts['home_motivation']}")
    if facts["away_motivation"]:
        print(f"  Мотивация гостей: {facts['away_motivation']}")
    if facts["notes"]:
        print(f"  📝 {facts['notes']}")


# ============================================
# ГЛАВНЫЙ ЗАПУСК
# ============================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=["football", "hockey"], default=None)
    parser.add_argument("--match-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    conn = get_conn()
    ensure_schema(conn)

    matches = fetch_upcoming_matches(conn, sport=args.sport, match_id=args.match_id, limit=args.limit)
    print(f"🔍 Обогащаем {len(matches)} матчей...")

    if not FOOTBALL_DATA_API_KEY:
        print()
        print("⚠️  FOOTBALL_DATA_API_KEY не задан!")
        print("   Для получения данных по футболу:")
        print("   1. Зайди на https://www.football-data.org/client/register")
        print("   2. Зарегистрируйся бесплатно")
        print("   3. Скопируй API ключ")
        print("   4. В PowerShell:")
        print('      $env:FOOTBALL_DATA_API_KEY="YOUR_KEY"')
        print()
        print("   Пока записываем пустые факты (агент будет работать без данных)")
        print()

    standings_cache = {}

    for match in matches:
        sport = match["sport"]

        if sport == "football":
            facts = enrich_football(match, standings_cache, conn=conn)
        elif sport == "hockey":
            facts = enrich_hockey(match, conn=conn)
        else:
            continue

        save_facts(conn, match["id"], facts)
        print_facts(match, facts)

    conn.close()

    print(f"\n✅ Готово!")
    if not FOOTBALL_DATA_API_KEY:
        print("   Зарегистрируйся на football-data.org чтобы получить реальные данные.")
    print("   Следующий шаг: python agent_handoff.py --dry-run --limit 10")


if __name__ == "__main__":
    main()
