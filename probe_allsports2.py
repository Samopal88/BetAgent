#!/usr/bin/env python3
"""
probe_allsports2.py — проверяем allsportsapi2 endpoints

Запуск:
  $env:ALLSPORTS_API_KEY="YOUR_KEY"
  python probe_allsports2.py
"""
import os, json, time, requests, urllib3
urllib3.disable_warnings()

KEY  = os.getenv("ALLSPORTS_API_KEY", "")
HOST = "allsportsapi2.p.rapidapi.com"
BASE = f"https://{HOST}"
HDR  = {"x-rapidapi-host": HOST, "x-rapidapi-key": KEY, "Content-Type": "application/json"}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    print(f"  {r.status_code} GET {path}")
    if r.status_code == 200:
        d = r.json()
        print(f"  Keys: {list(d.keys()) if isinstance(d, dict) else 'list len=' + str(len(d))}")
        return d
    print(f"  Body: {r.text[:150]}")
    return None
    time.sleep(0.5)

print("=== AllSportsApi2 probe ===\n")

# Категории (1=футбол, 4=хоккей?)
print("1. Все турниры категории 1 (футбол):")
d = get("/api/tournament/all/category/1")
if d:
    items = d.get("groups") or d.get("tournaments") or d.get("result") or []
    if isinstance(items, list):
        russia = [x for x in items if "russia" in json.dumps(x, ensure_ascii=False).lower()]
        print(f"   Всего: {len(items)} | Россия: {len(russia)}")
        for x in russia[:3]:
            print(f"   {x}")
time.sleep(1)

# Хоккей
print("\n2. Все турниры категории 4 (хоккей?):")
d = get("/api/tournament/all/category/4")
if d:
    items = d.get("groups") or d.get("tournaments") or d.get("result") or []
    if isinstance(items, list):
        khl = [x for x in items if "khl" in json.dumps(x, ensure_ascii=False).lower() or "kontinental" in json.dumps(x, ensure_ascii=False).lower()]
        print(f"   Всего: {len(items)} | КХЛ: {len(khl)}")
        for x in khl[:3]:
            print(f"   {x}")
time.sleep(1)

# Матчи сегодня
print("\n3. Матчи сегодня (football livescore):")
d = get("/api/football/livescore/")
if d:
    matches = d.get("result") or []
    print(f"   Матчей: {len(matches)}")
    for m in matches[:3]:
        print(f"   {m.get('event_home_team')} vs {m.get('event_away_team')} | {m.get('league_name')}")
time.sleep(1)

# Fixtures
print("\n4. Football Fixtures по дате:")
d = get("/api/football/Fixtures/", {"from": "2026-03-14", "to": "2026-03-16", "leagueId": "302"})
if d:
    matches = d.get("result") or []
    print(f"   Матчей: {len(matches)}")
    for m in matches[:3]:
        print(f"   {m}")
time.sleep(1)

# Standings
print("\n5. Standings РПЛ (leagueId=302 — примерный):")
d = get("/api/football/Standings/", {"leagueId": "302"})
if d:
    print(json.dumps(d, ensure_ascii=False, indent=2)[:400])
time.sleep(1)

# Lineups
print("\n6. Match lineups (нужен matchId):")
d = get("/api/football/match/1/lineups/")
if d:
    print(json.dumps(d, ensure_ascii=False, indent=2)[:300])
time.sleep(1)

# Form
print("\n7. Match form:")
d = get("/api/football/match/10060042/form")
if d:
    print(json.dumps(d, ensure_ascii=False, indent=2)[:300])

print("\n✅ Probe завершён")
