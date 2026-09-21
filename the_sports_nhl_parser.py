#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
the_sports_nhl_parser.py

Надёжный NHL parser без TheSports standings:
- standings: official NHL API (api-web.nhle.com)
- recent results / upcoming fixtures: official NHL score API
- пишет в betagent.db:
    - standings (league='nhl')
    - matches
    - results_raw

Запуск:
  python the_sports_nhl_parser.py
"""

import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

import requests

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

# Оставляем старое имя/константу для совместимости с пайплайном
DEFAULT_URL = "https://api-web.nhle.com/v1/standings/now"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

LEAGUE = "nhl"
LEAGUE_NAME = "НХЛ. Регулярный сезон"

# Канонические короткие русские названия как в вашей базе/Фонбете
TEAM_MAP = {
    # full EN names
    "Anaheim Ducks": "Анахайм",
    "Boston Bruins": "Бостон",
    "Buffalo Sabres": "Баффало",
    "Calgary Flames": "Калгари",
    "Carolina Hurricanes": "Каролина",
    "Chicago Blackhawks": "Чикаго",
    "Colorado Avalanche": "Колорадо",
    "Columbus Blue Jackets": "Коламбус",
    "Dallas Stars": "Даллас",
    "Detroit Red Wings": "Детройт",
    "Edmonton Oilers": "Эдмонтон",
    "Florida Panthers": "Флорида",
    "Los Angeles Kings": "Лос-Анджелес",
    "Minnesota Wild": "Миннесота",
    "Montreal Canadiens": "Монреаль",
    "Nashville Predators": "Нэшвилл",
    "New Jersey Devils": "Нью-Джерси",
    "New York Islanders": "Айлендерс",
    "New York Rangers": "Рейнджерс",
    "Ottawa Senators": "Оттава",
    "Philadelphia Flyers": "Филадельфия",
    "Pittsburgh Penguins": "Питтсбург",
    "San Jose Sharks": "Сан-Хосе",
    "Seattle Kraken": "Сиэтл",
    "St. Louis Blues": "Сент-Луис",
    "St Louis Blues": "Сент-Луис",
    "Tampa Bay Lightning": "Тампа-Бэй",
    "Toronto Maple Leafs": "Торонто",
    "Utah Hockey Club": "Юта",
    "Utah Mammoth": "Юта",
    "Vancouver Canucks": "Ванкувер",
    "Vegas Golden Knights": "Вегас",
    "Washington Capitals": "Вашингтон",
    "Winnipeg Jets": "Виннипег",

    # abbreviations
    "ANA": "Анахайм",
    "BOS": "Бостон",
    "BUF": "Баффало",
    "CGY": "Калгари",
    "CAR": "Каролина",
    "CHI": "Чикаго",
    "COL": "Колорадо",
    "CBJ": "Коламбус",
    "DAL": "Даллас",
    "DET": "Детройт",
    "EDM": "Эдмонтон",
    "FLA": "Флорида",
    "LAK": "Лос-Анджелес",
    "MIN": "Миннесота",
    "MTL": "Монреаль",
    "NSH": "Нэшвилл",
    "NJD": "Нью-Джерси",
    "NYI": "Айлендерс",
    "NYR": "Рейнджерс",
    "OTT": "Оттава",
    "PHI": "Филадельфия",
    "PIT": "Питтсбург",
    "SJS": "Сан-Хосе",
    "SEA": "Сиэтл",
    "STL": "Сент-Луис",
    "TBL": "Тампа-Бэй",
    "TOR": "Торонто",
    "UTA": "Юта",
    "VAN": "Ванкувер",
    "VGK": "Вегас",
    "WSH": "Вашингтон",
    "WPG": "Виннипег",
    "ARI": "Аризона",

    # legacy / long RU names
    "Анахайм Дакс": "Анахайм",
    "Бостон Брюинз": "Бостон",
    "Баффало Сейбрз": "Баффало",
    "Калгари Флэймз": "Калгари",
    "Каролина Харрикейнз": "Каролина",
    "Чикаго Блэкхокс": "Чикаго",
    "Колорадо Эвеланш": "Колорадо",
    "Коламбус Блю Джекетс": "Коламбус",
    "Даллас Старз": "Даллас",
    "Детройт Ред Уингз": "Детройт",
    "Эдмонтон Ойлерз": "Эдмонтон",
    "Флорида Пантерз": "Флорида",
    "Лос-Анджелес Кингз": "Лос-Анджелес",
    "Миннесота Уайлд": "Миннесота",
    "Монреаль Канадиенс": "Монреаль",
    "Нэшвилл Предаторз": "Нэшвилл",
    "Нью-Джерси Девилз": "Нью-Джерси",
    "Нью-Йорк Айлендерс": "Айлендерс",
    "Нью-Йорк Рейнджерс": "Рейнджерс",
    "Оттава Сенаторз": "Оттава",
    "Филадельфия Флайерз": "Филадельфия",
    "Питтсбург Пингвинз": "Питтсбург",
    "Сан-Хосе Шаркс": "Сан-Хосе",
    "Сиэтл Кракен": "Сиэтл",
    "Сент-Луис Блюз": "Сент-Луис",
    "Тампа-Бэй Лайтнинг": "Тампа-Бэй",
    "Торонто Мэйпл Лифс": "Торонто",
    "Юта Хоккей Клаб": "Юта",
    "Ванкувер Кэнакс": "Ванкувер",
    "Вегас Голден Найтс": "Вегас",
    "Вашингтон Кэпиталз": "Вашингтон",
    "Виннипег Джетс": "Виннипег",

    # already short RU
    "Анахайм": "Анахайм",
    "Бостон": "Бостон",
    "Баффало": "Баффало",
    "Калгари": "Калгари",
    "Каролина": "Каролина",
    "Чикаго": "Чикаго",
    "Колорадо": "Колорадо",
    "Коламбус": "Коламбус",
    "Даллас": "Даллас",
    "Детройт": "Детройт",
    "Эдмонтон": "Эдмонтон",
    "Флорида": "Флорида",
    "Лос-Анджелес": "Лос-Анджелес",
    "Миннесота": "Миннесота",
    "Монреаль": "Монреаль",
    "Нэшвилл": "Нэшвилл",
    "Нью-Джерси": "Нью-Джерси",
    "Айлендерс": "Айлендерс",
    "Рейнджерс": "Рейнджерс",
    "Оттава": "Оттава",
    "Филадельфия": "Филадельфия",
    "Питтсбург": "Питтсбург",
    "Сан-Хосе": "Сан-Хосе",
    "Сиэтл": "Сиэтл",
    "Сент-Луис": "Сент-Луис",
    "Тампа-Бэй": "Тампа-Бэй",
    "Торонто": "Торонто",
    "Юта": "Юта",
    "Ванкувер": "Ванкувер",
    "Вегас": "Вегас",
    "Вашингтон": "Вашингтон",
    "Виннипег": "Виннипег",
}

# clubAbbrev -> short RU
ABBR_MAP = {k: v for k, v in TEAM_MAP.items() if len(k) <= 4 and k.upper() == k}

def normalize_team(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = str(name).strip()
    return TEAM_MAP.get(name, name)

def extract_team_name(team_obj: Any) -> Optional[str]:
    """
    Универсально вытаскивает название команды из разных схем NHL API.
    """
    if team_obj is None:
        return None

    if isinstance(team_obj, str):
        return normalize_team(team_obj)

    if isinstance(team_obj, dict):
        # Сначала аббревиатура — это самый надёжный матчинг к вашей БД
        for abbr_key in ("abbrev", "teamAbbrev", "triCode", "default"):
            val = team_obj.get(abbr_key)
            if isinstance(val, dict):
                val = val.get("default") or val.get("ru")
            if isinstance(val, str) and val in ABBR_MAP:
                return ABBR_MAP[val]

        # placeName + commonName
        place = team_obj.get("placeName")
        common = team_obj.get("commonName")
        if isinstance(place, dict):
            place = place.get("default") or place.get("ru")
        if isinstance(common, dict):
            common = common.get("default") or common.get("ru")
        if place and common:
            combined = f"{place} {common}"
            return normalize_team(combined)

        # teamName/default
        team_name = team_obj.get("teamName")
        if isinstance(team_name, dict):
            team_name = team_name.get("default") or team_name.get("ru")
        if isinstance(team_name, str):
            return normalize_team(team_name)

        # direct localized / english strings
        for key in ("name", "default", "fullName", "teamCommonName", "teamPlaceNameWithPreposition"):
            val = team_obj.get(key)
            if isinstance(val, dict):
                val = val.get("default") or val.get("ru")
            if isinstance(val, str):
                return normalize_team(val)

    return normalize_team(str(team_obj))

def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

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

def parse_standings(_: Optional[object] = None) -> List[Tuple]:
    """
    Standings берём из official NHL API.
    """
    payload = fetch_json("https://api-web.nhle.com/v1/standings/now")
    standings = payload.get("standings") or payload.get("data") or []
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows: List[Tuple] = []
    for item in standings:
        team_name = (
            extract_team_name(item.get("teamName"))
            or extract_team_name(item.get("teamCommonName"))
            or extract_team_name(item.get("teamAbbrev"))
            or extract_team_name(item.get("placeName"))
        )
        if not team_name:
            continue

        position = (
            item.get("leagueSequence")
            or item.get("conferenceSequence")
            or item.get("wildcardSequence")
            or item.get("divisionSequence")
        )
        points = item.get("points")
        played = item.get("gamesPlayed")
        wins = item.get("wins")
        losses = item.get("losses")
        draws = item.get("ties", 0)
        goals_for = item.get("goalFor") or item.get("goalsFor")
        goals_against = item.get("goalAgainst") or item.get("goalsAgainst")

        # В NHL таблице обычно поражения в OT/SO идут отдельно.
        ot_losses = item.get("otLosses") or item.get("shootoutLosses") or 0
        if losses is not None:
            losses = int(losses) + int(ot_losses)

        if goals_for is not None and goals_against is not None:
            goal_diff = int(goals_for) - int(goals_against)
        else:
            goal_diff = None

        rows.append((
            LEAGUE,
            team_name,
            int(position) if position is not None else None,
            int(points) if points is not None else None,
            int(played) if played is not None else None,
            int(wins) if wins is not None else None,
            int(draws) if draws is not None else 0,
            int(losses) if losses is not None else None,
            int(goals_for) if goals_for is not None else None,
            int(goals_against) if goals_against is not None else None,
            int(goal_diff) if goal_diff is not None else None,
            DEFAULT_URL,
            updated_at,
        ))

    rows.sort(key=lambda x: (x[2] is None, x[2], x[1]))

    if len(rows) < 20:
        raise RuntimeError(f"NHL standings parsed too few rows: {len(rows)}")

    return rows

def parse_kickoff_utc(start_time_utc: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not start_time_utc:
        return None, None
    try:
        dt = datetime.fromisoformat(start_time_utc.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return None, None

def game_finished(game: Dict[str, Any]) -> bool:
    state = str(game.get("gameState") or "").upper()
    schedule_state = str(game.get("gameScheduleState") or "").upper()
    return state in {"OFF", "FINAL", "OVER"}

def extract_scores(game: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """
    Возвращает счёт ИМЕННО в основное время (60 минут).

    Для NHL это критично: рынки 1X2/ничья у нас считаются по regulation time,
    а официальный API часто отдаёт финальный счёт с учётом OT/SO.

    Логика:
    1) если есть regulationGoals у команд — берём их;
    2) иначе если матч закончился в OT/SO и есть scoring / summary — считаем только 1-3 периоды;
    3) иначе fallback на обычный score.
    """
    away = game.get("awayTeam") or {}
    home = game.get("homeTeam") or {}

    def _to_int(v):
        try:
            return int(v) if v is not None else None
        except Exception:
            return None

    # 1) Лучший вариант: API уже дал голы именно в основное время
    home_reg = _to_int(home.get("regulationGoals"))
    away_reg = _to_int(away.get("regulationGoals"))
    if home_reg is not None and away_reg is not None:
        return home_reg, away_reg

    last_period_type = str((game.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()

    # 2) Если был OT/SO, пробуем посчитать только первые 3 периода
    if last_period_type in {"OT", "SO"}:
        scoring = game.get("scoring") or game.get("summary") or {}
        periods = scoring.get("periods") if isinstance(scoring, dict) else None
        if isinstance(periods, list) and periods:
            home_total = 0
            away_total = 0
            seen_any = False
            for period in periods:
                num = _to_int(period.get("period") or period.get("periodDescriptor", {}).get("number") or period.get("number"))
                ptype = str(period.get("periodType") or period.get("type") or period.get("periodDescriptor", {}).get("periodType") or "").upper()
                if num is not None and num > 3:
                    continue
                if ptype and ptype not in {"REG", "1ST", "2ND", "3RD"} and num is None:
                    continue

                home_goals = (
                    _to_int(period.get("homeScore")) if period.get("homeScore") is not None else
                    _to_int(period.get("homeGoals")) if period.get("homeGoals") is not None else
                    _to_int((period.get("homeTeam") or {}).get("score"))
                )
                away_goals = (
                    _to_int(period.get("awayScore")) if period.get("awayScore") is not None else
                    _to_int(period.get("awayGoals")) if period.get("awayGoals") is not None else
                    _to_int((period.get("awayTeam") or {}).get("score"))
                )
                if home_goals is None and away_goals is None:
                    continue
                seen_any = True
                home_total += home_goals or 0
                away_total += away_goals or 0

            if seen_any:
                return home_total, away_total

        # Частый случай: API не дал расклад по периодам, но финальный счёт содержит ровно +1 гол победителю в OT/SO
        home_final = _to_int(home.get("score"))
        away_final = _to_int(away.get("score"))
        if home_final is not None and away_final is not None:
            if home_final > away_final:
                return home_final - 1, away_final
            if away_final > home_final:
                return home_final, away_final - 1
            return home_final, away_final

    # 3) Обычный матч в основное время — берём финальный счёт как есть
    home_score = _to_int(home.get("score"))
    away_score = _to_int(away.get("score"))
    return home_score, away_score

def parse_results_and_fixtures(_: Optional[object] = None) -> List[Tuple]:
    """
    Берём окно дат вокруг текущего дня из official NHL score API:
      (match_date, kickoff, home_team, away_team, home_score, away_score, is_finished)
    """
    rows: List[Tuple] = []

    today_utc = datetime.now(timezone.utc).date()
    dates = [today_utc + timedelta(days=d) for d in range(-7, 8)]

    seen = set()

    for d in dates:
        url = f"https://api-web.nhle.com/v1/score/{d.isoformat()}"
        try:
            payload = fetch_json(url)
        except Exception:
            continue

        games = payload.get("games") or []
        for game in games:
            home_team = extract_team_name(game.get("homeTeam"))
            away_team = extract_team_name(game.get("awayTeam"))
            if not home_team or not away_team:
                continue

            match_date, kickoff = parse_kickoff_utc(game.get("startTimeUTC"))
            if not match_date:
                match_date = d.isoformat()
            if not kickoff:
                kickoff = "00:00"

            home_score, away_score = extract_scores(game)
            is_finished = 1 if game_finished(game) else 0

            key = (match_date, home_team, away_team)
            if key in seen:
                continue
            seen.add(key)

            rows.append((
                match_date,
                kickoff,
                home_team,
                away_team,
                home_score,
                away_score,
                is_finished,
            ))

    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
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
    # Оставляем только завершённые матчи — не пишем будущие
    rows = [r for r in rows if r[6] == 1]  # is_finished=1 only
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
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for match_date, kickoff, home_team, away_team, home_score, away_score, is_finished in rows:
        if not match_date:
            continue

        dt = f"{match_date} {kickoff}:00"
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
                    home_score=COALESCE(?, home_score),
                    away_score=COALESCE(?, away_score),
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
    ap.add_argument("--html", default=None, help="не используется, оставлено для совместимости")
    args = ap.parse_args()
    _ = args  # quiet lint

    standings_rows = parse_standings()
    result_rows = parse_results_and_fixtures()

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
        gf = r[8] if r[8] is not None else "-"
        ga = r[9] if r[9] is not None else "-"
        pts = r[3] if r[3] is not None else "-"
        pos = r[2] if r[2] is not None else "?"
        print(f"  {pos}. {r[1]} — {pts} pts, {gf}:{ga}")

if __name__ == "__main__":
    main()
