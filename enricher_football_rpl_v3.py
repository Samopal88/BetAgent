#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enricher_football_rpl_v3.py

Что исправлено относительно v2:
1) форма и средние голы считаются по НОРМАЛИЗОВАННЫМ именам команд
2) fuzzy-поиск матчей больше не ломает form/goals_avg
3) в notes пишется длина формы:
   - home_form_len
   - away_form_len
4) notes помечает short_form / h2h_empty

Источник:
- TheSports RPL results page (короткий хвост последних туров)

Запуск:
  python enricher_football_rpl_v3.py
"""

import json
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))

# Основная страница — последние туры текущего сезона
URL_MAIN = "https://www.the-sports.org/football-soccer-russia-division-1-russian-premier-league-2025-2026-results-eprd136876.html"

# Прошлый сезон — для H2H и формы (больше матчей в истории)
URL_PREV_SEASON = "https://www.the-sports.org/football-soccer-russia-division-1-russian-premier-league-regular-season-2024-2025-results-eprd134429.html"

# Архивные страницы текущего сезона (пагинация если появится)
ARCHIVE_URLS = []

LEAGUE_KEY = "rpl"
LEAGUE_KEY_PREV = "rpl_prev"  # отдельный ключ чтобы не мешать текущей таблице
MATCHES_LEAGUE_NAMES = {
    "Россия. Премьер-Лига. Сезон 25/26",
    "РПЛ",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

TEAM_MAP = {
    "Zenit St. Petersburg": "Зенит",
    "Zenith Saint-Petersburg": "Зенит",
    "Zenith St. Petersburg": "Зенит",
    "Spartak Moscow": "Спартак",
    "CSKA Moscow": "ЦСКА",
    "Dinamo Moscow": "Динамо Москва",
    "Dynamo Moscow": "Динамо Москва",
    "FC Krasnodar": "Краснодар",
    "Lokomotiv Moscow": "Локомотив Москва",
    "FC Lokomotiv Moscow": "Локомотив Москва",
    "FC Rostov": "Ростов",
    "Rostov": "Ростов",
    "Rubin Kazan": "Рубин",
    "FC Rubin Kazan": "Рубин",
    "Krylya Sovetov Samara": "Крылья Советов",
    "FC Krylya Sovetov Samara": "Крылья Советов",
    "Akhmat Grozny": "Ахмат",
    "FC Akhmat Grozny": "Ахмат",
    "FK Akhmat": "Ахмат",
    "FK Orenburg": "Оренбург",
    "FC Gazovik Orenburg": "Оренбург",
    "Gazovik Orenburg": "Оренбург",
    "Pari Nizhniy Novgorod": "Пари НН",
    "FC Nizhny Novgorod": "Пари НН",
    "Nizhny Novgorod": "Пари НН",
    "Fakel Voronezh": "Факел",
    "FC Baltika Kaliningrad": "Балтика",
    "Baltika Kaliningrad": "Балтика",
    "FC Sochi": "Сочи",
    "Sochi": "Сочи",
    "Dynamo Makhachkala": "Динамо Махачкала",
    "Dinamo Makhachkala": "Динамо Махачкала",
    "FK Makhachkala": "Динамо Махачкала",
    "Acron Togliatti": "Акрон",
    "FK Akron Togliatti": "Акрон",
    "Akron Togliatti": "Акрон",
    "Lokomotiv": "Локомотив Москва",
}

def simplify_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = name.replace("fc ", "").replace("fk ", "")
    name = name.replace("saint-petersburg", "st petersburg")
    name = name.replace("st.", "st")
    name = re.sub(r"[^a-zа-я0-9\s\-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def norm_team(name: str) -> str:
    name = (name or "").strip()
    if name in TEAM_MAP:
        return TEAM_MAP[name]

    simp = simplify_name(name)
    for k, v in TEAM_MAP.items():
        if simplify_name(k) == simp:
            return v

    return name

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_tables(conn):
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS standings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT,
        team_name TEXT,
        position INTEGER,
        points INTEGER,
        played INTEGER,
        wins INTEGER,
        draws INTEGER,
        losses INTEGER,
        goals_for INTEGER,
        goals_against INTEGER,
        goal_diff INTEGER,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS results_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT,
        match_date TEXT,
        kickoff TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        is_finished INTEGER,
        source TEXT,
        updated_at TEXT
    )
    """)
    
    # Create team_injuries table if it doesn't exist
    cur.execute("""
    CREATE TABLE IF NOT EXISTS team_injuries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport TEXT,
        team_name TEXT,
        injuries_count INTEGER,
        key_absences TEXT,
        injuries_notes TEXT,
        source TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS match_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER UNIQUE,
        home_form TEXT,
        away_form TEXT,
        home_position INTEGER,
        away_position INTEGER,
        home_points INTEGER,
        away_points INTEGER,
        h2h_summary TEXT,
        home_goals_scored_avg REAL,
        away_goals_scored_avg REAL,
        home_goals_allowed_avg REAL,
        away_goals_allowed_avg REAL,
        home_motivation TEXT,
        away_motivation TEXT,
        notes TEXT,
        source TEXT,
        updated_at TEXT
    )
    """)
    
    # New table for reusable feature storage
    cur.execute("""
    CREATE TABLE IF NOT EXISTS match_features (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER UNIQUE,
        sport TEXT,
        league TEXT,
        match_date TEXT,
        home_team TEXT,
        away_team TEXT,
        source TEXT,
        created_at TEXT,
        updated_at TEXT,
        
        -- Standings
        home_pos INTEGER,
        away_pos INTEGER,
        home_points INTEGER,
        away_points INTEGER,
        home_goal_diff INTEGER,
        away_goal_diff INTEGER,
        
        -- Recent form
        home_form TEXT,
        away_form TEXT,
        home_points_last5 INTEGER,
        away_points_last5 INTEGER,
        home_scored_last5 REAL,
        home_allowed_last5 REAL,
        away_scored_last5 REAL,
        away_allowed_last5 REAL,
        
        -- Home/away split
        home_home_form TEXT,
        away_away_form TEXT,
        home_home_scored REAL,
        home_home_allowed REAL,
        away_away_scored REAL,
        away_away_allowed REAL,
        
        -- H2H
        h2h_matches_count INTEGER,
        h2h_home_wins INTEGER,
        h2h_draws INTEGER,
        h2h_away_wins INTEGER,
        h2h_home_scored INTEGER,
        h2h_away_scored INTEGER,
        h2h_summary TEXT,
        
        -- Injuries
        injuries_home_count INTEGER,
        injuries_away_count INTEGER,
        key_absences_home TEXT,
        key_absences_away TEXT,
        injuries_notes_home TEXT,
        injuries_notes_away TEXT,
        
        -- Lineup/context
        has_lineups INTEGER,
        lineup_status TEXT,
        hours_to_match INTEGER,
        
        -- Data quality
        has_standings INTEGER,
        has_form INTEGER,
        has_goals INTEGER,
        has_h2h INTEGER,
        has_injuries INTEGER,
        data_completeness_score REAL
    )
    """)
    conn.commit()

