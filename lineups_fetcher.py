#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — lineups_fetcher.py

Тянет составы и травмы с API-Football (api-sports.io).
Обновляет match_facts.lineup_data_available = True когда состав подтверждён.

Источник: https://www.api-football.com/
Бесплатный план: 100 запросов/день

Запуск:
  python lineups_fetcher.py
  python lineups_fetcher.py --dry-run
  python lineups_fetcher.py --limit 10

ENV:
  API_FOOTBALL_KEY=YOUR_KEY
"""

import os, re, json, time, sqlite3, argparse
import requests, urllib3
from datetime import datetime, timedelta
from pathlib import Path

urllib3.disable_warnings()

DB_PATH  = Path(os.getenv("BETAGENT_DB", "betagent.db"))
API_KEY  = os.getenv("API_FOOTBALL_KEY", "")

# api-sports прямой endpoint (не rapidapi)
BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {
    "x-apisports-key": API_KEY,
}

# Маппинг лиг Фонбет → league_id в API-Football
LEAGUE_IDS = {
    "Англия. Премьер-Лига. Сезон 25/26":     39,
    "Германия. Бундеслига. Сезон 25/26":      78,
    "Италия. Серия А. Сезон 25/26":           135,
    "Испания. Примера дивизион. Сезон 25/26": 140,
    "Франция. Лига 1. Сезон 25/26":           61,
    "Россия. Премьер-Лига. Сезон 25/26":      235,
}

SEASON = 2025


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def api_get(path: str, params: dict) -> dict | None:
    if not API_KEY:
        print("❌ API_FOOTBALL_KEY не задан!")
        return None
    try:
        r = requests.get(
            f"{BASE_URL}{path}",
            headers=HEADERS,
            params=params,
            timeout=15,
            verify=False,
        )
        if r.status_code == 429:
            print("  ⏳ Rate limit, ждём 30 сек...")
            time.sleep(30)
            r = requests.get(f"{BASE_URL}{path}", headers=HEADERS,
                             params=params, timeout=15, verify=False)
        if r.status_code == 200:
            return r.json()
        print(f"  ⚠️  API {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  ❌ {e}")
    return None


# Кэш fixtures по дате — загружаем один раз в день
_fixtures_cache: dict = {}

def get_fixtures_by_date(date: str) -> list:
    """Загружает ВСЕ матчи на дату одним запросом (Free план)."""
    if date in _fixtures_cache:
        return _fixtures_cache[date]
    data = api_get("/fixtures", {"date": date})
    time.sleep(1)
    if data:
        fixtures = data.get("response", [])
        _fixtures_cache[date] = fixtures
        print(f"  📅 Загружено {len(fixtures)} fixtures на {date}")
        return fixtures
    return []


def get_fixture_id(league_id: int, home_fonbet: str, away_fonbet: str,
                   match_date: str) -> int | None:
    """Ищем fixture_id среди загруженных матчей на дату."""
    home_api = fonbet_to_api_name(home_fonbet)
    away_api = fonbet_to_api_name(away_fonbet)
    date = match_date[:10]

    # Пробуем дату матча и ±1 день
    for delta in (0, 1, -1):
        from datetime import timedelta as td
        d = (datetime.strptime(date, "%Y-%m-%d") + td(days=delta)).strftime("%Y-%m-%d")
        fixtures = get_fixtures_by_date(d)

        for fix in fixtures:
            # Фильтруем по лиге если возможно
            fix_league = fix.get("league", {}).get("id")
            if fix_league and fix_league != league_id:
                continue
            ht = fix["teams"]["home"]["name"]
            at = fix["teams"]["away"]["name"]
            if fuzzy_match(ht, home_api) and fuzzy_match(at, away_api):
                return fix["fixture"]["id"]

    return None


def fuzzy_match(a: str, b: str) -> bool:
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return True
    # По первому слову
    if a.split()[0] == b.split()[0]:
        return True
    # Вхождение
    if a in b or b in a:
        return True
    return False


def get_lineups(fixture_id: int) -> dict | None:
    """Составы за 1 час до матча."""
    data = api_get("/fixtures/lineups", {"fixture": fixture_id})
    time.sleep(1)
    if not data or not data.get("response"):
        return None
    return data["response"]


def get_injuries(league_id: int) -> list:
    """Травмы и дисквалификации по лиге."""
    data = api_get("/injuries", {
        "league": league_id,
        "season": SEASON,
    })
    time.sleep(1)
    if not data:
        return []
    return data.get("response", [])


def fonbet_to_api_name(fonbet_name: str) -> str:
    """Приближённый маппинг названий команд."""
    mapping = {
        # АПЛ
        "Сандерленд":        "Sunderland",
        "Брайтон":           "Brighton",
        "Бернли":            "Burnley",
        "Борнмут":           "Bournemouth",
        "Челси":             "Chelsea",
        "Ньюкасл":           "Newcastle",
        "Арсенал":           "Arsenal",
        "Эвертон":           "Everton",
        "Вест Хэм":          "West Ham",
        "Манчестер Сити":    "Manchester City",
        "Ноттингем Форест":  "Nottingham Forest",
        "Фулхэм":            "Fulham",
        "Кристал Пэлас":     "Crystal Palace",
        "Лидс Юнайтед":      "Leeds",
        "Манчестер Юнайтед": "Manchester United",
        "Астон Вилла":       "Aston Villa",
        # Бундеслига
        "Байер Леверкузен":  "Bayer Leverkusen",
        "Бавария":           "Bayern Munich",
        "Боруссия Дортмунд": "Borussia Dortmund",
        "Аугсбург":          "Augsburg",
        "Хоффенхайм":        "Hoffenheim",
        "Вольфсбург":        "Wolfsburg",
        "Айнтрахт Франкфурт":"Eintracht Frankfurt",
        "Хайденхайм":        "Heidenheim",
        "Гамбург":           "Hamburg",
        "Кельн":             "FC Koln",
        # Серия А
        "Интер Милан":       "Inter",
        "Аталанта":          "Atalanta",
        "Наполи":            "Napoli",
        "Лечче":             "Lecce",
        "Удинезе":           "Udinese",
        "Ювентус":           "Juventus",
        # Примера
        "Атлетико Мадрид":   "Atletico Madrid",
        "Хетафе":            "Getafe",
        "Реал Мадрид":       "Real Madrid",
        "Жирона":            "Girona",
        "Атлетик Бильбао":   "Athletic Club",
        "Мальорка":          "Mallorca",
        "Эспаньол":          "Espanyol",
        # Лига 1
        "Монако":            "Monaco",
        "Брест":             "Brest",
        "Лорьян":            "Lorient",
        "Ланс":              "Lens",
        "Анже":              "Angers",
        "Ницца":             "Nice",
        # РПЛ
        "Зенит":             "Zenit",
        "Спартак":           "Spartak Moscow",
        "ЦСКА":              "CSKA Moscow",
        "Динамо Москва":     "Dynamo Moscow",
        "Краснодар":         "Krasnodar",
        "Локомотив Москва":  "Lokomotiv Moscow",
        "Ростов":            "Rostov",
        "Рубин":             "Rubin Kazan",
        "Крылья Советов":    "Krylia Sovetov",
        "Ахмат":             "Akhmat Grozny",
        "Оренбург":          "Orenburg",
        "Пари НН":           "Nizhny Novgorod",
        "Балтика":           "Baltika",
        "Сочи":              "Sochi",
        "Акрон":             "Akron Togliatti",
        "Динамо Махачкала":  "Makhachkala",
    }
    return mapping.get(fonbet_name, fonbet_name)


def parse_lineup_facts(lineups_resp: list, home_fonbet: str, away_fonbet: str) -> dict:
    """Извлекаем ключевые данные из составов."""
    facts = {
        "home_lineup_confirmed": False,
        "away_lineup_confirmed": False,
        "home_formation": "",
        "away_formation": "",
        "home_key_players": [],
        "away_key_players": [],
        "notes_lineup": "",
    }

    if not lineups_resp:
        return facts

    for team_data in lineups_resp:
        team_name = team_data.get("team", {}).get("name", "")
        formation = team_data.get("formation", "")
        start_xi = team_data.get("startXI", [])

        players = [p["player"]["name"] for p in start_xi if p.get("player")]
        is_home = fuzzy_match(team_name, fonbet_to_api_name(home_fonbet))

        if is_home:
            facts["home_lineup_confirmed"] = bool(players)
            facts["home_formation"] = formation
            facts["home_key_players"] = players[:5]
        else:
            facts["away_lineup_confirmed"] = bool(players)
            facts["away_formation"] = formation
            facts["away_key_players"] = players[:5]

    return facts


def update_match_facts_lineup(conn, match_id: int, lineup_facts: dict,
                               injuries_home: list, injuries_away: list,
                               dry_run: bool = False) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lineup_available = (lineup_facts["home_lineup_confirmed"] or
                        lineup_facts["away_lineup_confirmed"])

    notes_parts = []
    if lineup_facts.get("home_formation"):
        notes_parts.append(f"Хозяева: {lineup_facts['home_formation']}")
    if lineup_facts.get("away_formation"):
        notes_parts.append(f"Гости: {lineup_facts['away_formation']}")
    if injuries_home:
        inj = ", ".join(f"{i['player']['name']} ({i['player']['reason']})"
                        for i in injuries_home[:3] if i.get("player"))
        notes_parts.append(f"Травмы хозяева: {inj}")
    if injuries_away:
        inj = ", ".join(f"{i['player']['name']} ({i['player']['reason']})"
                        for i in injuries_away[:3] if i.get("player"))
        notes_parts.append(f"Травмы гости: {inj}")

    notes = " | ".join(notes_parts)

    if dry_run:
        print(f"    [DRY-RUN] match_id={match_id} lineup_available={lineup_available}")
        print(f"    notes: {notes[:100]}")
        return

    cur = conn.cursor()
    existing = cur.execute(
        "SELECT id FROM match_facts WHERE match_id=?", (match_id,)
    ).fetchone()

    if existing:
        cur.execute("""
            UPDATE match_facts
            SET lineup_data_available = ?,
                notes = COALESCE(notes || ' | ', '') || ?,
                source = source || '+lineups',
                updated_at = ?
            WHERE match_id = ?
        """, (1 if lineup_available else 0, notes, now, match_id))
    else:
        cur.execute("""
            INSERT INTO match_facts (
                match_id, lineup_data_available, notes, source, updated_at
            ) VALUES (?, ?, ?, 'lineups_fetcher', ?)
        """, (match_id, 1 if lineup_available else 0, notes, now))

    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="football", choices=["football"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if not API_KEY:
        print("❌ Задай переменную окружения:")
        print("   $env:API_FOOTBALL_KEY='YOUR_KEY'")
        return

    conn = get_conn()

    # Добавляем колонку если нет
    try:
        conn.execute("ALTER TABLE match_facts ADD COLUMN lineup_data_available INTEGER DEFAULT 0")
        conn.commit()
        print("  ✅ Добавлена колонка lineup_data_available")
    except Exception:
        pass  # уже есть

    # Берём upcoming матчи с уже заполненными match_facts
    rows = conn.execute("""
        SELECT m.id, m.home_team, m.away_team, m.league, m.match_date
        FROM matches m
        JOIN match_facts mf ON mf.match_id = m.id
        WHERE m.sport = 'football'
          AND m.status = 'upcoming'
          AND m.odds_home IS NOT NULL
        ORDER BY m.match_date ASC
        LIMIT ?
    """, (args.limit,)).fetchall()

    if not rows:
        print("Нет матчей для обновления составов.")
        conn.close()
        return

    print(f"Обновляем составы для {len(rows)} матчей...\n")
    requests_used = 0

    for match in rows:
        home = match["home_team"]
        away = match["away_team"]
        league_name = match["league"]
        league_id = LEAGUE_IDS.get(league_name)
        match_date = match["match_date"][:10]

        print(f"  {home} — {away}")

        if not league_id:
            print(f"    ⚠️  Лига не в маппинге: {league_name}")
            continue

        # Загрузка fixtures по дате — 1 запрос на дату (кэшируется)
        was_cached = match_date in _fixtures_cache
        fixture_id = get_fixture_id(league_id, home, away, match_date)
        if not was_cached:
            requests_used += 1

        if not fixture_id:
            print(f"    ⚠️  fixture_id не найден")
            continue

        print(f"    fixture_id={fixture_id}")

        # Составы (доступны за ~1 час до матча)
        lineups = get_lineups(fixture_id)
        requests_used += 1
        time.sleep(1)

        lineup_facts = parse_lineup_facts(lineups or [], home, away)

        # Травмы — берём из кэша по лиге (1 запрос на лигу в день)
        injuries_data = get_injuries(league_id)
        requests_used += 1
        time.sleep(1)

        injuries_home = [i for i in injuries_data
                         if fuzzy_match(i.get("team", {}).get("name", ""),
                                        fonbet_to_api_name(home))]
        injuries_away = [i for i in injuries_data
                         if fuzzy_match(i.get("team", {}).get("name", ""),
                                        fonbet_to_api_name(away))]

        update_match_facts_lineup(conn, match["id"], lineup_facts,
                                   injuries_home, injuries_away, args.dry_run)

        status = "✅ lineup" if lineup_facts["home_lineup_confirmed"] else "⏳ нет состава"
        print(f"    {status} | {lineup_facts.get('home_formation','')} vs "
              f"{lineup_facts.get('away_formation','')} | "
              f"травмы Д:{len(injuries_home)} Г:{len(injuries_away)}")
        print(f"    Запросов использовано: ~{requests_used}/100")

        if requests_used >= 85:
            print("\n⚠️  Лимит запросов близко (85/100). Останавливаемся.")
            break

        time.sleep(1)

    conn.close()
    print(f"\n✅ Готово. Использовано запросов: {requests_used}")
    print("Теперь запускай:")
    print("  python agent_handoff_v7.py --dry-run --sport football --limit 20")


if __name__ == "__main__":
    main()
