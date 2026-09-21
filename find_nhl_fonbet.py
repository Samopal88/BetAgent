#!/usr/bin/env python3
"""Ищем НХЛ в Фонбет API"""
import requests, urllib3, json
urllib3.disable_warnings()

API = "https://line-lb54-w.bk6bba-resources.com/ma/events/listBase?lang=ru&scopeMarket=1600"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://fon.bet/"}

r = requests.get(API, headers=HEADERS, timeout=20, verify=False)
data = r.json()
sports = data.get("sports", [])

# Ищем хоккейные сегменты
print("=== ХОККЕЙ — все сегменты ===")
hockey_sport_id = None
for s in sports:
    if s.get("name") == "Хоккей" and s.get("kind") == "sport":
        hockey_sport_id = s["id"]
        break

segments = [s for s in sports if s.get("parentId") == hockey_sport_id and s.get("kind") == "segment"]
for seg in sorted(segments, key=lambda x: x.get("name", "")):
    name = seg.get("name", "")
    if any(x in name.upper() for x in ["НХЛ", "NHL", "АХЛ", "AHL", "ВХЛ", "МХЛ", "SHL", "КХЛ", "ФИН", "ШВЕ", "ЧЕХ"]):
        events = [e for e in data.get("events", []) if e.get("sportId") == seg["id"]]
        print(f"  '{name}' | id={seg['id']} | матчей={len(events)}")