def fetch_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 5000:
            return resp.text
        return None
    except Exception as e:
        print(f"  ⚠️  fetch error {url}: {e}")
        return None

def fetch_all_pages(include_prev_season: bool = True) -> tuple:
    """
    Возвращает (current_soups, prev_season_soup)
    current_soups — список soup текущего сезона
    prev_season_soup — soup прошлого сезона (для H2H и доп. формы)
    """
    current_soups = []
    prev_soup = None

    # Главная страница текущего сезона
    html = fetch_html(URL_MAIN)
    if html:
        current_soups.append(BeautifulSoup(html, "html.parser"))
        print(f"  ✅ Текущий сезон: {len(html)} bytes")
    else:
        print(f"  ❌ Не удалось загрузить главную страницу")

    # Архивные страницы текущего сезона
    for url in ARCHIVE_URLS:
        html = fetch_html(url)
        if html:
            current_soups.append(BeautifulSoup(html, "html.parser"))
            print(f"  ✅ Архив: {len(html)} bytes")

    # Прошлый сезон
    if include_prev_season:
        import time
        time.sleep(1)  # вежливая пауза
        html = fetch_html(URL_PREV_SEASON)
        if html:
            prev_soup = BeautifulSoup(html, "html.parser")
            print(f"  ✅ Прошлый сезон: {len(html)} bytes")
        else:
            print(f"  ℹ️  Прошлый сезон недоступен")

    return current_soups, prev_soup

MONTHS = {
    'January':'01','February':'02','March':'03','April':'04','May':'05','June':'06',
    'July':'07','August':'08','September':'09','October':'10','November':'11','December':'12'
}

def parse_date_fallback(text: str) -> Optional[str]:
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip())
    if not m:
        return None
    d, mon, y = m.groups()
    mm = MONTHS.get(mon)
    if not mm:
        return None
    return f"{y}-{mm}-{int(d):02d}"

def find_general_standings_table(soup: BeautifulSoup):
    anchor = soup.find(["h3", "h4"], string=re.compile("General classification", re.I))
    if anchor:
        nxt = anchor.find_next("table")
        if nxt:
            return nxt

    for table in soup.find_all("table", class_="table-style-2"):
        txt = table.get_text(" ", strip=True)
        if all(tok in txt for tok in ["Team", "Pts", "MP", "GF", "GA"]):
            return table
    return None

def parse_standings(soup: BeautifulSoup):
    rows_out = []
    table = find_general_standings_table(soup)
    if not table:
        return rows_out

    trs = table.find_all("tr")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for tr in trs[1:]:
        cols = tr.find_all("td")
        if len(cols) < 10:
            continue
        try:
            position = int(cols[0].get_text(strip=True))
            team_name = norm_team(cols[1].get_text(" ", strip=True).replace("(RUS)", "").strip())
            points = int(cols[2].get_text(strip=True))
            played = int(cols[3].get_text(strip=True))
            wins = int(cols[4].get_text(strip=True))
            draws = int(cols[5].get_text(strip=True))
            losses = int(cols[6].get_text(strip=True))
            goals_for = int(cols[7].get_text(strip=True))
            goals_against = int(cols[8].get_text(strip=True))
            gd_text = cols[9].get_text(strip=True).replace("+", "")
            goal_diff = int(gd_text)
        except Exception:
            continue

        rows_out.append((
            LEAGUE_KEY, team_name, position, points, played, wins, draws, losses,
            goals_for, goals_against, goal_diff, now
        ))
    return rows_out

