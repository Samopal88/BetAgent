#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — enricher_football.py

Обогащает футбольные матчи данными из football-data.org:
- standings (позиция, очки)
- last 5 results (форма)
- h2h последние матчи
- средние голы

Поддерживаемые лиги (бесплатный план):
  PL   — Англия. Премьер-Лига
  BL1  — Германия. Бундеслига
  SA   — Италия. Серия А
  PD   — Испания. Примера
  FL1  — Франция. Лига 1

РПЛ — не входит в бесплатный план, обрабатывается отдельно
(standings_parser.py + заглушка или парсинг с другого источника)

Запуск:
  python enricher_football.py
  python enricher_football.py --limit 10
  python enricher_football.py --league PL --limit 5
"""

import os
import json
import time
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {
    "X-Auth-Token": API_KEY,
    "Accept": "application/json",
}

# Маппинг: название лиги в Фонбете → код в football-data.org
LEAGUE_MAP = {
    "Англия. Премьер-Лига. Сезон 25/26":      "PL",
    "Германия. Бундеслига. Сезон 25/26":       "BL1",
    "Италия. Серия А. Сезон 25/26":            "SA",
    "Испания. Примера дивизион. Сезон 25/26":  "PD",
    "Франция. Лига 1. Сезон 25/26":            "FL1",
}

# Коды лиг → season year
SEASON_YEAR = {
    "PL": 2025, "BL1": 2025, "SA": 2025, "PD": 2025, "FL1": 2025,
}

# Маппинг названий команд Фонбет → football-data.org
# Пополняй по мере появления несовпадений
TEAM_NAME_MAP = {
    # АПЛ
    "Сандерленд":           "Sunderland AFC",
    "Брайтон":              "Brighton & Hove Albion FC",
    "Бернли":               "Burnley FC",
    "Борнмут":              "AFC Bournemouth",
    "Челси":                "Chelsea FC",
    "Ньюкасл":              "Newcastle United FC",
    "Арсенал":              "Arsenal FC",
    "Эвертон":              "Everton FC",
    "Вест Хэм":             "West Ham United FC",
    "Манчестер Сити":       "Manchester City FC",
    "Ноттингем Форест":     "Nottingham Forest FC",
    "Фулхэм":               "Fulham FC",
    "Кристал Пэлас":        "Crystal Palace FC",
    "Лидс Юнайтед":         "Leeds United FC",
    "Лидс":                 "Leeds United FC",
    "Манчестер Юнайтед":    "Manchester United FC",
    "Астон Вилла":          "Aston Villa FC",
    "Ливерпуль":            "Liverpool FC",
    "Брентфорд":            "Brentford FC",
    "Тоттенхэм":            "Tottenham Hotspur FC",
    "Вулверхэмптон":        "Wolverhampton Wanderers FC",
    # Бундеслига
    "Байер Леверкузен":     "Bayer 04 Leverkusen",
    "Бавария":              "FC Bayern München",
    "Боруссия Дортмунд":    "Borussia Dortmund",
    "Аугсбург":             "FC Augsburg",
    "Хоффенхайм":           "TSG 1899 Hoffenheim",
    "Вольфсбург":           "VfL Wolfsburg",
    "Айнтрахт Франкфурт":   "Eintracht Frankfurt",
    "Хайденхайм":           "1. FC Heidenheim 1846",
    "Гамбург":              "Hamburger SV",
    "Кельн":                "1. FC Köln",
    "Лейпциг":              "RB Leipzig",
    "Вердер":               "SV Werder Bremen",
    "Унион Берлин":         "1. FC Union Berlin",
    "Боруссия Менхенгладбах": "Borussia Mönchengladbach",
    "Штутгарт":               "VfB Stuttgart",
    "Фрайбург":               "SC Freiburg",
    "Санкт-Паули":            "FC St. Pauli 1910",
    "Майнц":                  "1. FSV Mainz 05",
    # Серия А
    "Интер Милан":          "FC Internazionale Milano",
    "Аталанта":             "Atalanta BC",
    "Наполи":               "SSC Napoli",
    "Лечче":                "US Lecce",
    "Удинезе":              "Udinese Calcio",
    "Ювентус":              "Juventus FC",
    "Кальяри":              "Cagliari Calcio",
    "Дженоа":               "Genoa CFC",
    "Парма":                "Parma Calcio 1913",
    "Кремонезе":            "US Cremonese",
    "Милан":                "AC Milan",
    "Торино":               "Torino FC",
    "Сассуоло":             "US Sassuolo Calcio",
    "Комо":                 "Como 1907",
    "Пиза":                 "AC Pisa 1909",
    "Верона":               "Hellas Verona FC",
    "Фиорентина":           "ACF Fiorentina",
    "Рома":                 "AS Roma",
    "Лацио":                "SS Lazio",
    "Болонья":              "Bologna FC 1909",
    # Примера
    "Жирона":               "Girona FC",
    "Атлетик Бильбао":      "Athletic Club",
    "Атлетико Мадрид":      "Club Atlético de Madrid",
    "Хетафе":               "Getafe CF",
    "Реал Мадрид":          "Real Madrid CF",
    "Эльче":                "Elche CF",
    "Мальорка":             "RCD Mallorca",
    "Эспаньол":             "RCD Espanyol de Barcelona",
    "Овьедо":               "Real Oviedo",
    "Валенсия":             "Valencia CF",
    "Вильярреал":           "Villarreal CF",
    "Реал Сосьедад":        "Real Sociedad de Fútbol",
    "Осасуна":              "CA Osasuna",
    "Леванте":              "Levante UD",
    "Севилья":              "Sevilla FC",
    "Барселона":            "FC Barcelona",
    "Райо Вальекано":       "Rayo Vallecano de Madrid",
    "Сельта":               "RC Celta de Vigo",
    "Бетис":                "Real Betis Balompié",
    "Алавес":               "Deportivo Alavés",
    # Лига 1
    "Лорьян":               "FC Lorient",
    "Ланс":                 "Racing Club de Lens",
    "Анже":                 "Angers SCO",
    "Ницца":                "OGC Nice",
    "Монако":               "AS Monaco FC",
    "Брест":                "Stade Brestois 29",
    "Тулуза":               "Toulouse FC",
    "Осер":                 "AJ Auxerre",
    "ПСЖ":                  "Paris Saint-Germain FC",
    "Париж":               "Paris Saint-Germain FC",
    "Марсель":              "Olympique de Marseille",
    "Лион":                 "Olympique Lyonnais",
    "Лилль":                "Lille OSC",
    "Ренн":                 "Stade Rennais FC 1901",
    "Нант":                 "FC Nantes",
    "Мец":                  "FC Metz",
    "Гавр":                 "Le Havre AC",
    "Страсбур":             "RC Strasbourg Alsace",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_match_facts(conn):
    conn.execute("""
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


