#!/usr/bin/env python3
"""
probe_allsports_api.py

Проверяет AllSportsApi и показывает доступные endpoints.
Запуск после получения ключа:
  $env:ALLSPORTS_API_KEY="YOUR_KEY"
  python probe_allsports_api.py
"""

import os, json, requests, urllib3
urllib3.disable_warnings()

KEY = os.getenv("ALLSPORTS_API_KEY", "")
if not KEY:
    print("❌ Задай: $env:ALLSPORTS_API_KEY='YOUR_KEY'")
    exit(1)

HOST = "allsportsapi2.p.rapidapi.com"
BASE = f"https://{HOST}"
HEADERS = {
    "x-rapidapi-host": HOST,
    "x-rapidapi-key": KEY,
}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HEADERS,
                     params=params or {}, timeout=15, verify=False)
    print(f"  {r.status_code} {path}")
    if r.status_code == 200:
        return r.json()
    print(f"  Body: {r.text[:200]}")
    return None

print("=== Проверяем AllSportsApi ===\n")

# 1. Турниры/лиги
print("1. Футбол — лиги России:")
data = get("/api/football/allLeagues/")
if data:
    leagues = data.get("result", [])
    rpl = [l for l in leagues if "russia" in str(l).lower() or "рпл" in str(l).lower()]
    print(f"   Всего лиг: {len(leagues)}")
    for l in rpl[:5]:
        print(f"   {l}")

# 2. Standings РПЛ (league_id нужно найти)
print("\n2. Standings — ищем РПЛ:")
data = get("/api/football/Standings/", {"leagueId": "1451"})  # примерный ID РПЛ
if data:
    print(json.dumps(data, ensure_ascii=False, indent=2)[:500])

# 3. Lineups — проверяем endpoint
print("\n3. Lineups endpoint:")
data = get("/api/football/lineups/", {"matchId": "1"})
if data:
    print(json.dumps(data, ensure_ascii=False, indent=2)[:300])

# 4. Injuries
print("\n4. Injuries endpoint:")
data = get("/api/football/injuries/", {"leagueId": "1451"})
if data:
    print(json.dumps(data, ensure_ascii=False, indent=2)[:300])

# 5. Fixtures (матчи по дате)
print("\n5. Fixtures по дате:")
data = get("/api/football/Fixtures/", {"from": "2026-03-14", "to": "2026-03-15"})
if data:
    matches = data.get("result", [])
    print(f"   Матчей: {len(matches)}")
    rpl_matches = [m for m in matches if "russia" in str(m).lower() or "premier" in str(m).lower()]
    for m in rpl_matches[:3]:
        print(f"   {m.get('event_home_team')} vs {m.get('event_away_team')} | {m.get('league_name')}")

print("\n✅ Probe завершён")
