#!/usr/bin/env python3
"""Тестируем разные способы получить fixtures"""
import os, time, requests, urllib3
urllib3.disable_warnings()

KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE = "https://v3.football.api-sports.io"
HDR = {"x-apisports-key": KEY}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    d = r.json() if r.status_code == 200 else None
    count = len(d.get("response", [])) if d else 0
    print(f"  {r.status_code} | params={params} | found={count}")
    if count > 0:
        f = d["response"][0]
        print(f"    Пример: {f['teams']['home']['name']} vs {f['teams']['away']['name']} | id={f['fixture']['id']}")
    elif d and d.get("errors"):
        print(f"    Errors: {d['errors']}")
    return d

print("=== Тест 1: date=2026-03-15 ===")
get("/fixtures", {"date": "2026-03-15"})
time.sleep(1)

print("\n=== Тест 2: league=39 season=2025 date=2026-03-15 ===")
get("/fixtures", {"league": 39, "season": 2025, "date": "2026-03-15"})
time.sleep(1)

print("\n=== Тест 3: live=all ===")
get("/fixtures", {"live": "all"})
time.sleep(1)

print("\n=== Тест 4: league=235 season=2025 next=5 ===")
get("/fixtures", {"league": 235, "season": 2025, "next": 5})
time.sleep(1)

print("\n=== Тест 5: league=39 season=2025 next=5 ===")
get("/fixtures", {"league": 39, "season": 2025, "next": 5})
time.sleep(1)

print("\n=== Тест 6: league=39 season=2024 last=3 ===")
get("/fixtures", {"league": 39, "season": 2024, "last": 3})
EOF