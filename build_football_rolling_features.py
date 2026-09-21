#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_football_rolling_features.py

Генерирует rolling-фичи для каждого матча из backtest_football_matches_betz.
Использует ТОЛЬКО данные, доступные ДО матча (строгий time split).

Фичи на команду (home/away):
  - form_pts_5      — очки за последние 5 матчей (W=3, D=1, L=0)
  - form_gf_5       — голы забито за последние 5
  - form_ga_5       — голы пропущено за последние 5
  - form_btts_5     — обе забили в N из последних 5
  - winrate_home    — winrate хозяев дома (последние 10 дома)
  - winrate_away    — winrate гостей в гостях (последние 10 в гостях)
  - goals_home_avg  — средние голы хозяев дома (последние 10)
  - goals_away_avg  — средние голы гостей в гостях (последние 10)

Cross-фичи:
  - form_diff       — разница очков (home - away)
  - goals_diff      — разница голов
  - h2h_home_wins   — победы хозяев в последних 5 очных матчах
  - h2h_btts_rate   — BTTS rate в последних 5 очных

Сохраняет в таблицу football_rolling_features (SQLite).

Запуск:
  python build_football_rolling_features.py
  python build_football_rolling_features.py --db /path/to/betagent.db
  python build_football_rolling_features.py --min-matches 3 --window 5
