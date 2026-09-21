#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — injuries_fetcher.py

Тянет травмы и дисквалификации с API-Football (api-sports.io).
Записывает в match_facts.notes для upcoming матчей.
Запускается утром — 6 запросов на все лиги.

Запуск:
  python injuries_fetcher.py
  python injuries_fetcher.py --dry-run

ENV:
  API_FOOTBALL_KEY=YOUR_KEY
"""

import os, time, sqlite3, argparse
import requests, urllib3
from datetime import datetime
from pathlib import Path

urllib3.disable_warnings()

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
API_KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# league_id → название лиги в Фонбете
LEAGUES = {
    39:  "Англия. Премьер-Лига. Сезон 25/26",
    78:  "Германия. Бундеслига. Сезон 25/26",
    135: "Италия. Серия А. Сезон 25/26",
    140: "Испания. Примера дивизион. Сезон 25/26",
    61:  "Франция. Лига 1. Сезон 25/26",
    235: "Россия. Премьер-Лига. Сезон 25/26",
}

# Сезон для каждой лиги (Free план: только до 2024)
LEAGUE_SEASON = {
    39: 2024, 78: 2024, 135: 2024,
    140: 2024, 61: 2024, 235: 2024,
}

# Маппинг названий команд API → Фонбет
TEAM_MAP = {
    # АПЛ
    "Manchester City":    "Манчестер Сити",
    "Arsenal":            "Арсенал",
    "Liverpool":          "Ливерпуль",
    "Chelsea":            "Челси",
    "Manchester United":  "Манчестер Юнайтед",
    "Tottenham":          "Тоттенхэм",
    "Newcastle":          "Ньюкасл",
    "Aston Villa":        "Астон Вилла",
    "Brighton":           "Брайтон",
    "West Ham":           "Вест Хэм",
    "Fulham":             "Фулхэм",
    "Brentford":          "Брентфорд",
    "Crystal Palace":     "Кристал Пэлас",
    "Everton":            "Эвертон",
    "Nottingham Forest":  "Ноттингем Форест",
    "Wolves":             "Вулверхэмптон",
    "Bournemouth":        "Борнмут",
    "Sunderland":         "Сандерленд",
    "Burnley":            "Бернли",
    "Luton":              "Лутон",
    # Бундеслига
    "Bayern Munich":      "Бавария",
    "Bayer Leverkusen":   "Байер Леверкузен",
    "Borussia Dortmund":  "Боруссия Дортмунд",
    "RB Leipzig":         "РБ Лейпциг",
    "Eintracht Frankfurt":"Айнтрахт Франкфурт",
    "Wolfsburg":          "Вольфсбург",
    "Hoffenheim":         "Хоффенхайм",
    "Augsburg":           "Аугсбург",
    "Heidenheim":         "Хайденхайм",
    "Hamburg":            "Гамбург",
    "FC Koln":            "Кельн",
    # Серия А
    "Inter":              "Интер Милан",
    "AC Milan":           "Милан",
    "Juventus":           "Ювентус",
    "Napoli":             "Наполи",
    "Atalanta":           "Аталанта",
    "Roma":               "Рома",
    "Lazio":              "Лацио",
    "Fiorentina":         "Фиорентина",
    "Udinese":            "Удинезе",
    "Lecce":              "Лечче",
    # Примера
    "Real Madrid":        "Реал Мадрид",
    "Barcelona":          "Барселона",
    "Atletico Madrid":    "Атлетико Мадрид",
    "Athletic Club":      "Атлетик Бильбао",
    "Real Sociedad":      "Реал Сосьедад",
    "Villarreal":         "Вильярреал",
    "Sevilla":            "Севилья",
    "Valencia":           "Валенсия",
    "Getafe":             "Хетафе",
    "Girona":             "Жирона",
    # Лига 1
    "PSG":                "ПСЖ",
    "Monaco":             "Монако",
    "Brest":              "Брест",
    "Nice":               "Ницца",
    "Lens":               "Ланс",
    "Marseille":          "Марсель",
    "Lyon":               "Лион",
    "Lorient":            "Лорьян",
    "Angers":             "Анже",
    # РПЛ
    "Zenit":              "Зенит",
    "Spartak Moscow":     "Спартак",
    "CSKA Moscow":        "ЦСКА",
    "Dynamo Moscow":      "Динамо Москва",
    "Krasnodar":          "Краснодар",
    "Lokomotiv Moscow":   "Локомотив Москва",
    "Rostov":             "Ростов",
    "Rubin Kazan":        "Рубин",
}


def norm_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def api_get(path: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=HEADERS,
                         params=params, timeout=15, verify=False)
        if r.status_code == 200:
            d = r.json()
            if d.get("errors"):
                print(f"  ⚠️  API errors: {d['errors']}")
                return None
            return d
        print(f"  ❌ {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  ❌ {e}")
    return None


def fetch_injuries(league_id: int, season: int) -> list:
    """Тянет травмы и дисквалификации по лиге."""
    data = api_get("/injuries", {"league": league_id, "season": season})
    if not data:
        return []
    return data.get("response", [])


def build_injury_notes(injuries: list, home_team: str, away_team: str) -> str:
    """Формирует строку с травмами для match_facts.notes."""
    home_inj = {}  # player_name → reason (дедупликация)
    away_inj = {}

    for inj in injuries:
        team_api = inj.get("team", {}).get("name", "")
        team_ru = norm_team(team_api)
        player = inj.get("player", {}).get("name", "?")
        reason = inj.get("player", {}).get("reason", "?")

        entry = f"{player} ({reason})"

        if team_ru == home_team or team_api == home_team:
            home_inj[player] = reason
        elif team_ru == away_team or team_api == away_team:
            away_inj[player] = reason

    parts = []
    if home_inj:
        items = [f"{p} ({r})" for p, r in list(home_inj.items())[:5]]
        parts.append(f"Травмы {home_team}: {', '.join(items)}")
    if away_inj:
        items = [f"{p} ({r})" for p, r in list(away_inj.items())[:5]]
        parts.append(f"Травмы {away_team}: {', '.join(items)}")

    return " | ".join(parts)


def update_notes(conn, match_id: int, injury_notes: str, dry_run: bool):
    """Добавляет заметки о травмах в match_facts."""
    if not injury_notes:
        return

    if dry_run:
        print(f"    [DRY-RUN] {injury_notes[:100]}")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id, notes FROM match_facts WHERE match_id=?", (match_id,)
    ).fetchone()

    if existing:
        old_notes = existing["notes"] or ""
        # Убираем старые записи о травмах чтобы не дублировать
        parts = [p for p in old_notes.split(" | ") if "Травмы" not in p]
        parts.append(injury_notes)
        new_notes = " | ".join(filter(None, parts))
        conn.execute("""
            UPDATE match_facts SET notes=?, updated_at=? WHERE match_id=?
        """, (new_notes, now, match_id))
    else:
        conn.execute("""
            INSERT INTO match_facts (match_id, notes, source, updated_at)
            VALUES (?, ?, 'injuries_fetcher', ?)
        """, (match_id, injury_notes, now))

    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not API_KEY:
        print("❌ Задай: $env:API_FOOTBALL_KEY='YOUR_KEY'")
        return

    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    requests_used = 0

    # Загружаем травмы по каждой лиге
    all_injuries: dict[int, list] = {}
    print("Загружаем травмы...\n")

    for league_id, league_name in LEAGUES.items():
        season = LEAGUE_SEASON[league_id]
        print(f"  {league_name}...")
        injuries = fetch_injuries(league_id, season)
        all_injuries[league_id] = injuries
        requests_used += 1
        print(f"    → {len(injuries)} записей")
        time.sleep(1)

    print(f"\nЗапросов использовано: {requests_used}/100")

    # Получаем upcoming матчи
    upcoming = conn.execute("""
        SELECT m.id, m.home_team, m.away_team, m.league
        FROM matches m
        WHERE m.sport = 'football'
          AND m.status = 'upcoming'
          AND m.odds_home IS NOT NULL
        ORDER BY m.match_date ASC
    """).fetchall()

    print(f"\nОбновляем травмы для {len(upcoming)} матчей...\n")
    updated = 0

    for match in upcoming:
        league_name = match["league"]
        league_id = next(
            (lid for lid, lname in LEAGUES.items() if lname == league_name),
            None
        )
        if not league_id:
            continue

        injuries = all_injuries.get(league_id, [])
        home = match["home_team"]
        away = match["away_team"]

        notes = build_injury_notes(injuries, home, away)
        if notes:
            print(f"  {home} — {away}")
            update_notes(conn, match["id"], notes, args.dry_run)
            print(f"    ✅ {notes[:120]}")
            updated += 1

    conn.close()
    print(f"\n✅ Обновлено матчей с травмами: {updated}")
    print("Теперь запускай:")
    print("  python agent_handoff_v7.py --dry-run --sport football --limit 20")


if __name__ == "__main__":
    main()