def api_get(path: str, params: dict = None) -> Optional[dict]:
    """Запрос к football-data.org с rate limit (10 req/min бесплатно)."""
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15, verify=False)
        if r.status_code == 429:
            print("    ⏳ Rate limit, ждём 60 сек...")
            time.sleep(60)
            r = requests.get(url, headers=HEADERS, params=params, timeout=15, verify=False)
        if r.status_code == 200:
            return r.json()
        print(f"    ⚠️  API {r.status_code}: {url}")
        return None
    except Exception as e:
        print(f"    ❌ API error: {e}")
        return None


# ============================================================
# КЭШИ (в памяти за один запуск)
# ============================================================
_standings_cache = {}   # league_code → {team_name_api: {position, points, played, gf, ga}}
_matches_cache   = {}   # league_code → list of finished matches


def get_standings(league_code: str) -> dict:
    if league_code in _standings_cache:
        return _standings_cache[league_code]

    season = SEASON_YEAR.get(league_code, 2025)
    data = api_get(f"/competitions/{league_code}/standings", {"season": season})
    time.sleep(6)  # rate limit

    result = {}
    if not data:
        _standings_cache[league_code] = result
        return result

    for standing_group in data.get("standings", []):
        if standing_group.get("type") != "TOTAL":
            continue
        for row in standing_group.get("table", []):
            name = row.get("team", {}).get("name", "")
            result[name] = {
                "position": row.get("position"),
                "points": row.get("points"),
                "played": row.get("playedGames"),
                "won": row.get("won"),
                "draw": row.get("draw"),
                "lost": row.get("lost"),
                "goals_for": row.get("goalsFor"),
                "goals_against": row.get("goalsAgainst"),
            }

    _standings_cache[league_code] = result
    return result