"""

import os
import sqlite3
import argparse
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

DB_PATH = os.getenv("BETAGENT_DB", "betagent.db")

# Фильтр мусорных лиг — исключаем всё что не профессиональный футбол
BLACKLIST_PATTERNS = [
    "женщин", "women", "резерв", "reserve", "юнош", "youth",
    "молодеж", "u19", "u20", "u21", "u23", "товарищ", "friendly",
    "6x6", "студен", "любител", "8x8", "пляж", "beach", "мини",
    "futsal", "футзал", "ампутантов", "слепых", "инвалид",
]

def is_blacklisted(league: str) -> bool:
    if not league:
        return True
    l = league.lower()
    return any(p in l for p in BLACKLIST_PATTERNS)


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS football_rolling_features")
    conn.execute("""
        CREATE TABLE football_rolling_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            source_match_id TEXT,
            league TEXT,
            country TEXT,
            competition TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,

            -- Результат матча
            home_score INTEGER,
            away_score INTEGER,
            result TEXT,           -- H/D/A
            total_goals INTEGER,
            btts INTEGER,          -- 1/0

            -- Коэффициенты
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            odds_btts_yes REAL,
            odds_btts_no REAL,
            odds_total_over REAL,
            odds_total_under REAL,
            total_line REAL,

            -- Rolling фичи — хозяева (все матчи, окно 5)
            home_form_pts_5 REAL,
            home_form_gf_5 REAL,
            home_form_ga_5 REAL,
            home_form_btts_5 REAL,
            home_form_n_5 INTEGER,

            -- Rolling фичи — хозяева дома (окно 10)
            home_home_winrate_10 REAL,
            home_home_gf_10 REAL,
            home_home_ga_10 REAL,
            home_home_n_10 INTEGER,

            -- Rolling фичи — гости (все матчи, окно 5)
            away_form_pts_5 REAL,
            away_form_gf_5 REAL,
            away_form_ga_5 REAL,
            away_form_btts_5 REAL,
            away_form_n_5 INTEGER,

            -- Rolling фичи — гости в гостях (окно 10)
            away_away_winrate_10 REAL,
            away_away_gf_10 REAL,
            away_away_ga_10 REAL,
            away_away_n_10 INTEGER,

            -- H2H (последние 5 очных)
            h2h_home_wins REAL,
            h2h_draws REAL,
            h2h_away_wins REAL,
            h2h_btts_rate REAL,
            h2h_avg_goals REAL,
            h2h_n INTEGER,

            -- Cross-фичи
            form_pts_diff REAL,    -- home_form_pts_5 - away_form_pts_5
            gf_diff REAL,          -- home_form_gf_5 - away_form_gf_5
            home_winrate_diff REAL, -- home_home_winrate - away_away_winrate

            -- Маржа букмекера
            margin_1x2 REAL,
            margin_btts REAL,

            -- Метаданные
            has_odds_1x2 INTEGER,
            has_odds_btts INTEGER,
            has_odds_total INTEGER,
            has_form_home INTEGER,  -- есть ли хоть 3 матча формы
            has_form_away INTEGER,

            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_frf_league
        ON football_rolling_features(league, match_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_frf_match_id
        ON football_rolling_features(match_id)
    """)
    conn.commit()
    print("✅ Таблица football_rolling_features создана")


def load_matches(conn: sqlite3.Connection) -> List[Dict]:
    """Загружаем все матчи с результатами, сортируем по дате."""
    rows = conn.execute("""
        SELECT
            id, source_match_id, league, country, competition,
            match_date, home_team, away_team,
            home_score, away_score,
            odds_home, odds_draw, odds_away,
            odds_btts_yes, odds_btts_no,
            odds_total_over, odds_total_under, total_line
        FROM backtest_football_matches_betz
        WHERE home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND home_team IS NOT NULL
          AND away_team IS NOT NULL
        ORDER BY match_date ASC, id ASC
    """).fetchall()
    return [dict(r) for r in rows]


def calc_margin(p1: Optional[float], p2: Optional[float],
                p3: Optional[float] = None) -> Optional[float]:
    """Маржа букмекера из коэффициентов."""
    try:
        if p3 is not None:
            return (1/p1 + 1/p2 + 1/p3) - 1
        return (1/p1 + 1/p2) - 1
    except (TypeError, ZeroDivisionError):
        return None


def rolling_team_stats(history: List[Dict], before_date: str,
                       window: int = 5) -> Dict:
    """
    Считаем rolling stats для команды по всем матчам (home + away).
    history — список {'date', 'gf', 'ga', 'is_home'}, отсортированный по дате.
    Берём последние `window` матчей СТРОГО до before_date.
    """
    past = [h for h in history if h['date'] < before_date]
    past = past[-window:]  # последние N

    n = len(past)
    if n == 0:
        return {'pts': None, 'gf': None, 'ga': None, 'btts': None, 'n': 0}

    pts_total = 0
    gf_total = 0
    ga_total = 0
    btts_total = 0

    for m in past:
        gf = m['gf']
        ga = m['ga']
        gf_total += gf
        ga_total += ga
        if gf > ga:
            pts_total += 3
        elif gf == ga:
            pts_total += 1
        if gf > 0 and ga > 0:
            btts_total += 1

    return {
        'pts': round(pts_total / n, 3),
        'gf': round(gf_total / n, 3),
        'ga': round(ga_total / n, 3),
        'btts': round(btts_total / n, 3),
        'n': n,
    }


def rolling_venue_stats(history: List[Dict], before_date: str,
                        is_home: bool, window: int = 10) -> Dict:
    """
    Winrate и голы только дома (is_home=True) или только в гостях (is_home=False).
    """
    past = [h for h in history if h['date'] < before_date and h['is_home'] == is_home]
    past = past[-window:]

    n = len(past)
    if n == 0:
        return {'winrate': None, 'gf': None, 'ga': None, 'n': 0}

    wins = sum(1 for m in past if m['gf'] > m['ga'])
    gf_total = sum(m['gf'] for m in past)
    ga_total = sum(m['ga'] for m in past)

    return {
        'winrate': round(wins / n, 3),
        'gf': round(gf_total / n, 3),
        'ga': round(ga_total / n, 3),
        'n': n,
    }


def rolling_h2h(h2h_history: List[Dict], before_date: str,
                home_team: str, window: int = 5) -> Dict:
    """
    H2H статистика между двумя командами.
    h2h_history — матчи между этими командами в любую сторону.
    """
    past = [h for h in h2h_history if h['date'] < before_date]
    past = past[-window:]

    n = len(past)
    if n == 0:
        return {
            'home_wins': None, 'draws': None, 'away_wins': None,
            'btts_rate': None, 'avg_goals': None, 'n': 0
        }

    home_wins = 0
    draws = 0
    away_wins = 0
    btts = 0
    goals = 0

    for m in past:
        # нормализуем: "home" — та команда которая сейчас хозяин
        if m['team1'] == home_team:
            gf, ga = m['gf1'], m['gf2']
        else:
            gf, ga = m['gf2'], m['gf1']

        if gf > ga:
            home_wins += 1
        elif gf == ga:
            draws += 1
        else:
            away_wins += 1

        if gf > 0 and ga > 0:
            btts += 1
        goals += gf + ga

    return {
        'home_wins': round(home_wins / n, 3),
        'draws': round(draws / n, 3),
        'away_wins': round(away_wins / n, 3),
        'btts_rate': round(btts / n, 3),
        'avg_goals': round(goals / n, 3),
        'n': n,
    }


def build_features(matches: List[Dict],
                   min_form_matches: int = 0) -> List[Dict]:
    """
    Основная функция — строим фичи для каждого матча.
    Strict time split: используем только матчи ДО текущего.
    """
    # Индексы для быстрого поиска
    # team_history[team] = [{date, gf, ga, is_home}, ...]
    team_history: Dict[str, List[Dict]] = defaultdict(list)
    # h2h_index[(t1,t2)] = [{date, team1, gf1, gf2}, ...]  (t1 < t2 лексикограф.)
    h2h_index: Dict[Tuple, List[Dict]] = defaultdict(list)

    # Проходим матчи В ХРОНОЛОГИЧЕСКОМ порядке
    # Для каждого матча — сначала считаем фичи (из прошлого), потом добавляем в историю
    results = []
    skipped_blacklist = 0
    skipped_no_result = 0

    for i, m in enumerate(matches):
        league = m.get('league', '')

        if is_blacklisted(league):
            skipped_blacklist += 1
            # Всё равно добавляем в историю для других команд
            _add_to_history(team_history, h2h_index, m)
            continue

        home_team = m['home_team']
        away_team = m['away_team']
        match_date = m['match_date']
        home_score = m['home_score']
        away_score = m['away_score']

        # === Считаем фичи ДО матча ===

        # Форма команд (все матчи)
        h_form = rolling_team_stats(team_history[home_team], match_date, window=5)
        a_form = rolling_team_stats(team_history[away_team], match_date, window=5)

        # Venue stats
        h_home = rolling_venue_stats(team_history[home_team], match_date,
                                     is_home=True, window=10)
        a_away = rolling_venue_stats(team_history[away_team], match_date,
                                     is_home=False, window=10)

        # H2H
        h2h_key = tuple(sorted([home_team, away_team]))
        h2h = rolling_h2h(h2h_index[h2h_key], match_date, home_team, window=5)

        # Результат матча
        if home_score > away_score:
            result = 'H'
        elif home_score == away_score:
            result = 'D'
        else:
            result = 'A'

        total_goals = home_score + away_score
        btts = 1 if home_score > 0 and away_score > 0 else 0

        # Маржи
        oh = m.get('odds_home')
        od = m.get('odds_draw')
        oa = m.get('odds_away')
        oby = m.get('odds_btts_yes')
        obn = m.get('odds_btts_no')

        margin_1x2 = calc_margin(oh, od, oa)
        margin_btts = calc_margin(oby, obn)

        # Cross-фичи
        form_pts_diff = None
        if h_form['pts'] is not None and a_form['pts'] is not None:
            form_pts_diff = round(h_form['pts'] - a_form['pts'], 3)

        gf_diff = None
        if h_form['gf'] is not None and a_form['gf'] is not None:
            gf_diff = round(h_form['gf'] - a_form['gf'], 3)

        winrate_diff = None
        if h_home['winrate'] is not None and a_away['winrate'] is not None:
            winrate_diff = round(h_home['winrate'] - a_away['winrate'], 3)

        # Флаги наличия данных
        has_odds_1x2 = 1 if (oh and od and oa) else 0
        has_odds_btts = 1 if (oby and obn) else 0
        has_odds_total = 1 if m.get('odds_total_over') and m.get('odds_total_under') else 0
        has_form_home = 1 if h_form['n'] >= min_form_matches else 0
        has_form_away = 1 if a_form['n'] >= min_form_matches else 0

        row = {
            'match_id': m['id'],
            'source_match_id': m.get('source_match_id'),
            'league': league,
            'country': m.get('country'),
            'competition': m.get('competition'),
            'match_date': match_date,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': home_score,
            'away_score': away_score,
            'result': result,
            'total_goals': total_goals,
            'btts': btts,
            # Коэффициенты
            'odds_home': oh,
            'odds_draw': od,
            'odds_away': oa,
            'odds_btts_yes': oby,
            'odds_btts_no': obn,
            'odds_total_over': m.get('odds_total_over'),
            'odds_total_under': m.get('odds_total_under'),
            'total_line': m.get('total_line'),
            # Home form (все матчи)
            'home_form_pts_5': h_form['pts'],
            'home_form_gf_5': h_form['gf'],
            'home_form_ga_5': h_form['ga'],
            'home_form_btts_5': h_form['btts'],
            'home_form_n_5': h_form['n'],
            # Home venue stats
            'home_home_winrate_10': h_home['winrate'],
            'home_home_gf_10': h_home['gf'],
            'home_home_ga_10': h_home['ga'],
            'home_home_n_10': h_home['n'],
            # Away form
            'away_form_pts_5': a_form['pts'],
            'away_form_gf_5': a_form['gf'],
            'away_form_ga_5': a_form['ga'],
            'away_form_btts_5': a_form['btts'],
            'away_form_n_5': a_form['n'],
            # Away venue stats
            'away_away_winrate_10': a_away['winrate'],
            'away_away_gf_10': a_away['gf'],
            'away_away_ga_10': a_away['ga'],
            'away_away_n_10': a_away['n'],
            # H2H
            'h2h_home_wins': h2h['home_wins'],
            'h2h_draws': h2h['draws'],
            'h2h_away_wins': h2h['away_wins'],
            'h2h_btts_rate': h2h['btts_rate'],
            'h2h_avg_goals': h2h['avg_goals'],
            'h2h_n': h2h['n'],
            # Cross
            'form_pts_diff': form_pts_diff,
            'gf_diff': gf_diff,
            'home_winrate_diff': winrate_diff,
            # Маржи
            'margin_1x2': round(margin_1x2, 4) if margin_1x2 is not None else None,
            'margin_btts': round(margin_btts, 4) if margin_btts is not None else None,
            # Флаги
            'has_odds_1x2': has_odds_1x2,
            'has_odds_btts': has_odds_btts,
            'has_odds_total': has_odds_total,
            'has_form_home': has_form_home,
            'has_form_away': has_form_away,
        }
        results.append(row)

        # === После фич — добавляем в историю ===
        _add_to_history(team_history, h2h_index, m)

        if (i + 1) % 5000 == 0:
            print(f"  Обработано: {i+1}/{len(matches)} матчей, "
                  f"сохранено: {len(results)}, пропущено (blacklist): {skipped_blacklist}")

    print(f"\n✅ Итого:")
    print(f"   Матчей всего:      {len(matches)}")
    print(f"   Пропущено (blacklist): {skipped_blacklist}")
    print(f"   Сохранено фич:     {len(results)}")

    return results


def _add_to_history(team_history, h2h_index, m):
    """Добавляем матч в историю команд и H2H."""
    home_team = m['home_team']
    away_team = m['away_team']
    match_date = m['match_date']
    hs = m.get('home_score')
    as_ = m.get('away_score')

    if hs is None or as_ is None:
        return

    team_history[home_team].append({
        'date': match_date, 'gf': hs, 'ga': as_, 'is_home': True
    })
    team_history[away_team].append({
        'date': match_date, 'gf': as_, 'ga': hs, 'is_home': False
    })

    h2h_key = tuple(sorted([home_team, away_team]))
    h2h_index[h2h_key].append({
        'date': match_date,
        'team1': home_team, 'gf1': hs, 'gf2': as_
    })


def save_features(conn: sqlite3.Connection, rows: List[Dict]) -> None:
    """Сохраняем в БД батчами."""
    if not rows:
        print("⚠️  Нет данных для сохранения")
        return

    cols = [c for c in rows[0].keys()]
    placeholders = ', '.join(['?' for _ in cols])
    col_names = ', '.join(cols)
    sql = f"INSERT INTO football_rolling_features ({col_names}) VALUES ({placeholders})"

    batch_size = 1000
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        values = [[r.get(c) for c in cols] for r in batch]
        conn.executemany(sql, values)
        conn.commit()
        total += len(batch)

    print(f"💾 Сохранено {total} строк в football_rolling_features")


def print_summary(conn: sqlite3.Connection) -> None:
    """Краткая статистика по результату."""
    print("\n📊 Статистика по таблице football_rolling_features:")

    total = conn.execute("SELECT COUNT(*) FROM football_rolling_features").fetchone()[0]
    print(f"   Всего строк: {total:,}")

    with_form = conn.execute("""
        SELECT COUNT(*) FROM football_rolling_features
        WHERE has_form_home=1 AND has_form_away=1
    """).fetchone()[0]
    print(f"   С формой обеих команд: {with_form:,} ({100*with_form//total if total else 0}%)")

    with_btts = conn.execute("""
        SELECT COUNT(*) FROM football_rolling_features WHERE has_odds_btts=1
    """).fetchone()[0]
    print(f"   С коэф BTTS: {with_btts:,} ({100*with_btts//total if total else 0}%)")

    print("\n   Топ-10 лиг по объёму:")
    rows = conn.execute("""
        SELECT competition, country, COUNT(*) as n,
               MIN(match_date) as from_d, MAX(match_date) as to_d
        FROM football_rolling_features
        GROUP BY competition, country
        ORDER BY n DESC
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"   {r[0]} ({r[1]}): {r[2]:,} матчей [{r[3]} — {r[4]}]")

    print("\n   Покрытие по годам:")
    rows = conn.execute("""
        SELECT substr(match_date,1,4) as yr, COUNT(*) as n,
               SUM(has_form_home * has_form_away) as with_form
        FROM football_rolling_features
        GROUP BY yr ORDER BY yr
    """).fetchall()
    for r in rows:
        pct = 100 * r[2] // r[1] if r[1] else 0
        print(f"   {r[0]}: {r[1]:,} матчей, с формой: {r[2]:,} ({pct}%)")