def parse_results_and_fixtures(soup: BeautifulSoup):
    out = []
    current_date = None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for tr in soup.find_all("tr"):
        # Формат 1: дата в h6.daterenc (текущий сезон)
        h6 = tr.find("h6", class_="daterenc")
        if h6:
            current_date = parse_date_fallback(h6.get_text(" ", strip=True))
            continue

        cols = tr.find_all("td")
        if not cols:
            continue

        # Формат 2: дата в первой ячейке таблицы (прошлый сезон)
        # row1: ['24 May 2025'] — одна ячейка с датой
        if len(cols) == 1:
            date_candidate = parse_date_fallback(cols[0].get_text(" ", strip=True))
            if date_candidate:
                current_date = date_candidate
            continue

        if len(cols) < 4 or not current_date:
            continue

        time_txt = cols[0].get_text(" ", strip=True)
        home_team = norm_team(cols[1].get_text(" ", strip=True).replace("(RUS)", "").strip())
        score_txt = cols[2].get_text(" ", strip=True)
        away_team = norm_team(cols[3].get_text(" ", strip=True).replace("(RUS)", "").strip())

        if not home_team or not away_team:
            continue

        kickoff = f"{current_date} {time_txt}" if re.match(r"^\d{1,2}h\d{2}$", time_txt) else current_date

        if re.search(r"\d+\s*-\s*\d+", score_txt):
            m = re.search(r"(\d+)\s*-\s*(\d+)", score_txt)
            hs, aas = int(m.group(1)), int(m.group(2))
            is_finished = 1
        elif score_txt.strip() == "-":
            hs, aas = None, None
            is_finished = 0
        else:
            continue

        out.append((
            LEAGUE_KEY, current_date, kickoff, home_team, away_team,
            hs, aas, is_finished, "TheSports RPL", now
        ))

    return out