def get_finished_matches(league_code: str) -> list:
    if league_code in _matches_cache:
        return _matches_cache[league_code]

    season = SEASON_YEAR.get(league_code, 2025)
    data = api_get(
        f"/competitions/{league_code}/matches",
        {"season": season, "status": "FINISHED"}
    )
    time.sleep(6)

    matches = []
    if data:
        matches = data.get("matches", [])

    _matches_cache[league_code] = matches
    return matches


def resolve_team_name(fonbet_name: str) -> str:
    """Переводим название команды из Фонбета в формат football-data.org."""
    return TEAM_NAME_MAP.get(fonbet_name, fonbet_name)


def find_team_in_standings(standings: dict, api_name: str) -> Optional[dict]:
    """Ищем команду в standings — точно или fuzzy."""
    if api_name in standings:
        return standings[api_name]

    name_lower = api_name.lower()
    for key, val in standings.items():
        if name_lower in key.lower() or key.lower() in name_lower:
            return val
        # По первому слову
        if name_lower.split()[0] in key.lower():
            return val

    return None


def get_team_last5(matches: list, api_name: str) -> tuple:
    """
    Последние 5 матчей команды → форма [W/D/L] и средние голы.
    Возвращает (form_list, goals_scored_avg, goals_allowed_avg).
    """
    team_matches = []
    for m in matches:
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        if api_name not in (home, away):
            continue
        score = m.get("score", {}).get("fullTime", {})
        if score.get("home") is None:
            continue
        team_matches.append(m)

    # Берём последние 5 по дате
    team_matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    last5 = team_matches[:5]

    form = []
    scored = []
    allowed = []

    for m in last5:
        home = m.get("homeTeam", {}).get("name", "")
        score = m.get("score", {}).get("fullTime", {})
        gh = score.get("home", 0) or 0
        ga = score.get("away", 0) or 0

        if api_name == home:
            scored.append(gh)
            allowed.append(ga)
            if gh > ga:
                form.append("W")
            elif gh == ga:
                form.append("D")
            else:
                form.append("L")
        else:
            scored.append(ga)
            allowed.append(gh)
            if ga > gh:
                form.append("W")
            elif gh == ga:
                form.append("D")
            else:
                form.append("L")

    goals_avg = round(sum(scored) / len(scored), 2) if scored else None
    allowed_avg = round(sum(allowed) / len(allowed), 2) if allowed else None

    return form, goals_avg, allowed_avg


def get_h2h_summary(matches: list, home_api: str, away_api: str) -> str:
    """H2H последние 5 матчей между двумя командами."""
    h2h = []
    for m in matches:
        mh = m.get("homeTeam", {}).get("name", "")
        ma = m.get("awayTeam", {}).get("name", "")
        if {mh, ma} != {home_api, away_api}:
            continue
        score = m.get("score", {}).get("fullTime", {})
        if score.get("home") is None:
            continue
        h2h.append(m)

    h2h.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    h2h = h2h[:5]

    if not h2h:
        return ""

    home_wins = away_wins = draws = 0
    scores = []

    for m in h2h:
        mh = m.get("homeTeam", {}).get("name", "")
        score = m.get("score", {}).get("fullTime", {})
        gh = score.get("home", 0) or 0
        ga = score.get("away", 0) or 0

        if mh == home_api:
            if gh > ga: home_wins += 1
            elif gh == ga: draws += 1
            else: away_wins += 1
            scores.append(f"{gh}:{ga}")
        else:
            if ga > gh: home_wins += 1
            elif gh == ga: draws += 1
            else: away_wins += 1
            scores.append(f"{ga}:{gh}")

    return (f"H2H last {len(h2h)}: {home_api.split()[0]} {home_wins}W "
            f"{draws}D {away_wins}L | {', '.join(scores)}")


