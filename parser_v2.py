#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import requests
import sqlite3
from datetime import datetime

FONBET_API = "https://line-lb54-w.bk6bba-resources.com/ma/events/listBase?lang=ru&scopeMarket=1600"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://fon.bet/",
    "Origin": "https://fon.bet",
}
PROXIES = {
    "http":  "socks5://127.0.0.1:1081",
    "https": "socks5://127.0.0.1:1081",
}

SPORT_NAMES = {
    "football": "Футбол",
    "hockey": "Хоккей",
    "tennis": "Теннис",
}

TARGET_LEAGUES_BY_SPORT = {
    "football": [
        "Россия. Премьер-Лига. Сезон 25/26",
        "Англия. Премьер-Лига. Сезон 25/26",
        "Германия. Бундеслига. Сезон 25/26",
        "Испания. Примера дивизион. Сезон 25/26",
        "Италия. Серия А. Сезон 25/26",
        "Франция. Лига 1. Сезон 25/26",
        "РПЛ",
        "Серия А",
        "США. MLS",
        "Эквадор. Серия А",
    ],
    # Летние лиги — паттерн матчинг через is_target_summer_league()
    "football_summer_patterns": [
        "дания", "швеция", "норвег", "финл", "ирланд",
    ],
    "hockey": [
        "Фонбет КХЛ. Регулярный сезон",
        "КХЛ",
        "НХЛ. Регулярный сезон",
        "NHL",
    ],
    # Tennis: all ATP/WTA/Challenger tournaments, skip pairs (doubles)
    "tennis": [],
}


def is_target_hockey_league_extended(league_name: str) -> bool:
    """Extended hockey league filter including DEL, Czech Extraliga, SHL."""
    if not league_name:
        return False

    l = (league_name or "").lower()

    # First check exclusions
    if is_excluded_hockey_league(l):
        return False

    # KHL: только регулярка. Плей-офф сознательно не берём.
    if "кхл" in l or "khl" in l:
        if is_khl_playoff_league(l):
            print(f"[HOCKEY LEAGUE REJECTED] KHL playoff disabled: {league_name}")
            return False
        return True

    # NHL оставляем включённым (регулярка/плей-офф) — стратегия у пользователя используется.
    if "нхл" in l or "nhl" in l:
        return True

    # Czech Extraliga check — только регулярный сезон, плей-офф отключён
    if "чех" in l and ("экстралига" in l or "extraliga" in l):
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    # NLA check — только регулярный сезон, не плей-офф
    if "швейцар" in l and ("national league" in l or "национальная лига" in l):
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    # DEL (Германия) — только регулярный сезон
    if "германи" in l and "del" in l and "del2" not in l:
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    # SHL (Швеция) — только регулярный сезон
    if "швеци" in l and "shl" in l and "allsvenskan" not in l:
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    return False


def ensure_totals_columns(conn):
    """
    Ensure that the totals columns exist in the matches table.
    This function is idempotent and can be called multiple times safely.
    """
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(matches)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    # Define required totals columns
    required_columns = {
        "odds_over_2_5": "REAL",
        "odds_under_2_5": "REAL",
        "odds_over_3_5": "REAL",
        "odds_under_3_5": "REAL",
        "odds_btts_yes": "REAL",
        "odds_btts_no": "REAL"
    }
    
    # Add any missing columns
    for column, data_type in required_columns.items():
        if column not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE matches ADD COLUMN {column} {data_type}")
                print(f"  ✅ Added column {column} to matches table")
            except sqlite3.OperationalError as e:
                # Column might have been added by another process
                print(f"  ⚠️ Could not add column {column}: {e}")
    
    conn.commit()


