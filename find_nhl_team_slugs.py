#!/usr/bin/env python3
"""Собирает правильные slugs всех команд НХЛ"""
import requests, urllib3, re
from bs4 import BeautifulSoup
urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
URL = "https://www.the-sports.org/ice-hockey-national-hockey-league-regular-season-2025-2026-results-eprd137395.html"

r = requests.get(URL, headers=HEADERS, timeout=20, verify=False)
soup = BeautifulSoup(r.text, "html.parser")

# Собираем все identity ссылки
slugs = set()
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "ice-hockey" in href and "identity" in href:
        slugs.add(href)

print(f"Найдено {len(slugs)} ссылок на команды:\n")
for slug in sorted(slugs):
    print(f"  {slug}")
