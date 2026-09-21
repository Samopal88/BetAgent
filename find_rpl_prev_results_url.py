#!/usr/bin/env python3
"""Находим URL страницы результатов РПЛ прошлого сезона"""
import requests
from bs4 import BeautifulSoup

URL = "https://www.the-sports.org/football-soccer-2024-2025-russia-division-1-russian-premier-league-epr134428.html"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9"}

r = requests.get(URL, headers=HEADERS, timeout=20)
soup = BeautifulSoup(r.text, "html.parser")

print("Ищем ссылки на results/eprd...\n")
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)
    if "eprd" in href or "result" in href.lower():
        print(f"  {text!r:30s} → {href}")
