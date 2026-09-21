#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — updater_results.py (v2)

Исправления v2:
- fallback на results_raw умеет матчить короткие названия команд
  ("Монреаль") с полными ("Монреаль Канадиенс")
- учитывает сдвиг даты +/- 1 день
- отдельная диагностика stale pending
- settler запускается, если в БД уже есть pending ставки на finished матчах
"""

import os
import re
import sqlite3
import argparse
import urllib3
import requests
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

urllib3.disable_warnings()

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
STALE_HOURS = int(os.getenv("STALE_PENDING_HOURS", "4"))

FONBET_APIS = [
    x.strip()
    for x in os.getenv(
        "FONBET_RESULTS_APIS",
        "https://line-lb54-w.bk6bba-resources.com/ma/events/listBase?lang=ru&scopeMarket=1600",
    ).split(",")
    if x.strip()
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://fon.bet/",
    "Origin": "https://fon.bet",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_pending_matches(conn):
    rows = conn.execute("""
        SELECT DISTINCT
            m.id,
            m.fonbet_id,
            m.sport,
            m.league,
            m.home_team,
            m.away_team,
            m.match_date,
            m.status,
            m.home_score,
            m.away_score
        FROM matches m
        JOIN bets b ON b.match_id = m.id
        WHERE b.result = 'pending'
        ORDER BY m.match_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_stale_pending(conn, hours: int):
    rows = conn.execute("""
        SELECT
            b.id AS bet_id,
            m.id AS match_id,
            m.sport,
            m.home_team,
            m.away_team,
            m.match_date,
            m.status,
            b.market
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
          AND datetime(m.match_date) < datetime('now', ?)
        ORDER BY m.match_date ASC
    """, (f"-{hours} hours",)).fetchall()
    return [dict(r) for r in rows]

def get_very_stale_pending(conn, hours: int = 24):
    """Get matches that are more than 24 hours old and still pending"""
    rows = conn.execute("""
        SELECT
            m.id AS match_id,
            m.fonbet_id,
            m.sport,
            m.league,
            m.home_team,
            m.away_team,
            m.match_date,
            m.status
        FROM matches m
        JOIN bets b ON b.match_id = m.id
        WHERE b.result = 'pending'
          AND datetime(m.match_date) < datetime('now', ?)
        GROUP BY m.id
        ORDER BY m.match_date ASC
    """, (f"-{hours} hours",)).fetchall()
    return [dict(r) for r in rows]


def get_finished_pending_count(conn):
    row = conn.execute("""
        SELECT COUNT(*) AS cnt
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
          AND m.status = 'finished'
    """).fetchone()
    return int(row["cnt"] or 0)


def get_pending_bet_count(conn):
    row = conn.execute("""
        SELECT COUNT(*) AS cnt
        FROM bets
        WHERE result = 'pending'
    """).fetchone()
    return int(row["cnt"] or 0)


