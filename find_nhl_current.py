#!/usr/bin/env python3
"""Ищем текущий сезон НХЛ на TheSports"""
import requests, urllib3, re
from bs4 import BeautifulSoup
urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}

# Заходим на страницу старого сезона — оттуда найдём ссылку на текущий
url = "https://www.the-sports.org/ice-hockey-national-hockey-league-regular-season-2023-2024-results-eprd131368.html"
r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
soup = BeautifulSoup(r.text, "html.parser")

print("Ссылки на другие сезоны НХЛ:")
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)
    if "national-hockey-league" in href.lower() or "nhl" in href.lower():
        if any(y in href for y in ["2024", "2025", "2026"]):
            print(f"  {text!r:50s} → {href}")

# Также ищем select с сезонами
print("\nSelect options (сезоны):")
for sel in soup.find_all("select"):
    for opt in sel.find_all("option"):
        val = opt.get("value", "")
        txt = opt.get_text(strip=True)
        if "nhl" in val.lower() or "national-hockey" in val.lower():
            print(f"  {txt!r} → {val}")