def create_database():
    conn = sqlite3.connect("betagent.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fonbet_id TEXT UNIQUE,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            odds_over_2_5 REAL,
            odds_under_2_5 REAL,
            odds_over_3_5 REAL,
            odds_under_3_5 REAL,
            odds_btts_yes REAL,
            odds_btts_no REAL,
            status TEXT DEFAULT 'upcoming',
            home_score INTEGER,
            away_score INTEGER,
            updated_at TEXT
        )
    """)
    
    # Ensure totals columns exist in matches table
    ensure_totals_columns(conn)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            market TEXT,
            odds REAL,
            our_probability REAL,
            ev REAL,
            kelly_size REAL,
            stake REAL,
            result TEXT DEFAULT 'pending',
            profit REAL,
            agent_reasoning TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text TEXT UNIQUE,
            sport TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accuracy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT,
            league TEXT,
            market TEXT,
            predicted_prob REAL,
            actual_result INTEGER,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("  ✅ База данных готова: betagent.db")


def get_fonbet_data():
    print("  📡 Подключаемся к Фонбет API...")
    try:
        response = requests.get(FONBET_API, headers=HEADERS, proxies=PROXIES, timeout=20)
        if response.status_code == 200:
            data = response.json()
            print("  ✅ Соединение успешно!")
            print(f"  📊 Спортов получено: {len(data.get('sports', []))}")
            print(f"  📊 Событий получено: {len(data.get('events', []))}")
            return data
        print(f"  ❌ Ошибка соединения: {response.status_code}")
        return None
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        return None


def find_sport_id(sports, sport_name_ru):
    for sport in sports:
        if sport.get("name") == sport_name_ru and sport.get("kind") == "sport":
            return sport.get("id")
    return None


def find_segments(sports, sport_id):
    return [s for s in sports if s.get("parentId") == sport_id and s.get("kind") == "segment"]


def is_excluded_hockey_league(league_name: str) -> bool:
    l = (league_name or "").lower()

    # Общие нерелевантные/виртуальные сегменты
    if "серии" in l or "итоги турнира" in l or "статистические показатели" in l:
        return True

    return any(term in l for term in [
        "nhl 26", "esports", "united esports", "liga pro", "h2h",
        "short", "шорт", "mnhl", "2x2", "3x4", "3x5", "3x7",
        "статистическ", "итоги турнира", "кто наберет",
        "до 20 лет", "u20", "maxa liga"
    ])


def is_khl_playoff_league(league_name: str) -> bool:
    l = (league_name or "").lower()
    if not ("кхл" in l or "khl" in l):
        return False
    playoff_tokens = [
        "плей", "playoff", "play-off", "кубок гагарина", "гагарина",
        "1/8", "1/4", "1/2", "полуфинал", "финал", "четвертьфинал"
    ]
    return any(token in l for token in playoff_tokens)


def is_target_hockey_league(league_name: str) -> bool:
    if not league_name:
        return False

    l = (league_name or "").lower()

    # First check exclusions
    if is_excluded_hockey_league(l):
        return False

    # KHL: только регулярка. Плей-офф сознательно не берём.
    if "кхл" in l or "khl" in l:
        if is_khl_playoff_league(l):
            print(f"[HOCKEY LEAGUE REJECTED] KHL playoff disabled: {league_name}")
            return False
        return True

    # NHL оставляем включённым (регулярка/плей-офф) — стратегия у пользователя используется.
    if "нхл" in l or "nhl" in l:
        return True

    # Czech Extraliga check
    # CZECH — только регулярный сезон, плей-офф отключён
    if "чех" in l and ("экстралига" in l or "extraliga" in l):
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    # NLA check — только регулярный сезон, не плей-офф
    if "швейцар" in l and ("national league" in l or "национальная лига" in l):
        if any(x in l for x in ["плей", "финал", "play", "final", "серии"]):
            return False
        return True

    return False

def is_target_summer_football_league(league_name: str) -> bool:
    """Паттерн-матчинг для летних скандинавских лиг."""
    if not league_name:
        return False
    l = league_name.lower()
    # Только высший дивизион — исключаем 2-й, 3-й дивизионы, резерв, женщин
    exclude = ["2-й", "3-й", "4-й", "второй", "третий", "резерв", "женщин",
               "u20", "до 20", "u19", "до 19", "1-я лига", "1-й дивизион",
               "плей-офф", "кубок", "молодёж"]
    if any(x in l for x in exclude):
        return False
    # Целевые страны — только высший дивизион
    summer_patterns = ["дания", "швеция. премьер", "швеция. аллсвен",
                       "норвегия. суперлига", "норвег. суперлига",
                       "финляндия. суперлига", "финл. суперлига",
                       "финляндия. вейккаус",
                       "ирландия. премьер", "ирланд. премьер"]
    return any(x in l for x in summer_patterns)


def is_target_league(league_name, sport_key):
    if sport_key == "hockey":
        # Use extended filter that includes DEL, Czech Extraliga, SHL
        result = is_target_hockey_league_extended(league_name)
        if result:
            print(f"[HOCKEY LEAGUE ACCEPTED] {league_name}")
        else:
            print(f"[HOCKEY LEAGUE REJECTED] {league_name}")
        return result
    elif sport_key == "tennis":
        result = is_target_tennis_league(league_name)
        if result:
            print(f"[TENNIS LEAGUE ACCEPTED] {league_name}")
        else:
            print(f"[TENNIS LEAGUE REJECTED] {league_name}")
        return result
    else:
        # Точное совпадение для топ-лиг
        if league_name in TARGET_LEAGUES_BY_SPORT.get(sport_key, []):
            return True
        # Паттерн-матчинг для летних лиг
        if is_target_summer_football_league(league_name):
            print(f"[SUMMER LEAGUE ACCEPTED] {league_name}")
            return True
        # Паттерн-матчинг для Эквадор Серия А (Апертура, Клаусура и т.д.)
        if league_name:
            ll = league_name.lower()
            if ("эквадор" in ll or "ecuador" in ll) and ("серия а" in ll or "serie a" in ll):
                print(f"[ECUADOR LEAGUE ACCEPTED] {league_name}")
                return True
        return False


def is_target_tennis_league(league_name: str) -> bool:
    """Accept all ATP/WTA/Challenger singles, reject doubles."""
    if not league_name:
        return False
    l = league_name.lower()
    # Reject doubles
    if "пар" in l:
        return False
    # Accept ATP, WTA, Challenger, ITF
    if any(x in l for x in ["atp", "wta", "челленджер", "itf", "большой шлем"]):
        return True
    return False


def get_odds(custom_factors, event_id):
    odds_home = odds_draw = odds_away = None
    odds_over_2_5 = odds_under_2_5 = odds_over_3_5 = odds_under_3_5 = None
    odds_btts_yes = odds_btts_no = None
    event_cf = None
    for cf in custom_factors:
        if cf.get("e") == event_id:
            event_cf = cf
            break
    if not event_cf:
        return None, None, None, None, None, None, None, None, None

    for factor in event_cf.get("factors", []):
        fid = factor.get("f")
        val = factor.get("v")
        if val is None:
            continue
        try:
            if fid == 921:
                odds_home = float(val)
            elif fid == 922:
                odds_draw = float(val)
            elif fid == 923:
                odds_away = float(val)
            # Totals markets
            elif fid == 930:  # Over 2.5
                odds_over_2_5 = float(val)
            elif fid == 931:  # Under 2.5
                odds_under_2_5 = float(val)
            elif fid == 938:  # Over 3.5
                odds_over_3_5 = float(val)
            elif fid == 939:  # Under 3.5
                odds_under_3_5 = float(val)
            # BTTS markets
            elif fid == 4241:  # BTTS Yes
                odds_btts_yes = float(val)
            elif fid == 4242:  # BTTS No
                odds_btts_no = float(val)
            # Fallback for BTTS markets (older/other leagues)
            elif fid == 1033:  # BTTS Yes (fallback)
                if odds_btts_yes is None:  # Only use if primary ID not found
                    odds_btts_yes = float(val)
            elif fid == 1034:  # BTTS No (fallback)
                if odds_btts_no is None:  # Only use if primary ID not found
                    odds_btts_no = float(val)
        except Exception:
            continue
    return odds_home, odds_draw, odds_away, odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5, odds_btts_yes, odds_btts_no


def get_tennis_odds(custom_factors, event_id):
    """Extract tennis winner odds (f=921 for player1, f=923 for player2)."""
    odds_p1 = odds_p2 = None
    for cf in custom_factors:
        if cf.get("e") == event_id:
            for factor in cf.get("factors", []):
                fid = factor.get("f")
                val = factor.get("v")
                if val is None:
                    continue
                try:
                    if fid == 921:
                        odds_p1 = float(val)
                    elif fid == 923:
                        odds_p2 = float(val)
                except Exception:
                    continue
            break
    return odds_p1, odds_p2


def is_placeholder(home, away):
    bad = {"Хозяева", "Гости", "Hosts", "Guests"}
    return home in bad or away in bad


def parse_fonbet_data(data, only_sport=None):
    sports = data.get("sports", [])
    events = data.get("events", [])
    custom_factors = data.get("customFactors", [])
    event_blocks = data.get("eventBlocks", [])
    blocked_ids = {b.get("eventId") for b in event_blocks}
    all_matches = []
    all_tennis = []

    for sport_key, sport_name_ru in SPORT_NAMES.items():
        if only_sport and sport_key != only_sport:
            continue

        sport_id = find_sport_id(sports, sport_name_ru)
        if not sport_id:
            print(f"  ⚠️  Спорт не найден: {sport_name_ru}")
            continue

        segments = find_segments(sports, sport_id)

        for segment in segments:
            league_name = segment.get("name", "")
            if not is_target_league(league_name, sport_key):
                continue

            segment_id = segment.get("id")
            segment_events = [
                e for e in events
                if e.get("sportId") == segment_id
                and not e.get("parentId")
                and e.get("id") not in blocked_ids
                and e.get("team1")
                and e.get("team2")
            ]

            for event in segment_events:
                event_id = event.get("id")
                team1 = event.get("team1", "").strip()
                team2 = event.get("team2", "").strip()
                event_name = event.get("name", "")

                # --- TENNIS PATH ---
                if sport_key == "tennis":
                    odds_p1, odds_p2 = get_tennis_odds(custom_factors, event_id)
                    if not odds_p1 or not odds_p2:
                        continue

                    start_time = event.get("startTime", "")
                    if start_time:
                        try:
                            dt = datetime.fromtimestamp(int(start_time))
                            match_date = dt.strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            match_date = str(start_time)
                    else:
                        continue

                    match_data = {
                        "fonbet_id": str(event_id),
                        "sport": sport_key,
                        "league": league_name,
                        "player1": team1,
                        "player2": team2,
                        "match_date": match_date,
                        "odds_p1": odds_p1,
                        "odds_p2": odds_p2,
                    }
                    all_tennis.append(match_data)
                    print(f"[TENNIS EVENT ACCEPTED] {team1} vs {team2} on {match_date} | {league_name} | {odds_p1}/{odds_p2}")
                    continue

                # --- FOOTBALL / HOCKEY PATH ---
                if is_placeholder(team1, team2):
                    if sport_key == "hockey":
                        print(f"[HOCKEY EVENT REJECTED] Placeholder teams: {team1} vs {team2}")
                    continue

                odds_home, odds_draw, odds_away, odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5, odds_btts_yes, odds_btts_no = get_odds(custom_factors, event_id)
                if not odds_home or not odds_away:
                    if sport_key == "hockey":
                        print(f"[HOCKEY EVENT REJECTED] Missing odds: home={odds_home}, away={odds_away}")
                    continue

                start_time = event.get("startTime", "")
                if start_time:
                    try:
                        dt = datetime.fromtimestamp(int(start_time))
                        match_date = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        match_date = str(start_time)
                        if sport_key == "hockey":
                            print(f"[HOCKEY EVENT WARNING] Invalid date format: {start_time}")
                else:
                    match_date = ""
                    if sport_key == "hockey":
                        print(f"[HOCKEY EVENT REJECTED] Missing start time")
                        continue

                # Check if this is a real match event (not a series/outright)
                if sport_key == "hockey" and ("серии" in event_name.lower() or "статистические показатели" in event_name.lower()):
                    print(f"[HOCKEY EVENT REJECTED] Not a match event: {event_name}")
                    continue

                match_data = {
                    "fonbet_id": str(event_id),
                    "sport": sport_key,
                    "league": league_name,
                    "home_team": team1,
                    "away_team": team2,
                    "match_date": match_date,
                    "odds_home": odds_home,
                    "odds_draw": odds_draw,
                    "odds_away": odds_away,
                    "odds_over_2_5": odds_over_2_5,
                    "odds_under_2_5": odds_under_2_5,
                    "odds_over_3_5": odds_over_3_5,
                    "odds_under_3_5": odds_under_3_5,
                    "odds_btts_yes": odds_btts_yes,
                    "odds_btts_no": odds_btts_no,
                }

                all_matches.append(match_data)
                if sport_key == "hockey":
                    print(f"[HOCKEY EVENT ACCEPTED] Added to matches: {team1} vs {team2} on {match_date}")

    return all_matches, all_tennis


def replace_sport_matches_safe(sport_key):
    conn = sqlite3.connect("betagent.db")
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM matches
        WHERE sport = ?
          AND status = 'upcoming'
          AND id NOT IN (
              SELECT DISTINCT match_id
              FROM bets
              WHERE result = 'pending'
                AND match_id IS NOT NULL
          )
    """, (sport_key,))
    deleted = cur.rowcount

    cur.execute("""
        SELECT COUNT(*)
        FROM matches
        WHERE sport = ?
          AND status = 'upcoming'
          AND id IN (
              SELECT DISTINCT match_id
              FROM bets
              WHERE result = 'pending'
                AND match_id IS NOT NULL
          )
    """, (sport_key,))
    protected = cur.fetchone()[0]

    conn.commit()
    conn.close()
    return deleted, protected


