#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_khl_form_v2.py — более устойчивое обновление формы КХЛ

Что делает:
- берёт upcoming-матчи КХЛ из betagent.db
- подтягивает форму команд с khl.ru
- обновляет match_facts:
    home_form / away_form
    home_goals_scored_avg / away_goals_scored_avg
    home_motivation / away_motivation
    source / updated_at

Что улучшено относительно v1:
- requests.Session + Retry
- timeout увеличен
- файловый кэш по командам
- несколько fallback URL по сезонам
- несколько стратегий парсинга формы
- аккуратные логи

Запуск:
    python fetch_khl_form_v2.py
    python fetch_khl_form_v2.py --limit 10
    python fetch_khl_form_v2.py --no-cache
"""

import os
import re
import json
import time
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
CACHE_DIR = Path(os.getenv("BETAGENT_CACHE_DIR", ".cache_khl"))
CACHE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

SEASONS = ["2025_2026", "2024_2025", "2023_2024"]

KHL_TEAM_SLUGS = {
    "СКА": "ska",
    "ЦСКА": "cska",
    "Динамо Москва": "dynamo",
    "Спартак": "spartak",
    "Локомотив Ярославль": "lokomotiv",
    "Северсталь": "severstal",
    "Динамо Минск": "dinamo-minsk",
    "Торпедо НН": "torpedo",
    "Металлург Мг": "metallurg-mg",
    "Салават Юлаев": "salavat-yulaev",
    "Авангард": "avangard",
    "Ак Барс": "ak-bars",
    "Трактор": "traktor",
    "Барыс": "barys",
    "Лада": "lada",
    "Сибирь": "sibir",
    "Нефтехимик": "neftekhimik",
    "Адмирал": "admiral",
    "Амур": "amur",
    "ХК Сочи": "hk-sochi",
    "Шанхай Дрэгонс": "kunlun",
    "Куньлунь Ред Стар": "kunlun",
    "Металлург Магнитогорск": "metallurg-mg",
    "Торпедо": "torpedo",
}

def get_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_khl_slug(team_name: str) -> Optional[str]:
    if team_name in KHL_TEAM_SLUGS:
        return KHL_TEAM_SLUGS[team_name]
    low = team_name.lower().strip()
    for key, slug in KHL_TEAM_SLUGS.items():
        key_low = key.lower()
        if low in key_low or key_low in low:
            return slug
    return None

def cache_path_for(slug: str) -> Path:
    return CACHE_DIR / f"{slug}.json"

def load_cache(slug: str, ttl_hours: int = 12) -> Optional[Dict[str, Any]]:
    path = cache_path_for(slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["cached_at"])
        if datetime.now() - ts <= timedelta(hours=ttl_hours):
            return data
    except Exception:
        return None
    return None

def save_cache(slug: str, payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload["cached_at"] = datetime.now().isoformat()
    cache_path_for(slug).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def fetch_text(session: requests.Session, url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = session.get(url, timeout=timeout, verify=False)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        return None
    return None

def normalize_form(form: List[str]) -> List[str]:
    out = []
    for x in form:
        x = x.upper().strip()
        if x in {"W", "OTW", "SO", "SOW"}:
            out.append("W")
        elif x in {"L", "OTL", "SOL"}:
            out.append("L")
    return out[-5:]

def parse_form_from_html(html: str) -> List[str]:
    """
    Пытается вытащить последние результаты из HTML несколькими способами.
    Возвращает список типа ["W","L","W"].
    """
    candidates = []

    # 1) Классы win/loss на строках / блоках
    for pat in [
        r'class="[^"]*\bwin\b[^"]*"',
        r'class="[^"]*\bloss\b[^"]*"',
        r'class="[^"]*\blose\b[^"]*"',
    ]:
        matches = re.findall(pat, html, flags=re.I)
        for m in matches:
            if "win" in m.lower():
                candidates.append("W")
            else:
                candidates.append("L")

    if len(candidates) >= 3:
        return normalize_form(candidates)

    # 2) Токены в JSON/скриптах
    candidates = re.findall(r'"result"\s*:\s*"(W|L|OTW|OTL|SO|SOW|SOL)"', html, flags=re.I)
    if len(candidates) >= 3:
        return normalize_form(candidates)

    # 3) В текстах рядом со score/status
    candidates = re.findall(r'\b(OTW|OTL|SOW|SOL|W|L)\b', html, flags=re.I)
    if len(candidates) >= 3:
        return normalize_form(candidates)

    # 4) Иногда на khl.ru встречаются слова Победа/Поражение
    words = re.findall(r'(Победа|Поражение)', html, flags=re.I)
    if words:
        converted = ["W" if "побед" in w.lower() else "L" for w in words]
        return normalize_form(converted)

    return []

def fetch_team_results(session: requests.Session, slug: str, use_cache: bool = True) -> List[str]:
    if use_cache:
        cached = load_cache(slug)
        if cached and "form" in cached:
            return cached["form"]

    html = None
    used_url = None
    for season in SEASONS:
        url = f"https://www.khl.ru/clubs/{slug}/{season}/results/"
        html = fetch_text(session, url, timeout=20)
        if html:
            used_url = url
            break

    if not html:
        # слабый fallback
        url = f"https://www.khl.ru/clubs/{slug}/"
        html = fetch_text(session, url, timeout=20)
        used_url = url if html else None

    if not html:
        if use_cache:
            cached = load_cache(slug, ttl_hours=168)
            if cached and "form" in cached:
                return cached["form"]
        return []

    form = parse_form_from_html(html)

    if use_cache:
        save_cache(slug, {"form": form, "source_url": used_url})

    return form

def get_motivation(position: Optional[int], played: Optional[int], total_teams: int = 23) -> str:
    if position is None:
        return ""
    games_left = max(68 - (played or 58), 0)
    playoff_line = 8
    if position <= 3:
        return f"Борьба за топ-3 ({games_left} игр до конца)"
    if position <= playoff_line:
        return f"Закрепление в зоне плей-офф (место {position})"
    if position == playoff_line + 1:
        return f"Борьба за последнее место плей-офф (место {position})"
    if position >= total_teams - 2:
        return f"Низ таблицы, турнирная мотивация ограничена (место {position})"
    return f"Середина/вне плей-офф зоны (место {position})"

def update_match_facts(conn, match_id: int, home_form, away_form, home_avg, away_avg, home_motiv, away_motiv):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE match_facts
        SET home_form = ?,
            away_form = ?,
            home_goals_scored_avg = ?,
            away_goals_scored_avg = ?,
            home_motivation = ?,
            away_motivation = ?,
            source = ?,
            updated_at = ?
        WHERE match_id = ?
    """, (
        json.dumps(home_form, ensure_ascii=False),
        json.dumps(away_form, ensure_ascii=False),
        home_avg,
        away_avg,
        home_motiv,
        away_motiv,
        "khl.ru + standings",
        now,
        match_id,
    ))
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    session = get_session()

    rows = cur.execute("""
        SELECT
            m.id,
            m.home_team,
            m.away_team,
            mf.home_position,
            mf.away_position,
            mf.home_points,
            mf.away_points
        FROM matches m
        JOIN match_facts mf ON mf.match_id = m.id
        WHERE m.sport = 'hockey'
          AND m.status = 'upcoming'
        ORDER BY m.match_date
        LIMIT ?
    """, (args.limit,)).fetchall()

    if not rows:
        print("Нет матчей для обновления. Сначала запусти enricher.py")
        conn.close()
        return

    print(f"Обновляем форму для {len(rows)} матчей КХЛ...\n")

    cache: Dict[str, List[str]] = {}

    for row in rows:
        home = row["home_team"]
        away = row["away_team"]

        print(f"  {home} — {away}")

        # форма хозяев
        if home not in cache:
            slug = get_khl_slug(home)
            if slug:
                form = fetch_team_results(session, slug, use_cache=not args.no_cache)
                cache[home] = form
                time.sleep(0.7)
            else:
                cache[home] = []

        # форма гостей
        if away not in cache:
            slug = get_khl_slug(away)
            if slug:
                form = fetch_team_results(session, slug, use_cache=not args.no_cache)
                cache[away] = form
                time.sleep(0.7)
            else:
                cache[away] = []

        home_form = cache[home]
        away_form = cache[away]

        # средние голы из standings
        home_avg = None
        away_avg = None

        standings_h = cur.execute(
            "SELECT goals_for, goals_against, played FROM standings WHERE league='khl' AND team_name=?",
            (home,)
        ).fetchone()
        standings_a = cur.execute(
            "SELECT goals_for, goals_against, played FROM standings WHERE league='khl' AND team_name=?",
            (away,)
        ).fetchone()

        if standings_h and standings_h["played"]:
            home_avg = round(standings_h["goals_for"] / standings_h["played"], 2)
        if standings_a and standings_a["played"]:
            away_avg = round(standings_a["goals_for"] / standings_a["played"], 2)

        home_played = standings_h["played"] if standings_h else None
        away_played = standings_a["played"] if standings_a else None

        home_motiv = get_motivation(row["home_position"], home_played)
        away_motiv = get_motivation(row["away_position"], away_played)

        update_match_facts(
            conn=conn,
            match_id=row["id"],
            home_form=home_form,
            away_form=away_form,
            home_avg=home_avg,
            away_avg=away_avg,
            home_motiv=home_motiv,
            away_motiv=away_motiv,
        )

        status = f"форма Д:{home_form or '?'} Г:{away_form or '?'}"
        avg_str = f"голов/игру Д:{home_avg} Г:{away_avg}"
        print(f"    ✅ {status} | {avg_str}")

    conn.close()
    print("\n✅ Готово! Теперь запускай:")
    print("  python agent_handoff.py --dry-run --sport hockey --limit 5")

if __name__ == "__main__":
    main()
