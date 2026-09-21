#!/usr/bin/env python3
"""Проверяем доступные endpoints API-Hockey"""
import os, requests, urllib3, time, json
urllib3.disable_warnings()

KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE = "https://v1.hockey.api-sports.io"
HDR = {"x-apisports-key": KEY}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    d = r.json() if r.status_code == 200 else {}
    count = len(d.get("response", []))
    errors = d.get("errors", {})
    print(f"  {r.status_code} | found={count} | errors={errors}")
    return d

def dump_first(d):
    resp = d.get("response", [])
    if resp:
        print(json.dumps(resp[0], ensure_ascii=False, indent=2)[:500])

print("1. Standings КХЛ season=2024:")
d = get("/standings", {"league": 35, "season": 2024})
dump_first(d)
time.sleep(1)

print("\n2. Games КХЛ season=2025 date=2026-03-15:")
d = get("/games", {"league": 35, "season": 2025, "date": "2026-03-15"})
dump_first(d)
time.sleep(1)

print("\n3. Games НХЛ season=2024 date=2026-03-15:")
d = get("/games", {"league": 57, "season": 2024, "date": "2026-03-15"})
dump_first(d)
time.sleep(1)

print("\n4. Games КХЛ season=2024 last=3:")
d = get("/games", {"league": 35, "season": 2024, "last": 3})
dump_first(d)
time.sleep(1)

print("\n5. Teams КХЛ season=2024:")
d = get("/teams", {"league": 35, "season": 2024})
resp = d.get("response", [])
for t in resp[:5]:
    print(f"  id={t.get('id')} | {t.get('name')}")

print("\n✅ Готово")
