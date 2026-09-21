#!/usr/bin/env python3
"""
find_fixtures.py — находим правильные fixture_id для наших лиг

Запуск: python find_fixtures.py
"""
import os, time, requests, urllib3
from datetime import datetime, timedelta
urllib3.disable_warnings()

KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE = "https://v3.football.api-sports.io"
HDR = {"x-apisports-key": KEY}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    if r.status_code == 200:
        return r.json()
    print(f"  ❌ {r.status_code}: {r.text[:100]}")
    return None

today = datetime.now().strftime("%Y-%m-%d")
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

# Лиги и возможные сезоны
LEAGUES = {
    "АПЛ":      (39,  [2024, 2025]),
    "Бундеслига": (78, [2024, 2025]),
    "Серия А":  (135, [2024, 2025]),
    "Примера":  (140, [2024, 2025]),
    "Лига 1":   (61,  [2024, 2025]),
    "РПЛ":      (235, [2024, 2025]),
}

print(f"Ищем матчи на {today} и {tomorrow}\n")
requests_used = 1  # уже потратили на статус

for name, (league_id, seasons) in LEAGUES.items():
    for season in seasons:
        d = get("/fixtures", {
            "league": league_id,
            "season": season,
            "from": today,
            "to": tomorrow,
        })
        requests_used += 1
        time.sleep(0.5)

        if d:
            fixtures = d.get("response", [])
            if fixtures:
                print(f"✅ {name} (league={league_id}, season={season}): {len(fixtures)} матчей")
                for f in fixtures[:3]:
                    home = f["teams"]["home"]["name"]
                    away = f["teams"]["away"]["name"]
                    date = f["fixture"]["date"][:16]
                    fid = f["fixture"]["id"]
                    print(f"   {date} | {home} vs {away} | fixture_id={fid}")
                break
            else:
                print(f"  {name} season={season}: 0 матчей")

print(f"\nЗапросов использовано: {requests_used}/100")
print("\nЕсли нашли fixture_id — запускай:")
print("  python lineups_fetcher.py --dry-run")