def get_motivation(position: Optional[int], played: Optional[int], league_code: str) -> str:
    if position is None:
        return ""

    games_left = max(38 - (played or 30), 0)

    if league_code in ("PL", "BL1", "SA", "PD", "FL1"):
        # Топ-4 — ЛЧ, 5-6 — ЛЕ, последние 3 — вылет
        if position <= 4:
            return f"Борьба за ЛЧ (место {position}, {games_left} игр)"
        if position <= 6:
            return f"Зона Лиги Европы (место {position})"
        if position >= 18:
            return f"Борьба за выживание (место {position}!)"
        if position >= 16:
            return f"Опасная зона (место {position})"
        return f"Середина таблицы (место {position})"

    return f"Место {position}"


def upsert_match_facts(conn, match_id, **kwargs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT id FROM match_facts WHERE match_id=?", (match_id,)
    ).fetchone()

    fields = list(kwargs.keys())
    values = list(kwargs.values())

    if existing:
        set_clause = ", ".join(f"{f}=?" for f in fields)
        cur.execute(
            f"UPDATE match_facts SET {set_clause}, updated_at=? WHERE match_id=?",
            values + [now, match_id]
        )
    else:
        fields_str = ", ".join(fields + ["updated_at", "match_id"])
        placeholders = ", ".join("?" * (len(fields) + 2))
        cur.execute(
            f"INSERT INTO match_facts ({fields_str}) VALUES ({placeholders})",
            values + [now, match_id]
        )
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--league", default=None, help="Код лиги: PL, BL1, SA, PD, FL1")
    args = ap.parse_args()

    conn = get_conn()
    ensure_match_facts(conn)
    
    # Diagnostic counters
    total_matches = 0
    matches_with_standings = 0
    matches_with_form = 0
    matches_with_goals = 0
    matches_with_all = 0
    
    # League-level diagnostics
    league_stats = {}
    
    # Missing team mapping diagnostics
    missing_teams = {}

    # Фильтр по лиге если задан
    if args.league:
        target_leagues = {
            k: v for k, v in LEAGUE_MAP.items()
            if v == args.league.upper()
        }
    else:
        target_leagues = LEAGUE_MAP

    # Берём upcoming матчи нужных лиг
    placeholders = ",".join("?" * len(target_leagues))
    matches = conn.execute(f"""
        SELECT id, home_team, away_team, league, match_date
        FROM matches
        WHERE sport='football'
          AND status='upcoming'
          AND odds_home IS NOT NULL
          AND league IN ({placeholders})
        ORDER BY match_date ASC
        LIMIT ?
    """, list(target_leagues.keys()) + [args.limit]).fetchall()

    if not matches:
        print("Нет футбольных матчей для обогащения.")
        print("Лиги ищем:", list(target_leagues.keys()))
        conn.close()
        return

    print(f"Обогащаем {len(matches)} футбольных матчей...\n")

    # Группируем по лиге чтобы загружать standings/results один раз на лигу
    by_league = {}
    for m in matches:
        lc = target_leagues.get(m["league"])
        if lc:
            by_league.setdefault(lc, []).append(m)
            
    # Initialize league stats
    for league_code in by_league.keys():
        league_stats[league_code] = {
            "total": 0,
            "with_standings": 0,
            "with_form": 0,
            "with_goals": 0,
            "with_all": 0
        }

    for league_code, league_matches in by_league.items():
        print(f"\n📊 {league_code} ({len(league_matches)} матчей)")
        print("  Загружаем standings...")
        standings = get_standings(league_code)
        print(f"  → {len(standings)} команд в таблице")
        
        # Print all available team names from the source
        if standings:
            print(f"  📋 Available teams in {league_code} standings ({len(standings)}):")
            team_names = sorted(standings.keys())
            print(f"    {', '.join(team_names)}")

        print("  Загружаем результаты сезона...")
        all_matches = get_finished_matches(league_code)
        print(f"  → {len(all_matches)} завершённых матчей")
        
        # Extract and print all unique team names from season results
        if all_matches:
            teams_in_results = set()
            for match in all_matches:
                home_team = match.get("homeTeam", {}).get("name", "")
                away_team = match.get("awayTeam", {}).get("name", "")
                if home_team:
                    teams_in_results.add(home_team)
                if away_team:
                    teams_in_results.add(away_team)
            
            print(f"  📋 Available teams in {league_code} season results ({len(teams_in_results)}):")
            team_names = sorted(teams_in_results)
            print(f"    {', '.join(team_names)}")

        for m in league_matches:
            home_fonbet = m["home_team"]
            away_fonbet = m["away_team"]
            home_api = resolve_team_name(home_fonbet)
            away_api = resolve_team_name(away_fonbet)

            print(f"\n  {home_fonbet} — {away_fonbet}")

            # Standings
            home_st = find_team_in_standings(standings, home_api)
            away_st = find_team_in_standings(standings, away_api)

            home_pos = home_st["position"] if home_st else None
            away_pos = away_st["position"] if away_st else None
            home_pts = home_st["points"] if home_st else None
            away_pts = away_st["points"] if away_st else None
            home_played = home_st["played"] if home_st else None
            away_played = away_st["played"] if away_st else None

            # Форма последних 5
            home_form, home_scored, home_allowed = get_team_last5(all_matches, home_api)
            away_form, away_scored, away_allowed = get_team_last5(all_matches, away_api)
            
            # Diagnostics for missing form/goals data
            if not home_form or home_scored is None or home_allowed is None:
                print(f"  ⚠️ Missing form/goals data: {league_code} | Fonbet: '{home_fonbet}' → API: '{home_api}'")
            
            if not away_form or away_scored is None or away_allowed is None:
                print(f"  ⚠️ Missing form/goals data: {league_code} | Fonbet: '{away_fonbet}' → API: '{away_api}'")

            # H2H
            h2h = get_h2h_summary(all_matches, home_api, away_api)

            # Мотивация
            home_motiv = get_motivation(home_pos, home_played, league_code)
            away_motiv = get_motivation(away_pos, away_played, league_code)

            # Notes
            notes = []
            if not home_st:
                notes.append(f"Не найден в standings: {home_api}")
                # Track missing team mapping
                print(f"  ⚠️ Missing team in standings: {league_code} | Fonbet: '{home_fonbet}' → API: '{home_api}'")
                missing_teams[home_api] = missing_teams.get(home_api, 0) + 1
            if not away_st:
                notes.append(f"Не найден в standings: {away_api}")
                # Track missing team mapping
                print(f"  ⚠️ Missing team in standings: {league_code} | Fonbet: '{away_fonbet}' → API: '{away_api}'")
                missing_teams[away_api] = missing_teams.get(away_api, 0) + 1
            if len(home_form) < 3:
                notes.append(f"Мало матчей формы {home_fonbet}: {len(home_form)}")
            if not h2h:
                notes.append("H2H пустой")
                
            # Update diagnostics
            total_matches += 1
            league_stats[league_code]["total"] += 1
            
            has_standings = bool(home_st) and bool(away_st)
            has_form = bool(home_form) and bool(away_form) and len(home_form) >= 3 and len(away_form) >= 3
            has_goals = home_scored is not None and away_scored is not None and home_allowed is not None and away_allowed is not None
            
            if has_standings:
                matches_with_standings += 1
                league_stats[league_code]["with_standings"] += 1
            
            if has_form:
                matches_with_form += 1
                league_stats[league_code]["with_form"] += 1
                
            if has_goals:
                matches_with_goals += 1
                league_stats[league_code]["with_goals"] += 1
                
            if has_standings and has_form and has_goals:
                matches_with_all += 1
                league_stats[league_code]["with_all"] += 1

            upsert_match_facts(
                conn,
                m["id"],
                home_form=json.dumps(home_form),
                away_form=json.dumps(away_form),
                home_position=home_pos,
                away_position=away_pos,
                home_points=home_pts,
                away_points=away_pts,
                h2h_summary=h2h,
                home_goals_scored_avg=home_scored,
                away_goals_scored_avg=away_scored,
                home_goals_allowed_avg=home_allowed,
                away_goals_allowed_avg=away_allowed,
                home_motivation=home_motiv,
                away_motivation=away_motiv,
                notes=" | ".join(notes) if notes else "",
                source=f"football-data.org/{league_code}",
            )

            # Print match data with coverage indicators
            form_status = "✅" if has_form else "❌"
            goals_status = "✅" if has_goals else "❌"
            standings_status = "✅" if has_standings else "❌"
            
            print(f"    форма: {home_form} vs {away_form} {form_status}")
            print(f"    голы: {home_scored}/{home_allowed} vs {away_scored}/{away_allowed} {goals_status}")
            print(f"    позиции: {home_pos}/{home_pts} vs {away_pos}/{away_pts} {standings_status}")
            if h2h:
                print(f"    H2H: {h2h}")

    conn.close()
    
    # Print overall diagnostics
    print("\n📊 Data Coverage Summary:")
    print(f"  Total matches processed: {total_matches}")
    if total_matches > 0:
        print(f"  Matches with standings: {matches_with_standings} ({round(matches_with_standings/total_matches*100)}% coverage)")
        print(f"  Matches with form data: {matches_with_form} ({round(matches_with_form/total_matches*100)}% coverage)")
        print(f"  Matches with goals data: {matches_with_goals} ({round(matches_with_goals/total_matches*100)}% coverage)")
        print(f"  Matches with all core data: {matches_with_all} ({round(matches_with_all/total_matches*100)}% coverage)")
    
    # Print league-level diagnostics
    print("\n📊 League-level Coverage:")
    for league_code, stats in league_stats.items():
        if stats["total"] == 0:
            continue
        print(f"  {league_code}:")
        print(f"    Total matches: {stats['total']}")
        if stats["total"] > 0:
            print(f"    With standings: {stats['with_standings']} ({round(stats['with_standings']/stats['total']*100)}%)")
            print(f"    With form data: {stats['with_form']} ({round(stats['with_form']/stats['total']*100)}%)")
            print(f"    With goals data: {stats['with_goals']} ({round(stats['with_goals']/stats['total']*100)}%)")
            print(f"    With all core data: {stats['with_all']} ({round(stats['with_all']/stats['total']*100)}%)")
    
    # Print missing team mappings summary
    if missing_teams:
        print("\n⚠️ Missing Team Mappings Summary:")
        for team_name, count in sorted(missing_teams.items(), key=lambda x: x[1], reverse=True):
            print(f"  {team_name}: {count} occurrences")
        print("\n💡 Add these mappings to TEAM_NAME_MAP:")
        for team_name in sorted(missing_teams.keys()):
            print(f'    "{team_name}": "ACTUAL_NAME_FROM_SOURCE",  # Update with correct name from source')
    
    print("\n✅ Готово!")
    print("Следующий шаг:")
    print("  python agent_handoff_v6.py --dry-run --sport football --limit 20")


if __name__ == "__main__":
    main()
