#!/usr/bin/env python3
"""Проверяем API-Hockey — ищем КХЛ и НХЛ"""
import os, requests, urllib3, time, json
urllib3.disable_warnings()

KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE = "https://v1.hockey.api-sports.io"
HDR = {"x-apisports-key": KEY}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    d = r.json() if r.status_code == 200 else {}
    remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
    print(f"  {r.status_code} | remaining={remaining} | found={len(d.get('response', []))}")
    if d.get("errors"):
        print(f"  errors: {d['errors']}")
    return d

print("=== API-Hockey probe ===\n")

# 1. Ищем лиги с KHL и NHL
print("1. Все лиги (ищем КХЛ/НХЛ):")
d = get("/leagues")
if d:
    leagues = d.get("response", [])
    for l in leagues:
        name = l.get("name", "")
        lid = l.get("id")
        country = l.get("country", {}).get("name", "")
        if any(x in name.upper() for x in ["KHL", "NHL", "НХЛ", "КХЛ", "KONTINENTAL", "NATIONAL HOCKEY"]):
            print(f"   ✅ id={lid} | {name} | {country}")
time.sleep(1)

# 2. Травмы НХЛ
print("\n2. Травмы НХЛ (league=57, season=2024):")
d = get("/injuries", {"league": 57, "season": 2024})
if d:
    inj = d.get("response", [])
    print(f"   Найдено: {len(inj)}")
    for i in inj[:3]:
        print(f"   {i.get('team',{}).get('name')} | {i.get('player',{}).get('name')} — {i.get('player',{}).get('reason')}")
time.sleep(1)

# 3. Травмы КХЛ
print("\n3. Травмы КХЛ (league=57 — примерный):")
d = get("/injuries", {"league": 27, "season": 2024})
if d:
    inj = d.get("response", [])
    print(f"   Найдено: {len(inj)}")
    for i in inj[:3]:
        print(f"   {i.get('team',{}).get('name')} | {i.get('player',{}).get('name')} — {i.get('player',{}).get('reason')}")

print("\n✅ Probe завершён")
EOF