def mark_finished(conn, match_id, home_score, away_score, source, dry_run=False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Не закрываем матчи дата которых ещё в будущем
    row = conn.execute("SELECT match_date FROM matches WHERE id=?", (match_id,)).fetchone()
    if row:
        try:
            match_dt = datetime.strptime(str(row["match_date"])[:16], "%Y-%m-%d %H:%M")
            if match_dt > datetime.now():
                print(f"  ⏭️  match_id={match_id} пропущен — матч ещё не начался ({match_dt})")
                return
        except Exception:
            pass
    if not dry_run:
        conn.execute("""
            UPDATE matches
            SET status='finished',
                home_score=?,
                away_score=?,
                updated_at=?
            WHERE id=?
        """, (home_score, away_score, now, match_id))
        conn.commit()
    print(f"  ✅ [{source}] match_id={match_id} → {home_score}:{away_score}"
          + (" [DRY-RUN]" if dry_run else ""))


def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    name = name.replace("ё", "е")
    name = re.sub(r"[()\[\].,'`\"-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    
    # Expand hockey city abbreviations
    hockey_abbrevs = {
        "мг": "магнитогорск",
        "нн": "нижний новгород",
    }
    for abbr, full in hockey_abbrevs.items():
        if name.endswith(f" {abbr}"):
            name = name[:-len(abbr)].strip() + " " + full
    
    for token in [
        "хк", "фк", "hc", "fc",
        "u21", "u20", "u19",
        "women", "w", "жен",
    ]:
        name = re.sub(rf"\b{re.escape(token)}\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def team_names_match(short_name: str, full_name: str) -> bool:
    """
    Позволяет матчить:
    'Монреаль' <-> 'Монреаль Канадиенс'
    'Анахайм' <-> 'Анахайм Дакс'
    'СКА' <-> 'СКА Санкт-Петербург'
    'Юта' <-> 'Юта Хоккей Клаб'
    """
    a = normalize_team_name(short_name)
    b = normalize_team_name(full_name)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    
    # Специальные случаи для хоккея
    hockey_special_cases = {
        "ска": ["ска санкт петербург", "ска санкт-петербург", "ска петербург"],
        "юта": ["юта хоккей клаб", "юта маммот", "юта мэммот"],
        "маунтфилд": ["маунтфилд гк", "маунтфилд градец кралове", "mountfield hk"],
        "тршинец": ["оцеларжи тршинец", "hc ocelari trinec"],
    }
    
    a_lower = a.lower()
    b_lower = b.lower()
    
    for key, variants in hockey_special_cases.items():
        if a_lower == key and any(b_lower == v for v in variants):
            return True
        if b_lower == key and any(a_lower == v for v in variants):
            return True

    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return False

    # если все токены короткого имени входят в полное имя — считаем матчем
    if a_tokens.issubset(b_tokens) or b_tokens.issubset(a_tokens):
        return True

    # мягкий вариант: пересечение не пустое и первое слово совпадает
    a_first = a.split()[0]
    b_first = b.split()[0]
    if a_first == b_first and len(a_tokens & b_tokens) >= 1:
        return True

    return False


def fetch_fonbet_results():
    last_error = None
    for api in FONBET_APIS:
        try:
            print(f"  📡 Фонбет запрос: {api}")
            r = requests.get(api, headers=HEADERS, timeout=20, verify=False)
            if r.status_code != 200:
                print(f"  ⚠️  Фонбет API: статус {r.status_code}")
                last_error = f"status={r.status_code}"
                continue
            data = r.json()
        except Exception as e:
            print(f"  ❌ Фонбет API ошибка: {e}")
            last_error = str(e)
            continue

        results = {}
        for event in data.get("events", []):
            event_status = event.get("status", "")
            is_finished = (
                event_status in ("finished", "ended", "closed")
                or event.get("isFinished") is True
                or event.get("finished") is True
            )
            has_live_marker = event.get("liveCurrent") or event.get("liveTime")

            score = event.get("score") or event.get("result") or ""
            if not score:
                continue
            if has_live_marker and not is_finished:
                continue

            m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", str(score))
            if m:
                fonbet_id = str(event.get("id", ""))
                if fonbet_id:
                    results[fonbet_id] = (int(m.group(1)), int(m.group(2)))

        print(f"  📡 Фонбет: найдено {len(results)} матчей со счётом")
        return results

    print(f"  ⚠️  Фонбет недоступен, используем fallback. last_error={last_error}")
    return {}


def check_fonbet_for_match(fonbet_results, fonbet_id):
    if not fonbet_id:
        return None
    return fonbet_results.get(str(fonbet_id))


def _check_tennis_live_results(conn, home_team, away_team, match_date):
    """
    Ищем теннисный матч в tennis_live_results по фамилиям.
    Возвращает (sets_winner, sets_loser) или None.
    Проверяет дату матча +/- 1 день (матч мог завершиться на день позже).
    """
    def _surname(name: str) -> str:
        if not name:
            return ""
        parts = name.strip().replace(".", "").split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    translit_map = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "u", "я": "ia",
    })

    def _latin_key(name: str) -> str:
        value = _surname(name).lower().replace("ё", "е")
        value = value.translate(translit_map)
        value = re.sub(r"[^a-z]", "", value)
        value = value.replace("ou", "u").replace("oo", "u")
        return value

    def _skeleton(name: str) -> str:
        return re.sub(r"[aeiouy]", "", _latin_key(name))

    def _name_tokens(name: str) -> set[str]:
        if not name:
            return set()
        value = name.lower().replace("ё", "е").replace(".", " ")
        value = value.translate(translit_map)
        tokens = re.findall(r"[a-z]+", value)
        return {t for t in tokens if len(t) >= 2}

    def _same_player(left: str, right: str) -> bool:
        left_key = _latin_key(left)
        right_key = _latin_key(right)
        if left_key and right_key and left_key == right_key:
            return True
        left_skeleton = _skeleton(left)
        right_skeleton = _skeleton(right)
        if left_skeleton and right_skeleton and left_skeleton == right_skeleton:
            return True
        if left_key and right_key and len(left_key) >= 4 and len(right_key) >= 4:
            if left_key.endswith(right_key) or right_key.endswith(left_key):
                return True
        left_tokens = _name_tokens(left)
        right_tokens = _name_tokens(right)
        if left_tokens and right_tokens and left_tokens.intersection(right_tokens):
            return True
        return False

    s1 = _surname(home_team)
    s2 = _surname(away_team)
    if not s1 or not s2:
        return None

    home_key = _latin_key(home_team)
    away_key = _latin_key(away_team)
    home_skeleton = _skeleton(home_team)
    away_skeleton = _skeleton(away_team)

    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        dates = [str(match_date)[:10]]

    for d in dates:
        rows = conn.execute("""
            SELECT winner_name, loser_name, sets_winner, sets_loser
            FROM tennis_live_results
            WHERE match_date = ?
        """, (d,)).fetchall()

        for row in rows:
            winner_key = _latin_key(row["winner_name"])
            loser_key = _latin_key(row["loser_name"])
            winner_skeleton = _skeleton(row["winner_name"])
            loser_skeleton = _skeleton(row["loser_name"])

            direct_match = (
                (_same_player(row["winner_name"], home_team) and _same_player(row["loser_name"], away_team)) or
                (_same_player(row["winner_name"], away_team) and _same_player(row["loser_name"], home_team))
            )
            skeleton_match = (
                (winner_skeleton == home_skeleton and loser_skeleton == away_skeleton) or
                (winner_skeleton == away_skeleton and loser_skeleton == home_skeleton)
            )
            # Compound-surname partial match: "Мерида-Агилар Д" -> "meridaagilar"
            # vs "Даниель Мерида Агилар" -> "agilar". "meridaagilar".endswith("agilar") is True.
            partial_match = (
                len(loser_key) >= 4 and len(away_key) >= 4 and
                (
                    (winner_key == home_key and (away_key.endswith(loser_key) or loser_key.endswith(away_key))) or
                    (winner_key == away_key and (home_key.endswith(loser_key) or loser_key.endswith(home_key)))
                )
            )

            if direct_match or skeleton_match or partial_match:
                if row["sets_winner"] is None or row["sets_loser"] is None:
                    return None
                return (int(row["sets_winner"]), int(row["sets_loser"]))
    return None


def _has_related_tennis_result(conn, home_team, away_team, match_date):
    def _surname(name: str) -> str:
        if not name:
            return ""
        parts = name.strip().replace(".", "").split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    translit_map = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "u", "я": "ia",
    })

    def _latin_key(name: str) -> str:
        value = _surname(name).lower().replace("ё", "е")
        value = value.translate(translit_map)
        value = re.sub(r"[^a-z]", "", value)
        value = value.replace("ou", "u").replace("oo", "u")
        return value

    def _skeleton(name: str) -> str:
        return re.sub(r"[aeiouy]", "", _latin_key(name))

    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        dates = [str(match_date)[:10]]

    home_key = _latin_key(home_team)
    away_key = _latin_key(away_team)
    home_skeleton = _skeleton(home_team)
    away_skeleton = _skeleton(away_team)
    if not home_key and not away_key:
        return False

    rows = conn.execute(
        f"""
        SELECT winner_name, loser_name
        FROM tennis_live_results
        WHERE match_date IN ({",".join("?" for _ in dates)})
        """,
        dates,
    ).fetchall()

    for row in rows:
        winner_key = _latin_key(row["winner_name"])
        loser_key = _latin_key(row["loser_name"])
        winner_skeleton = _skeleton(row["winner_name"])
        loser_skeleton = _skeleton(row["loser_name"])

        if home_key and (winner_key == home_key or loser_key == home_key):
            return True
        if away_key and (winner_key == away_key or loser_key == away_key):
            return True
        if home_skeleton and (winner_skeleton == home_skeleton or loser_skeleton == home_skeleton):
            return True
        if away_skeleton and (winner_skeleton == away_skeleton or loser_skeleton == away_skeleton):
            return True
        # Compound-surname partial match
        if len(away_key) >= 4 and (
            (winner_key == home_key and (away_key.endswith(loser_key) or loser_key.endswith(away_key))) or
            (winner_key == away_key and (home_key.endswith(loser_key) or loser_key.endswith(home_key)))
        ):
            return True
    return False