def save_matches(matches):
    conn = sqlite3.connect("betagent.db")
    cursor = conn.cursor()
    saved = updated = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for m in matches:
        cursor.execute("SELECT id, status FROM matches WHERE fonbet_id=?", (m["fonbet_id"],))
        _row = cursor.fetchone()
        if _row and _row[1] == "finished":
            continue
        if _row:
            cursor.execute("""
                UPDATE matches
                SET sport=?, league=?, home_team=?, away_team=?, match_date=?,
                    odds_home=?, odds_draw=?, odds_away=?, 
                    odds_over_2_5=?, odds_under_2_5=?, odds_over_3_5=?, odds_under_3_5=?,
                    odds_btts_yes=?, odds_btts_no=?,
                    updated_at=?, status='upcoming'
                WHERE fonbet_id=?
            """, (
                m["sport"], m["league"], m["home_team"], m["away_team"], m["match_date"],
                m["odds_home"], m["odds_draw"], m["odds_away"],
                m.get("odds_over_2_5"), m.get("odds_under_2_5"), m.get("odds_over_3_5"), m.get("odds_under_3_5"),
                m.get("odds_btts_yes"), m.get("odds_btts_no"),
                now, m["fonbet_id"]
            ))
            updated += 1
        else:
            cursor.execute("""
                INSERT INTO matches
                (fonbet_id, sport, league, home_team, away_team,
                 match_date, odds_home, odds_draw, odds_away, 
                 odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
                 odds_btts_yes, odds_btts_no, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m["fonbet_id"], m["sport"], m["league"],
                m["home_team"], m["away_team"], m["match_date"],
                m["odds_home"], m["odds_draw"], m["odds_away"],
                m.get("odds_over_2_5"), m.get("odds_under_2_5"), m.get("odds_over_3_5"), m.get("odds_under_3_5"),
                m.get("odds_btts_yes"), m.get("odds_btts_no"), now
            ))
            saved += 1

    conn.commit()
    conn.close()
    return saved, updated


def add_rules():
    conn = sqlite3.connect("betagent.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rules = [
        ("Не ставить на фаворита с коэф ниже 1.55 — даже при наличии edge. Профиль риска плохой.", "football"),
        ("Серия А — всегда проверять рынок X. Итальянский футбол недооценивает ничью.", "football"),
        ("Фавориты 1.40-1.50 исторически дают плохой результат в нашей базе.", "football"),
        ("Домашние андердоги в РПЛ выигрывают чаще чем говорит рынок.", "football"),
        ("В конце регулярки КХЛ проверять мотивацию — топ-команды могут беречь игроков.", "hockey"),
        ("Рынок переоценивает бренд (СКА, ЦСКА) — смотреть реальную таблицу.", "hockey"),
    ]
    added = 0
    for rule_text, sport in rules:
        cursor.execute("SELECT id FROM rules WHERE rule_text=?", (rule_text,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO rules (rule_text, sport, created_at) VALUES (?, ?, ?)",
                (rule_text, sport, now)
            )
            added += 1
    conn.commit()
    conn.close()
    print(f"  ✅ Правил добавлено: {added}")


def show_matches(sport=None, limit=30):
    conn = sqlite3.connect("betagent.db")
    cursor = conn.cursor()
    if sport:
        cursor.execute("""
            SELECT sport, league, home_team, away_team,
                   match_date, odds_home, odds_draw, odds_away,
                   odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
                   odds_btts_yes, odds_btts_no
            FROM matches
            WHERE status='upcoming' AND sport=?
            ORDER BY match_date
            LIMIT ?
        """, (sport, limit))
    else:
        cursor.execute("""
            SELECT sport, league, home_team, away_team,
                   match_date, odds_home, odds_draw, odds_away,
                   odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
                   odds_btts_yes, odds_btts_no
            FROM matches
            WHERE status='upcoming'
            ORDER BY sport, match_date
            LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 60)
    print(f"📋 МАТЧИ В БАЗЕ — {len(rows)} шт.")
    print("=" * 60)

    current_sport = None
    for sport_name, league, home, away, date, o1, ox, o2, over_2_5, under_2_5, over_3_5, under_3_5, btts_yes, btts_no in rows:
        if sport_name != current_sport:
            emoji = "⚽" if sport_name == "football" else "🏒"
            print(f"\n{emoji}  {sport_name.upper()}")
            current_sport = sport_name
        ox_str = f" X:{ox}" if ox else ""
        print(f"  [{league}] {date}")
        print(f"  {home} — {away}")
        print(f"  П1:{o1}{ox_str}  П2:{o2}")
        
        # Display totals if available
        totals_lines = []
        if over_2_5 or under_2_5:
            totals_lines.append(f"  ТБ2.5:{over_2_5}  ТМ2.5:{under_2_5}")
        if over_3_5 or under_3_5:
            totals_lines.append(f"  ТБ3.5:{over_3_5}  ТМ3.5:{under_3_5}")
        
        # Display BTTS if available (only for football)
        if sport_name == "football" and (btts_yes or btts_no):
            totals_lines.append(f"  ОЗ-ДА:{btts_yes}  ОЗ-НЕТ:{btts_no}")
        
        if totals_lines:
            print("\n".join(totals_lines))
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=["football", "hockey"], default=None)
    parser.add_argument("--show-limit", type=int, default=30)
    parser.add_argument("--replace-sport", action="store_true")
    args = parser.parse_args()

    print("🚀 BETAGENT — Парсер Фонбет v2 (safe replace)")
    print("=" * 60)

    print("\n📦 Шаг 1: Создаём базу данных...")
    create_database()
    
    # Ensure schema is up to date
    conn = sqlite3.connect("betagent.db")
    ensure_totals_columns(conn)
    conn.close()

    print("\n📡 Шаг 2: Получаем линию с Фонбет...")
    data = get_fonbet_data()

    if args.replace_sport and args.sport:
        deleted, protected = replace_sport_matches_safe(args.sport)
        print(f"  🧹 Удалено старых upcoming-матчей ({args.sport}): {deleted}")
        print(f"  🛡️  Защищено upcoming-матчей с pending-ставками: {protected}")

    if data:
        print("\n🔍 Шаг 3: Разбираем данные...")
        matches, tennis = parse_fonbet_data(data, only_sport=args.sport)
        print(f"  📊 Найдено подходящих матчей: {len(matches)}")
        if matches:
            saved, updated = save_matches(matches)
            print(f"  ✅ Новых: {saved} | Обновлено: {updated}")
        else:
            print("  ⚠️  Подходящих матчей не найдено")
    else:
        print("\n❌ Не удалось получить данные с Фонбет.")

    print("\n📌 Шаг 4: Загружаем правила...")
    add_rules()

    print("\n📋 Шаг 5: Показываем результат...")
    show_matches(sport=args.sport, limit=args.show_limit)

    print("=" * 60)
    print("✅ Готово! База данных: betagent.db")
    if args.sport:
        print(f"   Текущий спорт: {args.sport}")
    print("=" * 60)


if __name__ == "__main__":
    main()