def save_standings(conn, rows):
    cur = conn.cursor()
    cur.execute("DELETE FROM standings WHERE league=?", (LEAGUE_KEY,))
    cur.executemany("""
        INSERT INTO standings (
            league, team_name, position, points, played, wins, draws, losses,
            goals_for, goals_against, goal_diff, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

def save_results_raw(conn, rows, league_key: str = LEAGUE_KEY):
    if not rows:
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM results_raw WHERE league=?", (league_key,))
    cur.executemany("""
        INSERT INTO results_raw (
            league, match_date, kickoff, home_team, away_team,
            home_score, away_score, is_finished, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

def get_upcoming_fonbet_rpl_matches(conn):
    placeholders = ",".join(["?"] * len(MATCHES_LEAGUE_NAMES))
    return conn.execute(f"""
        SELECT id, home_team, away_team, match_date
        FROM matches
        WHERE sport='football'
          AND status='upcoming'
          AND league IN ({placeholders})
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
        ORDER BY match_date ASC
    """, tuple(MATCHES_LEAGUE_NAMES)).fetchall()

def get_team_standing(conn, team_name: str):
    team_name = norm_team(team_name)
    row = conn.execute("""
        SELECT * FROM standings
        WHERE league=? AND team_name=?
        LIMIT 1
    """, (LEAGUE_KEY, team_name)).fetchone()
    if row:
        return row

    simp = simplify_name(team_name)
    rows = conn.execute("SELECT * FROM standings WHERE league=?", (LEAGUE_KEY,)).fetchall()
    for r in rows:
        if simplify_name(r["team_name"]) == simp:
            return r
    return None

def get_last_results(conn, team_name: str, n: int = 5):
    """Ищем последние n матчей — сначала текущий сезон, потом прошлый"""
    team_name = norm_team(team_name)
    simp = simplify_name(team_name)

    results = []
    for league_key in (LEAGUE_KEY, LEAGUE_KEY_PREV):
        rows = conn.execute("""
            SELECT match_date, kickoff, home_team, away_team, home_score, away_score
            FROM results_raw
            WHERE league=? AND is_finished=1
              AND (home_team=? OR away_team=?)
            ORDER BY match_date DESC, kickoff DESC
            LIMIT ?
        """, (league_key, team_name, team_name, n)).fetchall()

        if not rows:
            # Fuzzy
            all_rows = conn.execute("""
                SELECT match_date, kickoff, home_team, away_team, home_score, away_score
                FROM results_raw
                WHERE league=? AND is_finished=1
                ORDER BY match_date DESC
            """, (league_key,)).fetchall()
            for r in all_rows:
                if (simplify_name(norm_team(r["home_team"])) == simp or
                        simplify_name(norm_team(r["away_team"])) == simp):
                    rows = list(rows) + [r]

        results.extend(rows)
        if len(results) >= n:
            break

    return results[:n]


def get_h2h(conn, home_team: str, away_team: str, n: int = 5):
    """Ищем H2H в обоих сезонах"""
    home_team = norm_team(home_team)
    away_team = norm_team(away_team)
    hs = simplify_name(home_team)
    aas = simplify_name(away_team)

    results = []
    for league_key in (LEAGUE_KEY, LEAGUE_KEY_PREV):
        rows = conn.execute("""
            SELECT match_date, home_team, away_team, home_score, away_score
            FROM results_raw
            WHERE league=? AND is_finished=1
              AND ((home_team=? AND away_team=?) OR (home_team=? AND away_team=?))
            ORDER BY match_date DESC
            LIMIT ?
        """, (league_key, home_team, away_team, away_team, home_team, n)).fetchall()

        if not rows:
            all_rows = conn.execute("""
                SELECT match_date, home_team, away_team, home_score, away_score
                FROM results_raw
                WHERE league=? AND is_finished=1
                ORDER BY match_date DESC
            """, (league_key,)).fetchall()
            for r in all_rows:
                rh = simplify_name(norm_team(r["home_team"]))
                ra = simplify_name(norm_team(r["away_team"]))
                if (rh == hs and ra == aas) or (rh == aas and ra == hs):
                    rows = list(rows) + [r]

        results.extend(rows)
        if len(results) >= n:
            break

    return results[:n]


def form_from_results(team_name: str, rows):
    team_name = norm_team(team_name)
    team_simp = simplify_name(team_name)
    form = []

    for r in rows:
        home = norm_team(r["home_team"])
        away = norm_team(r["away_team"])
        home_simp = simplify_name(home)
        away_simp = simplify_name(away)

        if home_simp == team_simp:
            if r["home_score"] > r["away_score"]:
                form.append("W")
            elif r["home_score"] == r["away_score"]:
                form.append("D")
            else:
                form.append("L")
        elif away_simp == team_simp:
            if r["away_score"] > r["home_score"]:
                form.append("W")
            elif r["away_score"] == r["home_score"]:
                form.append("D")
            else:
                form.append("L")
    return form

def goals_avg_from_results(team_name: str, rows):
    team_name = norm_team(team_name)
    team_simp = simplify_name(team_name)
    scored, allowed = [], []

    for r in rows:
        home = norm_team(r["home_team"])
        away = norm_team(r["away_team"])
        home_simp = simplify_name(home)
        away_simp = simplify_name(away)

        if home_simp == team_simp:
            scored.append(r["home_score"])
            allowed.append(r["away_score"])
        elif away_simp == team_simp:
            scored.append(r["away_score"])
            allowed.append(r["home_score"])

    if not scored:
        return None, None
    return round(sum(scored)/len(scored), 2), round(sum(allowed)/len(allowed), 2)

def build_h2h_summary(home_team: str, away_team: str, rows):
    if not rows:
        return ""
    home_team = norm_team(home_team)
    away_team = norm_team(away_team)
    hs = simplify_name(home_team)
    aas = simplify_name(away_team)

    home_wins = away_wins = draws = 0
    scores = []
    for r in rows:
        rh = simplify_name(norm_team(r["home_team"]))
        ra = simplify_name(norm_team(r["away_team"]))
        if rh == hs:
            h, a = r["home_score"], r["away_score"]
        elif ra == hs:
            h, a = r["away_score"], r["home_score"]
        else:
            continue

        if h > a:
            home_wins += 1
        elif h < a:
            away_wins += 1
        else:
            draws += 1
        scores.append(f"{h}:{a}")
    return f"H2H last {len(rows)}: {home_team} {home_wins}W, {away_team} {away_wins}W, draws {draws} | scores: {', '.join(scores)}"

def get_motivation(position: Optional[int], points: Optional[int]) -> str:
    if position is None:
        return ""
    if position <= 3:
        return f"Борьба за верх таблицы/еврокубки (место {position})"
    if position <= 6:
        return f"Верхняя половина таблицы, важны очки за еврозону/топ-6 (место {position})"
    if position <= 12:
        return f"Середина таблицы, мотивация зависит от плотности очков (место {position})"
    return f"Низ таблицы, важна борьба за выживание/выход из опасной зоны (место {position})"

def get_team_injuries(conn, team_name: str) -> dict:
    """
    Fetch injury/absence data for a team from the database.
    Returns a dict with count, key absences and notes.
    """
    team_name = norm_team(team_name)
    simp = simplify_name(team_name)
    
    # Try to find injury data in the database
    try:
        # First try exact match
        row = conn.execute("""
            SELECT injuries_count, key_absences, injuries_notes 
            FROM team_injuries 
            WHERE team_name = ? AND sport = 'football'
            ORDER BY updated_at DESC LIMIT 1
        """, (team_name,)).fetchone()
        
        # If not found, try fuzzy match
        if not row:
            rows = conn.execute("""
                SELECT team_name, injuries_count, key_absences, injuries_notes 
                FROM team_injuries 
                WHERE sport = 'football'
                ORDER BY updated_at DESC
            """).fetchall()
            
            for r in rows:
                if simplify_name(r["team_name"]) == simp:
                    row = r
                    break
        
        if row:
            return {
                "count": row["injuries_count"],
                "key_absences": row["key_absences"],
                "notes": row["injuries_notes"]
            }
    except sqlite3.OperationalError:
        # Table might not exist yet
        pass
    
    return {"count": None, "key_absences": None, "notes": None}

def get_match_injuries_from_facts(conn, match_id: int) -> dict:
    """
    Extract injury data from match_facts for a specific match.
    Returns a dict with home and away injury information.
    """
    try:
        row = conn.execute("""
            SELECT notes, source
            FROM match_facts
            WHERE match_id = ?
        """, (match_id,)).fetchone()
        
        if not row:
            return {
                "home_count": None, "away_count": None,
                "home_key_absences": None, "away_key_absences": None,
                "home_notes": None, "away_notes": None,
                "has_injury_data": False
            }
        
        notes = row["notes"] or ""
        source = row["source"] or ""
        
        # Check if there's any injury-related content
        has_injury_data = False
        home_notes = away_notes = None
        home_count = away_count = None
        home_key_absences = away_key_absences = None
        
        # Look for injury patterns in notes or source
        injury_keywords = ["травм", "injury", "absent", "отсутств", "дисквал", "suspension"]
        
        # Extract home team injuries
        home_injury_pattern = re.search(r"home[_\s]*(team)?[_\s]*injur(y|ies)[_\s]*[:=]([^|;]+)", 
                                       notes + " " + source, re.I)
        if home_injury_pattern:
            home_notes = home_injury_pattern.group(3).strip()
            has_injury_data = True
            
            # Try to extract count if it's a number
            count_match = re.search(r"(\d+)", home_notes)
            if count_match:
                try:
                    home_count = int(count_match.group(1))
                except ValueError:
                    pass
        
        # Extract away team injuries
        away_injury_pattern = re.search(r"away[_\s]*(team)?[_\s]*injur(y|ies)[_\s]*[:=]([^|;]+)", 
                                       notes + " " + source, re.I)
        if away_injury_pattern:
            away_notes = away_injury_pattern.group(3).strip()
            has_injury_data = True
            
            # Try to extract count if it's a number
            count_match = re.search(r"(\d+)", away_notes)
            if count_match:
                try:
                    away_count = int(count_match.group(1))
                except ValueError:
                    pass
        
        # If no structured pattern found, check for general injury keywords
        if not has_injury_data:
            for keyword in injury_keywords:
                if keyword in notes.lower() or keyword in source.lower():
                    has_injury_data = True
                    if not home_notes:
                        home_notes = "Injury data present but unstructured"
                    if not away_notes:
                        away_notes = "Injury data present but unstructured"
                    break
        
        return {
            "home_count": home_count,
            "away_count": away_count,
            "home_key_absences": None,  # Not parsed from current format
            "away_key_absences": None,  # Not parsed from current format
            "home_notes": home_notes,
            "away_notes": away_notes,
            "has_injury_data": has_injury_data
        }
    except Exception as e:
        print(f"  ⚠️  Error extracting injuries from match_facts: {e}")
        return {
            "home_count": None, "away_count": None,
            "home_key_absences": None, "away_key_absences": None,
            "home_notes": None, "away_notes": None,
            "has_injury_data": False
        }

def upsert_match_fact(conn, match_id: int, payload: dict):
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_facts WHERE match_id=?", (match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    values = (
        json.dumps(payload["home_form"], ensure_ascii=False),
        json.dumps(payload["away_form"], ensure_ascii=False),
        payload["home_position"],
        payload["away_position"],
        payload["home_points"],
        payload["away_points"],
        payload["h2h_summary"],
        payload["home_goals_scored_avg"],
        payload["away_goals_scored_avg"],
        payload["home_goals_allowed_avg"],
        payload["away_goals_allowed_avg"],
        payload["home_motivation"],
        payload["away_motivation"],
        payload["notes"],
        "TheSports RPL enricher v3",
        now,
        match_id,
    )

    if existing:
        cur.execute("""
            UPDATE match_facts
            SET home_form=?,
                away_form=?,
                home_position=?,
                away_position=?,
                home_points=?,
                away_points=?,
                h2h_summary=?,
                home_goals_scored_avg=?,
                away_goals_scored_avg=?,
                home_goals_allowed_avg=?,
                away_goals_allowed_avg=?,
                home_motivation=?,
                away_motivation=?,
                notes=?,
                source=?,
                updated_at=?
            WHERE match_id=?
        """, values)
    else:
        cur.execute("""
            INSERT INTO match_facts (
                home_form, away_form, home_position, away_position,
                home_points, away_points, h2h_summary,
                home_goals_scored_avg, away_goals_scored_avg,
                home_goals_allowed_avg, away_goals_allowed_avg,
                home_motivation, away_motivation, notes,
                source, updated_at, match_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
    conn.commit()

def upsert_match_features(conn, match_id: int, match_date: str, home_team: str, away_team: str, features: dict):
    """
    Save or update match features in the new reusable storage layer
    """
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_features WHERE match_id=?", (match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Calculate data completeness score (0-100)
    has_standings = 1 if features.get("home_pos") is not None else 0
    has_form = 1 if features.get("home_form") else 0
    has_goals = 1 if features.get("home_scored_last5") is not None else 0
    has_h2h = 1 if features.get("h2h_matches_count", 0) > 0 else 0
    has_injuries = 1 if (features.get("injuries_home_count") is not None or 
                         features.get("injuries_away_count") is not None or
                         features.get("has_injury_data", False) or
                         features.get("injuries_notes_home") is not None or
                         features.get("injuries_notes_away") is not None) else 0
    
    # Weight factors for completeness score
    weights = {"standings": 0.25, "form": 0.25, "goals": 0.2, "h2h": 0.2, "injuries": 0.1}
    completeness_score = round(100 * (
        weights["standings"] * has_standings +
        weights["form"] * has_form +
        weights["goals"] * has_goals +
        weights["h2h"] * has_h2h +
        weights["injuries"] * has_injuries
    ), 1)
    
    # Prepare values for insert/update
    values = (
        "football",                          # sport
        "rpl",                               # league
        match_date,                          # match_date
        home_team,                           # home_team
        away_team,                           # away_team
        "TheSports RPL enricher v3",         # source
        now if not existing else None,       # created_at (only for new records)
        now,                                 # updated_at
        
        # Standings
        features.get("home_pos"),
        features.get("away_pos"),
        features.get("home_points"),
        features.get("away_points"),
        features.get("home_goal_diff"),
        features.get("away_goal_diff"),
        
        # Recent form
        json.dumps(features.get("home_form", []), ensure_ascii=False),
        json.dumps(features.get("away_form", []), ensure_ascii=False),
        features.get("home_points_last5"),
        features.get("away_points_last5"),
        features.get("home_scored_last5"),
        features.get("home_allowed_last5"),
        features.get("away_scored_last5"),
        features.get("away_allowed_last5"),
        
        # Home/away split
        json.dumps(features.get("home_home_form", []), ensure_ascii=False),
        json.dumps(features.get("away_away_form", []), ensure_ascii=False),
        features.get("home_home_scored"),
        features.get("home_home_allowed"),
        features.get("away_away_scored"),
        features.get("away_away_allowed"),
        
        # H2H
        features.get("h2h_matches_count"),
        features.get("h2h_home_wins"),
        features.get("h2h_draws"),
        features.get("h2h_away_wins"),
        features.get("h2h_home_scored"),
        features.get("h2h_away_scored"),
        features.get("h2h_summary"),
        
        # Injuries
        features.get("injuries_home_count"),
        features.get("injuries_away_count"),
        features.get("key_absences_home"),
        features.get("key_absences_away"),
        features.get("injuries_notes_home"),
        features.get("injuries_notes_away"),
        
        # Lineup/context (not implemented yet)
        0,     # has_lineups
        None,  # lineup_status
        None,  # hours_to_match
        
        # Data quality
        has_standings,
        has_form,
        has_goals,
        has_h2h,
        has_injuries,
        completeness_score,
        
        match_id,  # For WHERE clause
    )
    
    if existing:
        cur.execute("""
            UPDATE match_features
            SET sport=?, league=?, match_date=?, home_team=?, away_team=?, source=?, 
                created_at=COALESCE(?, created_at), updated_at=?,
                home_pos=?, away_pos=?, home_points=?, away_points=?, 
                home_goal_diff=?, away_goal_diff=?,
                home_form=?, away_form=?, home_points_last5=?, away_points_last5=?,
                home_scored_last5=?, home_allowed_last5=?, away_scored_last5=?, away_allowed_last5=?,
                home_home_form=?, away_away_form=?, home_home_scored=?, home_home_allowed=?,
                away_away_scored=?, away_away_allowed=?,
                h2h_matches_count=?, h2h_home_wins=?, h2h_draws=?, h2h_away_wins=?,
                h2h_home_scored=?, h2h_away_scored=?, h2h_summary=?,
                injuries_home_count=?, injuries_away_count=?, key_absences_home=?, key_absences_away=?,
                injuries_notes_home=?, injuries_notes_away=?,
                has_lineups=?, lineup_status=?, hours_to_match=?,
                has_standings=?, has_form=?, has_goals=?, has_h2h=?, has_injuries=?,
                data_completeness_score=?
            WHERE match_id=?
        """, values)
    else:
        # Create dynamic placeholders based on the number of values
        placeholders = ", ".join(["?"] * len(values))
        
        cur.execute(f"""
            INSERT INTO match_features (
                sport, league, match_date, home_team, away_team, source, created_at, updated_at,
                home_pos, away_pos, home_points, away_points, home_goal_diff, away_goal_diff,
                home_form, away_form, home_points_last5, away_points_last5,
                home_scored_last5, home_allowed_last5, away_scored_last5, away_allowed_last5,
                home_home_form, away_away_form, home_home_scored, home_home_allowed,
                away_away_scored, away_away_allowed,
                h2h_matches_count, h2h_home_wins, h2h_draws, h2h_away_wins,
                h2h_home_scored, h2h_away_scored, h2h_summary,
                injuries_home_count, injuries_away_count, key_absences_home, key_absences_away,
                injuries_notes_home, injuries_notes_away,
                has_lineups, lineup_status, hours_to_match,
                has_standings, has_form, has_goals, has_h2h, has_injuries,
                data_completeness_score, match_id
            ) VALUES ({placeholders})
        """, values)
    conn.commit()
    
    return {
        "has_standings": has_standings,
        "has_form": has_form,
        "has_goals": has_goals,
        "has_h2h": has_h2h,
        "has_injuries": has_injuries,
        "data_completeness_score": completeness_score
    }

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-archive", action="store_true", help="Не загружать прошлый сезон")
    ap.add_argument("--dry-run", action="store_true", help="Только показать, не писать в БД")
    args = ap.parse_args()

    conn = get_conn()
    ensure_tables(conn)

    print("Загружаем TheSports RPL...")
    current_soups, prev_soup = fetch_all_pages(include_prev_season=not args.no_archive)

    if not current_soups:
        print("❌ Не удалось загрузить ни одну страницу")
        conn.close()
        return

    # Standings только из текущего сезона
    standings_rows = parse_standings(current_soups[0])

    # Результаты текущего сезона — дедупликация
    seen = set()
    all_results = []
    for soup in current_soups:
        for r in parse_results_and_fixtures(soup):
            key = (r[2], r[3], r[4])
            if key not in seen:
                seen.add(key)
                all_results.append(r)

    # Результаты прошлого сезона (только finished, для формы и H2H)
    prev_results = []
    if prev_soup:
        for r in parse_results_and_fixtures(prev_soup):
            if r[8] == 1:  # только finished
                prev_results.append(r)
        print(f"  → Прошлый сезон: {len(prev_results)} завершённых матчей")

    if not args.dry_run:
        save_standings(conn, standings_rows)
        save_results_raw(conn, all_results, LEAGUE_KEY)
        if prev_results:
            save_results_raw(conn, prev_results, LEAGUE_KEY_PREV)

    print(f"✅ Standings: {len(standings_rows)}")
    print(f"✅ Results/fixtures: {len(all_results)}")
    print(f"   finished: {sum(1 for r in all_results if r[7] == 1)}")
    print(f"   upcoming: {sum(1 for r in all_results if r[7] == 0)}")

    if args.dry_run:
        print("[DRY-RUN] В БД не пишем")
        conn.close()
        return

    upcoming = get_upcoming_fonbet_rpl_matches(conn)
    print(f"\nОбновляем match_facts для upcoming Fonbet RPL матчей: {len(upcoming)}")

    synced = 0
    for m in upcoming:
        home = norm_team(m["home_team"])
        away = norm_team(m["away_team"])

        home_st = get_team_standing(conn, home)
        away_st = get_team_standing(conn, away)

        home_results = get_last_results(conn, home, 5)
        away_results = get_last_results(conn, away, 5)
        h2h_rows = get_h2h(conn, home, away, 5)

        home_form = form_from_results(home, home_results)
        away_form = form_from_results(away, away_results)
        home_scored_avg, home_allowed_avg = goals_avg_from_results(home, home_results)
        away_scored_avg, away_allowed_avg = goals_avg_from_results(away, away_results)

        # Fallback: если нет результатов — берём средние голы из standings (сезон)
        if home_scored_avg is None and home_st:
            played = home_st["played"] or 1
            home_scored_avg = round(home_st["goals_for"] / played, 2) if home_st["goals_for"] else None
            home_allowed_avg = round(home_st["goals_against"] / played, 2) if home_st["goals_against"] else None
        if away_scored_avg is None and away_st:
            played = away_st["played"] or 1
            away_scored_avg = round(away_st["goals_for"] / played, 2) if away_st["goals_for"] else None
            away_allowed_avg = round(away_st["goals_against"] / played, 2) if away_st["goals_against"] else None
        h2h_summary = build_h2h_summary(home, away, h2h_rows)

        notes = []
        if len(home_form) < 5:
            notes.append(f"home_form_len={len(home_form)}")
            notes.append("home_short_form")
        if len(away_form) < 5:
            notes.append(f"away_form_len={len(away_form)}")
            notes.append("away_short_form")
        if not h2h_summary:
            notes.append("h2h_empty")

        payload = {
            "home_form": home_form,
            "away_form": away_form,
            "home_position": home_st["position"] if home_st else None,
            "away_position": away_st["position"] if away_st else None,
            "home_points": home_st["points"] if home_st else None,
            "away_points": away_st["points"] if away_st else None,
            "h2h_summary": h2h_summary,
            "home_goals_scored_avg": home_scored_avg,
            "away_goals_scored_avg": away_scored_avg,
            "home_goals_allowed_avg": home_allowed_avg,
            "away_goals_allowed_avg": away_allowed_avg,
            "home_motivation": get_motivation(home_st["position"], home_st["points"]) if home_st else "",
            "away_motivation": get_motivation(away_st["position"], away_st["points"]) if away_st else "",
            "notes": " | ".join(notes),
        }

        # Calculate points from form
        home_points_last5 = sum(1 if r == "W" else 0.5 if r == "D" else 0 for r in home_form) if home_form else None
        away_points_last5 = sum(1 if r == "W" else 0.5 if r == "D" else 0 for r in away_form) if away_form else None
        
        # Parse H2H data
        h2h_data = {"matches_count": 0, "home_wins": 0, "draws": 0, "away_wins": 0, 
                    "home_scored": 0, "away_scored": 0}
        
        if h2h_rows:
            h2h_data["matches_count"] = len(h2h_rows)
            for r in h2h_rows:
                rh = simplify_name(norm_team(r["home_team"]))
                ra = simplify_name(norm_team(r["away_team"]))
                hs = simplify_name(home)
                
                if rh == hs:  # Home team was home in this h2h match
                    if r["home_score"] > r["away_score"]:
                        h2h_data["home_wins"] += 1
                    elif r["home_score"] == r["away_score"]:
                        h2h_data["draws"] += 1
                    else:
                        h2h_data["away_wins"] += 1
                    h2h_data["home_scored"] += r["home_score"]
                    h2h_data["away_scored"] += r["away_score"]
                else:  # Home team was away in this h2h match
                    if r["away_score"] > r["home_score"]:
                        h2h_data["home_wins"] += 1
                    elif r["away_score"] == r["home_score"]:
                        h2h_data["draws"] += 1
                    else:
                        h2h_data["away_wins"] += 1
                    h2h_data["home_scored"] += r["away_score"]
                    h2h_data["away_scored"] += r["home_score"]
        
        # Get injury data for both teams - first try team_injuries table
        home_injuries = get_team_injuries(conn, home)
        away_injuries = get_team_injuries(conn, away)
        
        # Then try to get injury data from match_facts for this specific match
        match_injuries = get_match_injuries_from_facts(conn, m["id"])
        
        # Merge injury data, preferring match-specific data when available
        injuries_home_count = match_injuries["home_count"] if match_injuries["home_count"] is not None else home_injuries["count"]
        injuries_away_count = match_injuries["away_count"] if match_injuries["away_count"] is not None else away_injuries["count"]
        key_absences_home = match_injuries["home_key_absences"] if match_injuries["home_key_absences"] is not None else home_injuries["key_absences"]
        key_absences_away = match_injuries["away_key_absences"] if match_injuries["away_key_absences"] is not None else away_injuries["key_absences"]
        injuries_notes_home = match_injuries["home_notes"] if match_injuries["home_notes"] is not None else home_injuries["notes"]
        injuries_notes_away = match_injuries["away_notes"] if match_injuries["away_notes"] is not None else away_injuries["notes"]
        
        # Prepare features for the new storage layer
        features = {
            # Standings
            "home_pos": home_st["position"] if home_st else None,
            "away_pos": away_st["position"] if away_st else None,
            "home_points": home_st["points"] if home_st else None,
            "away_points": away_st["points"] if away_st else None,
            "home_goal_diff": home_st["goal_diff"] if home_st else None,
            "away_goal_diff": away_st["goal_diff"] if away_st else None,
            
            # Recent form
            "home_form": home_form,
            "away_form": away_form,
            "home_points_last5": home_points_last5,
            "away_points_last5": away_points_last5,
            "home_scored_last5": home_scored_avg,
            "home_allowed_last5": home_allowed_avg,
            "away_scored_last5": away_scored_avg,
            "away_allowed_last5": away_allowed_avg,
            
            # H2H
            "h2h_matches_count": h2h_data["matches_count"],
            "h2h_home_wins": h2h_data["home_wins"],
            "h2h_draws": h2h_data["draws"],
            "h2h_away_wins": h2h_data["away_wins"],
            "h2h_home_scored": h2h_data["home_scored"],
            "h2h_away_scored": h2h_data["away_scored"],
            "h2h_summary": h2h_summary,
            
            # Injuries
            "injuries_home_count": injuries_home_count,
            "injuries_away_count": injuries_away_count,
            "key_absences_home": key_absences_home,
            "key_absences_away": key_absences_away,
            "injuries_notes_home": injuries_notes_home,
            "injuries_notes_away": injuries_notes_away,
            "has_injury_data": match_injuries["has_injury_data"],
        }
        
        # Save to both tables (keep existing behavior + add new features)
        upsert_match_fact(conn, m["id"], payload)
        
        # Save to the new features table
        data_quality = upsert_match_features(conn, m["id"], m["match_date"], home, away, features)
        
        synced += 1
        print(f"SYNC: {home} — {away} | форма Д:{home_form} Г:{away_form} | notes={payload['notes']}")
        print(f"      Quality: has_standings={data_quality['has_standings']} has_form={data_quality['has_form']} " +
              f"has_goals={data_quality['has_goals']} has_h2h={data_quality['has_h2h']} " +
              f"has_injuries={data_quality['has_injuries']} score={data_quality['data_completeness_score']}")
        print(f"      Injuries: home={features.get('injuries_home_count')} away={features.get('injuries_away_count')}")
        if features.get("has_injury_data", False):
            home_notes = features.get('injuries_notes_home')
            away_notes = features.get('injuries_notes_away')
            print(f"      Injury notes: home={home_notes is not None} away={away_notes is not None}")

    conn.close()
    print(f"\n✅ Synced: {synced}")
    print("\nДальше:")
    print("  python agent_handoff_v7.py --dry-run --sport football --limit 15")

if __name__ == "__main__":
    main()