def diagnose_tennis_pending(conn, match: dict) -> str:
    home = match.get("home_team")
    away = match.get("away_team")
    match_date = match.get("match_date")
    status = match.get("status")
    home_score = match.get("home_score")
    away_score = match.get("away_score")

    if status == "finished" and home_score is not None and away_score is not None:
        return "ready_with_match_score"

    score = _check_tennis_live_results(conn, home, away, match_date)
    if score:
        return "result_source_found"

    if _has_related_tennis_result(conn, home, away, match_date):
        return "mapping_failed"

    try:
        match_day = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        if match_day.date() >= datetime.now(timezone.utc).date():
            return "match_not_finished"
    except Exception:
        pass

    return "no_result_source"


def check_the_sports_for_match(conn, home_team, away_team, match_date, sport=None, aggressive=False):
    """
    Ищем матч в results_raw:
    1) exact by home/away/date
    2) normalized exact by date +/-1
    3) short-vs-full name matching by date +/-1
    4) reversed team order support
    
    Если sport='hockey', ищем только в khl/nhl лигах
    
    aggressive=True: расширенный поиск для старых матчей
    - игнорирует фильтр по лиге
    - расширяет диапазон дат до +/-2 дней
    """
    try:
        match_day = str(match_date)[:10]
        dt = datetime.strptime(match_day, "%Y-%m-%d")
        
        # Standard or aggressive date range
        if aggressive:
            dates = [
                (dt - timedelta(days=2)).strftime("%Y-%m-%d"),
                (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                match_day,
                (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                (dt + timedelta(days=2)).strftime("%Y-%m-%d"),
            ]
        else:
            dates = [
                (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                match_day,
                (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            ]

        # 1) exact
        for d in dates:
            row = conn.execute("""
                SELECT home_score, away_score
                FROM results_raw
                WHERE is_finished = 1
                  AND home_team = ?
                  AND away_team = ?
                  AND match_date = ?
                LIMIT 1
            """, (home_team, away_team, d)).fetchone()
            if row and row["home_score"] is not None:
                return (row["home_score"], row["away_score"])

        # 2-4) scan all finished matches nearby
        for d in dates:
            if sport == 'hockey' and not aggressive:
                # Для хоккея ищем только в khl/nhl лигах (если не агрессивный режим)
                rows = conn.execute("""
                    SELECT home_team, away_team, home_score, away_score
                    FROM results_raw
                    WHERE is_finished = 1
                      AND match_date = ?
                      AND lower(league) IN ('khl', 'nhl', 'czech')
                """, (d,)).fetchall()
            else:
                # В агрессивном режиме игнорируем фильтр по лиге
                rows = conn.execute("""
                    SELECT home_team, away_team, home_score, away_score
                    FROM results_raw
                    WHERE is_finished = 1
                      AND match_date = ?
                """, (d,)).fetchall()

            for row in rows:
                rh = row["home_team"] or ""
                ra = row["away_team"] or ""

                # exact normalized
                if normalize_team_name(rh) == normalize_team_name(home_team) and normalize_team_name(ra) == normalize_team_name(away_team):
                    return (row["home_score"], row["away_score"])

                # reversed exact normalized
                if normalize_team_name(rh) == normalize_team_name(away_team) and normalize_team_name(ra) == normalize_team_name(home_team):
                    return (row["away_score"], row["home_score"])

                # short/full matching
                if team_names_match(home_team, rh) and team_names_match(away_team, ra):
                    return (row["home_score"], row["away_score"])

                # reversed short/full matching
                if team_names_match(home_team, ra) and team_names_match(away_team, rh):
                    return (row["away_score"], row["home_score"])
    except Exception as e:
        print(f"  ⚠️  results_raw lookup error: {e}")
    return None


def run_settler_now():
    print("\nЗапускаем settler...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    settler_path = os.path.join(script_dir, "settler.py")
    try:
        import settler
        settler.settle_bets()
        return
    except Exception as e:
        print(f"  ⚠️ import settler failed: {e}")

    try:
        result = subprocess.run(
            ["python3", settler_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            cwd=script_dir,
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except Exception as e:
        print(f"  ❌ settler.py error: {e}")


def update_results(dry_run=False, run_settler=False, debug_tennis=False):
    conn = get_conn()
    pending = get_pending_matches(conn)
    pending_bets_before = get_pending_bet_count(conn)

    if not pending:
        print("Нет pending ставок — нечего обновлять.")
        finished_pending_before = get_finished_pending_count(conn)
        if run_settler and finished_pending_before > 0 and not dry_run:
            print(f"Но есть pending ставки на finished матчах: {finished_pending_before}")
            run_settler_now()
        conn.close()
        return

    print(f"Найдено {len(pending)} матчей с pending ставками\n")

    stale = get_stale_pending(conn, STALE_HOURS)
    if stale:
        print(f"⚠️ Просроченных pending ({STALE_HOURS}ч+): {len(stale)}")
        for row in stale[:10]:
            print(f"  bet_id={row['bet_id']} | {row['sport']} | {row['home_team']} — {row['away_team']} | {row['match_date']} | {row['market']}")
    
    # Check for very stale matches (>24h)
    very_stale = get_very_stale_pending(conn, 24)
    if very_stale:
        print(f"⚠️ Очень старых pending (24ч+): {len(very_stale)}")
        for row in very_stale[:5]:
            print(f"  match_id={row['match_id']} | {row['sport']} | {row['home_team']} — {row['away_team']} | {row['match_date']}")

    # Only fetch external results if needed
    fonbet_results = {}
    updated = 0
    not_found = 0
    not_found_by_sport = {}
    not_found_examples = []
    tennis_pending = 0
    tennis_result_ready = 0
    tennis_closed_candidates = 0
    tennis_reason_counts = {
        "no_match_score": 0,
        "no_result_source": 0,
        "mapping_failed": 0,
        "match_not_finished": 0,
    }

    for match in pending:
        home = match["home_team"]
        away = match["away_team"]
        match_date = match["match_date"]
        match_id = match["id"]
        sport = match.get("sport")
        
        # Check if this is a very stale match (>24h)
        is_very_stale = False
        for vs in very_stale:
            if vs["match_id"] == match_id:
                is_very_stale = True
                break
                
        print(f"\n[{sport}] {home} — {away} | {match_date}{' [ОЧЕНЬ СТАРЫЙ]' if is_very_stale else ''}")

        # FIRST: Check if match already has scores in the local matches table
        if match["status"] == "finished" and match["home_score"] is not None and match["away_score"] is not None:
            print(f"  ✅ [Локальная БД] match_id={match_id} → {match['home_score']}:{match['away_score']}")
            updated += 1
            if sport == "tennis":
                tennis_pending += 1
                tennis_result_ready += 1
                tennis_closed_candidates += 1
            continue

        # Tennis: check tennis_live_results (not in results_raw)
        if sport == "tennis":
            tennis_pending += 1
            score = _check_tennis_live_results(conn, home, away, match_date)
            if score:
                tennis_result_ready += 1
                tennis_closed_candidates += 1
                mark_finished(conn, match_id, score[0], score[1], "tennis_live_results", dry_run)
                updated += 1
                if debug_tennis:
                    print(f"  🎾 debug: result_source=tennis_live_results | sets={score[0]}:{score[1]}")
                continue
            reason = diagnose_tennis_pending(conn, match)
            mapped_reason = {
                "ready_with_match_score": "no_match_score",
                "result_source_found": "no_match_score",
                "mapping_failed": "mapping_failed",
                "match_not_finished": "match_not_finished",
                "no_result_source": "no_result_source",
            }.get(reason, "no_result_source")
            tennis_reason_counts[mapped_reason] += 1
            if debug_tennis:
                print(f"  🎾 debug: reason={reason}")

        # Try standard results_raw lookup
        score = check_the_sports_for_match(conn, home, away, match_date, sport)
        if score:
            mark_finished(conn, match_id, score[0], score[1], "results_raw", dry_run)
            updated += 1
            continue
            
        # For very stale matches, try aggressive matching
        if is_very_stale:
            print(f"  🔍 Агрессивный поиск для старого матча...")
            score = check_the_sports_for_match(conn, home, away, match_date, sport, aggressive=True)
            if score:
                mark_finished(conn, match_id, score[0], score[1], "results_raw (агрессивный)", dry_run)
                updated += 1
                continue
                
            # Auto-resolve very stale matches if still not found
            # Skip tennis — 0:0 is meaningless for tennis sets
            if sport == "tennis":
                print(f"  ⏭️  Пропущен — теннисный матч, авто-закрытие 0:0 не применяется")
                not_found += 1
                continue

            print(f"  ⚠️ Авто-закрытие старого матча без результата")
            if not dry_run:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    UPDATE matches
                    SET status='finished',
                        home_score=0,
                        away_score=0,
                        updated_at=?
                    WHERE id=?
                """, (now, match_id))
                conn.commit()
            print(f"  ✅ [UNKNOWN RESULT (auto-resolved)] match_id={match_id} → 0:0" + (" [DRY-RUN]" if dry_run else ""))
            updated += 1
            continue

        print(f"  ⏳ Результат ещё не найден. Матч: {match_date}")
        not_found += 1
        sport_key = sport or "unknown"
        not_found_by_sport[sport_key] = not_found_by_sport.get(sport_key, 0) + 1
        if len(not_found_examples) < 5:
            not_found_examples.append(f"{sport_key}: {home} — {away} | {str(match_date)[:16]}")

    print(f"\n{'='*50}")
    print(f"Settlement summary | pending_matches={len(pending)} | pending_bets_before={pending_bets_before} | updated_matches={updated} | not_found_matches={not_found}")
    if not_found_by_sport:
        parts = [f"{sport}={cnt}" for sport, cnt in sorted(not_found_by_sport.items())]
        print("Not found by sport: " + ", ".join(parts))
    if not_found_examples:
        print("Примеры unmatched:")
        for item in not_found_examples:
            print(f"  - {item}")
    print(
        "Tennis diagnostics | "
        f"pending={tennis_pending} | with_result={tennis_result_ready} | "
        f"close_candidates={tennis_closed_candidates} | "
        f"no_match_score={tennis_reason_counts['no_match_score']} | "
        f"no_result_source={tennis_reason_counts['no_result_source']} | "
        f"mapping_failed={tennis_reason_counts['mapping_failed']} | "
        f"match_not_finished={tennis_reason_counts['match_not_finished']}"
    )

    finished_pending_after = get_finished_pending_count(conn)
    pending_bets_after = get_pending_bet_count(conn)

    if run_settler and not dry_run and finished_pending_after > 0:
        print(f"pending на finished матчах перед закрытием: {finished_pending_after}")
        run_settler_now()
        pending_bets_after = get_pending_bet_count(conn)

    closed_bets = max(0, pending_bets_before - pending_bets_after)
    print(
        "Settlement result | "
        f"closed_bets={closed_bets} | pending_bets_after={pending_bets_after} | "
        f"finished_pending_after={finished_pending_after}"
    )

    conn.close()

    if not_found > 0:
        print(f"\n⏳ {not_found} матчей ещё не завершены или результат ещё не найден.")
        print("Запусти позже: python updater_results.py --settle")


def main():
    ap = argparse.ArgumentParser(description="Обновляет результаты матчей и закрывает ставки")
    ap.add_argument("--dry-run", action="store_true", help="Только показывает, не пишет в БД")
    ap.add_argument("--settle", action="store_true", help="После обновления запустить settler.py")
    ap.add_argument("--debug-tennis", action="store_true", help="Подробная диагностика tennis settlement")
    args = ap.parse_args()

    print("🔄 BETAGENT — updater_results.py")
    print("=" * 50)
    update_results(dry_run=args.dry_run, run_settler=args.settle, debug_tennis=args.debug_tennis)
    print("\nСледующий шаг:")
    print("  python settler.py   (если не использовал --settle)")
    print("  python agent_handoff_v7.py --sport hockey --limit 11")


if __name__ == "__main__":
    main()
