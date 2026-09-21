#!/usr/bin/env python3
"""
probe_api_football.py — проверяем API-Football (api-sports.io)

Запуск: python probe_api_football.py
"""
import os, json, requests, urllib3
urllib3.disable_warnings()

KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE = "https://v3.football.api-sports.io"
HDR = {"x-apisports-key": KEY}

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15, verify=False)
    print(f"  {r.status_code} {path}")
    if r.status_code == 200:
        d = r.json()
        # Показываем лимиты
        remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
        limit = r.headers.get("x-ratelimit-requests-limit", "?")
        print(f"  Запросов остаток: {remaining}/{limit}")
        return d
    print(f"  Body: {r.text[:200]}")
    return None

import time

print("=== Проверяем API-Football ===\n")

# 1. Статус аккаунта
print("1. Статус аккаунта:")
d = get("/status")
if d:
    sub = d.get("response", {}).get("subscription", {})
    print(f"   План: {sub.get('plan', '?')}")
    print(f"   Запросов сегодня: {d.get('response', {}).get('requests', {}).get('current', '?')}/{d.get('response', {}).get('requests', {}).get('limit_day', '?')}")
time.sleep(1)

# 2. Fixtures РПЛ сегодня
print("\n2. Матчи РПЛ сегодня (league=235):")
d = get("/fixtures", {"league": 235, "season": 2025, "next": 7})
if d:
    fixtures = d.get("response", [])
    print(f"   Найдено: {len(fixtures)}")
    for f in fixtures[:3]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        date = f["fixture"]["date"][:10]
        fid = f["fixture"]["id"]
        print(f"   {date} | {home} vs {away} | id={fid}")
time.sleep(1)

# 3. Fixtures АПЛ
print("\n3. Матчи АПЛ ближайшие (league=39):")
d = get("/fixtures", {"league": 39, "season": 2024, "next": 5})
if d:
    fixtures = d.get("response", [])
    print(f"   Найдено: {len(fixtures)}")
    for f in fixtures[:3]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        date = f["fixture"]["date"][:10]
        fid = f["fixture"]["id"]
        print(f"   {date} | {home} vs {away} | id={fid}")
time.sleep(1)

# 4. Травмы АПЛ
print("\n4. Травмы АПЛ (league=39):")
d = get("/injuries", {"league": 39, "season": 2024})
if d:
    injuries = d.get("response", [])
    print(f"   Найдено травм: {len(injuries)}")
    for inj in injuries[:3]:
        player = inj.get("player", {}).get("name", "?")
        team = inj.get("team", {}).get("name", "?")
        reason = inj.get("player", {}).get("reason", "?")
        print(f"   {team}: {player} — {reason}")
time.sleep(1)

# 5. Lineups для конкретного матча (нужен fixture_id)
print("\n5. Fixtures РПЛ — ищем ID для теста lineups:")
d = get("/fixtures", {"league": 235, "season": 2025, "last": 1})
if d:
    fixtures = d.get("response", [])
    if fixtures:
        fid = fixtures[0]["fixture"]["id"]
        home = fixtures[0]["teams"]["home"]["name"]
        away = fixtures[0]["teams"]["away"]["name"]
        print(f"   Тестируем lineups для: {home} vs {away} (id={fid})")
        time.sleep(1)
        d2 = get("/fixtures/lineups", {"fixture": fid})
        if d2:
            lineups = d2.get("response", [])
            print(f"   Составов найдено: {len(lineups)}")
            for l in lineups[:1]:
                team = l.get("team", {}).get("name", "?")
                formation = l.get("formation", "?")
                players = [p["player"]["name"] for p in l.get("startXI", [])[:3]]
                print(f"   {team}: {formation} | Игроки: {', '.join(players)}")

print("\n✅ Probe завершён")