def main():
    ap = argparse.ArgumentParser(
        description="Генерация rolling-фич для football_rolling_features"
    )
    ap.add_argument("--db", default=DB_PATH, help="Путь к betagent.db")
    ap.add_argument("--min-matches", type=int, default=0,
                    help="Мин. матчей формы для флага has_form (default: 0 = все)")
    ap.add_argument("--no-blacklist", action="store_true",
                    help="Не фильтровать мусорные лиги")
    args = ap.parse_args()

    if args.no_blacklist:
        BLACKLIST_PATTERNS.clear()

    print(f"🚀 build_football_rolling_features.py")
    print(f"   DB: {args.db}")
    print(f"   Blacklist: {'выкл' if args.no_blacklist else 'вкл'} ({len(BLACKLIST_PATTERNS)} паттернов)")
    print(f"   min_form_matches для флага: {args.min_matches}")

    conn = get_conn(args.db)

    print("\n📥 Загружаем матчи...")
    t0 = datetime.now()
    matches = load_matches(conn)
    print(f"   Загружено: {len(matches):,} матчей за {(datetime.now()-t0).seconds}с")

    print("\n🔧 Создаём таблицу...")
    ensure_table(conn)

    print("\n⚙️  Строим фичи...")
    t1 = datetime.now()
    rows = build_features(matches, min_form_matches=args.min_matches)
    elapsed = (datetime.now() - t1).seconds
    print(f"   Готово за {elapsed}с")

    print("\n💾 Сохраняем...")
    save_features(conn, rows)

    print_summary(conn)
    conn.close()
    print("\n✅ Готово! Таблица football_rolling_features обновлена.")
    print("   Следующий шаг: запусти league_edge_scanner.py для поиска эджа по лигам")


if __name__ == "__main__":
    main()
