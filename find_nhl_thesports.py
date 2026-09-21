#!/usr/bin/env python3
"""Ищем страницу НХЛ на TheSports"""
import requests, urllib3
from bs4 import BeautifulSoup
urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}

# Главная страница хоккея на TheSports
url = "https://www.the-sports.org/ice-hockey-s4.html"
r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
soup = BeautifulSoup(r.text, "html.parser")

print(f"Status: {r.status_code}")
print("\nСсылки на НХЛ:")
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)
    if "nhl" in href.lower() or "national-hockey-league" in href.lower():
        if "2025" in href or "2026" in href or "result" in href:
            print(f"  {text!r:40s} → {href}")
