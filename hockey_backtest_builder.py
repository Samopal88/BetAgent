#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import math
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Match:
    id: int
    league: str
    match_date: str
    match_time: Optional[str]
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]


CREATE_FEATURES_SQL = """
CREATE TABLE IF NOT EXISTS backtest_hockey_features (
    match_id INTEGER PRIMARY KEY,
    league TEXT,
    season_key TEXT,
    match_date TEXT,
    match_time TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    result_1x2 TEXT,

    odds_home REAL,
    odds_draw REAL,
    odds_away REAL,
    market_prob_home REAL,
    market_prob_draw REAL,
    market_prob_away REAL,

    home_gp_before INTEGER,
    home_points_before INTEGER,
    home_gf_before INTEGER,
    home_ga_before INTEGER,
    home_gd_before INTEGER,
    home_ppg_before REAL,
    home_winrate_before REAL,
    home_drawrate_before REAL,
    home_lossrate_before REAL,
    home_home_ppg_before REAL,

    away_gp_before INTEGER,
    away_points_before INTEGER,
    away_gf_before INTEGER,
    away_ga_before INTEGER,
    away_gd_before INTEGER,
    away_ppg_before REAL,
    away_winrate_before REAL,
    away_drawrate_before REAL,
    away_lossrate_before REAL,
    away_away_ppg_before REAL,

    table_pos_home_before INTEGER,
    table_pos_away_before INTEGER,
    table_gap_points_before INTEGER,
    table_gap_gd_before INTEGER,

    form5_home_points REAL,
    form5_home_gd REAL,
    form5_home_winrate REAL,
    form5_away_points REAL,
    form5_away_gd REAL,
    form5_away_winrate REAL,

    form10_home_points REAL,
    form10_home_gd REAL,
    form10_home_winrate REAL,
    form10_away_points REAL,
    form10_away_gd REAL,
    form10_away_winrate REAL,

    h2h5_home_wins INTEGER,
    h2h5_draws INTEGER,
    h2h5_away_wins INTEGER,
    h2h5_home_gd INTEGER,

    rest_days_home REAL,
    rest_days_away REAL,
    fatigue_edge REAL,

    home_advantage_ppg REAL,
    strength_diff_ppg REAL,
    strength_diff_form5 REAL,
    strength_diff_form10 REAL,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


class TeamState:
    def __init__(self):
        self.gp = 0
        self.wins = 0
        self.draws = 0
        self.losses = 0
        self.points = 0
        self.gf = 0
        self.ga = 0
        self.home_gp = 0
        self.home_points = 0
        self.away_gp = 0
        self.away_points = 0
        self.last_played: Optional[datetime] = None
        self.last5 = deque(maxlen=5)
        self.last10 = deque(maxlen=10)


class H2HState:
    def __init__(self):
        self.last5 = deque(maxlen=5)



def parse_dt(date_text: str, time_text: Optional[str]) -> datetime:
    raw = f"{date_text} {time_text or '00:00'}"
    return datetime.strptime(raw, "%d.%m.%Y %H:%M")



def season_key_from_dt(dt: datetime) -> str:
    # Для хоккея сезон обычно пересекает годы: Jul-Jun.
    if dt.month >= 7:
        return f"{dt.year}/{dt.year + 1}"
    return f"{dt.year - 1}/{dt.year}"



def result_1x2(home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return 'home'
    if home_score < away_score:
        return 'away'
    return 'draw'



def safe_div(a, b):
    return a / b if b else None



def market_probs(odds_home, odds_draw, odds_away):
    vals = []
    for x in (odds_home, odds_draw, odds_away):
        vals.append((1 / x) if x and x > 1e-9 else None)
    if all(v is None for v in vals):
        return None, None, None
    s = sum(v for v in vals if v is not None)
    if not s:
        return None, None, None
    return tuple((v / s) if v is not None else None for v in vals)



def summarize_form(items):
    if not items:
        return None, None, None
    pts = sum(x['points'] for x in items) / len(items)
    gd = sum(x['gd'] for x in items) / len(items)
    wr = sum(1 for x in items if x['result'] == 'win') / len(items)
    return pts, gd, wr



def rest_days(last_played: Optional[datetime], current_dt: datetime):
    if not last_played:
        return None
    return round((current_dt - last_played).total_seconds() / 86400, 3)



def fetch_matches(conn) -> list[Match]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, league, match_date, match_time, home_team, away_team,
               home_score, away_score, odds_home, odds_draw, odds_away
        FROM backtest_hockey_matches
        WHERE home_team IS NOT NULL
          AND away_team IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY substr(match_date, 7, 4) || '-' || substr(match_date, 4, 2) || '-' || substr(match_date, 1, 2),
                 COALESCE(match_time, '00:00'),
                 league, home_team, away_team, id
        """
    ).fetchall()
    return [Match(**dict(r)) for r in rows]



def inspect_db(conn):
    conn.row_factory = sqlite3.Row
    print("\n=== TABLES ===")
    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print(r['name'])

    print("\n=== backtest_hockey_matches schema ===")
    for r in conn.execute("PRAGMA table_info(backtest_hockey_matches)"):
        print(f"{r['cid']:>2} | {r['name']:<18} | {r['type']}")

    total = conn.execute("SELECT COUNT(*) FROM backtest_hockey_matches").fetchone()[0]
    print(f"\nRows in backtest_hockey_matches: {total}")

    stats = conn.execute(
        """
        SELECT MIN(match_date), MAX(match_date),
               COUNT(DISTINCT league), COUNT(DISTINCT home_team || '|' || away_team)
        FROM backtest_hockey_matches
        """
    ).fetchone()
    print(f"Date range: {stats[0]} .. {stats[1]}")
    print(f"Leagues: {stats[2]}")
    print(f"Unique pair keys: {stats[3]}")

    nulls = conn.execute(
        """
        SELECT
            SUM(CASE WHEN home_score IS NULL OR away_score IS NULL THEN 1 ELSE 0 END) AS missing_score,
            SUM(CASE WHEN odds_home IS NULL THEN 1 ELSE 0 END) AS missing_odds_home,
            SUM(CASE WHEN odds_draw IS NULL THEN 1 ELSE 0 END) AS missing_odds_draw,
            SUM(CASE WHEN odds_away IS NULL THEN 1 ELSE 0 END) AS missing_odds_away
        FROM backtest_hockey_matches
        """
    ).fetchone()
    print("Missing values:")
    print(f"  score: {nulls[0]}")
    print(f"  odds_home: {nulls[1]}")
    print(f"  odds_draw: {nulls[2]}")
    print(f"  odds_away: {nulls[3]}")

    print("\n=== Top leagues ===")
    for r in conn.execute(
        """
        SELECT league, COUNT(*) cnt
        FROM backtest_hockey_matches
        GROUP BY league
        ORDER BY cnt DESC, league
        LIMIT 25
        """
    ):
        print(f"{r['cnt']:>5} | {r['league']}")

    print("\n=== Sample rows ===")
    for r in conn.execute(
        """
        SELECT id, league, match_date, match_time, home_team, away_team,
               home_score, away_score, odds_home, odds_draw, odds_away
        FROM backtest_hockey_matches
        ORDER BY substr(match_date, 7, 4) || '-' || substr(match_date, 4, 2) || '-' || substr(match_date, 1, 2),
                 COALESCE(match_time, '00:00')
        LIMIT 10
        """
    ):
        print(dict(r))



def build_features(conn):
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_FEATURES_SQL)
    conn.execute("DELETE FROM backtest_hockey_features")
    matches = fetch_matches(conn)
    logging.info("Loaded matches: %s", len(matches))

    season_team_state = defaultdict(lambda: defaultdict(TeamState))
    season_h2h_state = defaultdict(lambda: defaultdict(H2HState))

    insert_sql = """
        INSERT INTO backtest_hockey_features (
            match_id, league, season_key, match_date, match_time, home_team, away_team,
            home_score, away_score, result_1x2,
            odds_home, odds_draw, odds_away,
            market_prob_home, market_prob_draw, market_prob_away,
            home_gp_before, home_points_before, home_gf_before, home_ga_before, home_gd_before,
            home_ppg_before, home_winrate_before, home_drawrate_before, home_lossrate_before, home_home_ppg_before,
            away_gp_before, away_points_before, away_gf_before, away_ga_before, away_gd_before,
            away_ppg_before, away_winrate_before, away_drawrate_before, away_lossrate_before, away_away_ppg_before,
            table_pos_home_before, table_pos_away_before, table_gap_points_before, table_gap_gd_before,
            form5_home_points, form5_home_gd, form5_home_winrate,
            form5_away_points, form5_away_gd, form5_away_winrate,
            form10_home_points, form10_home_gd, form10_home_winrate,
            form10_away_points, form10_away_gd, form10_away_winrate,
            h2h5_home_wins, h2h5_draws, h2h5_away_wins, h2h5_home_gd,
            rest_days_home, rest_days_away, fatigue_edge,
            home_advantage_ppg, strength_diff_ppg, strength_diff_form5, strength_diff_form10
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    inserted = 0
    for m in matches:
        dt = parse_dt(m.match_date, m.match_time)
        season_key = season_key_from_dt(dt)
        league_key = f"{m.league}__{season_key}"
        team_states = season_team_state[league_key]
        h2h_states = season_h2h_state[league_key]
        hs = team_states[m.home_team]
        aw = team_states[m.away_team]
        h2h_key = "||".join(sorted([m.home_team, m.away_team]))
        h2h = h2h_states[h2h_key]

        # table snapshot before match
        ranking = sorted(
            team_states.items(),
            key=lambda kv: (
                kv[1].points,
                kv[1].gp and (kv[1].gf - kv[1].ga),
                kv[1].gf,
                -kv[1].ga,
                kv[0],
            ),
            reverse=True,
        )
        pos_map = {team: idx + 1 for idx, (team, _) in enumerate(ranking)}
        table_pos_home = pos_map.get(m.home_team)
        table_pos_away = pos_map.get(m.away_team)

        market_home, market_draw, market_away = market_probs(m.odds_home, m.odds_draw, m.odds_away)

        home_form5_pts, home_form5_gd, home_form5_wr = summarize_form(hs.last5)
        away_form5_pts, away_form5_gd, away_form5_wr = summarize_form(aw.last5)
        home_form10_pts, home_form10_gd, home_form10_wr = summarize_form(hs.last10)
        away_form10_pts, away_form10_gd, away_form10_wr = summarize_form(aw.last10)

        h2h_home_wins = h2h_draws = h2h_away_wins = 0
        h2h_home_gd = 0
        for item in h2h.last5:
            if item['perspective_home_team'] == m.home_team:
                if item['result'] == 'win':
                    h2h_home_wins += 1
                elif item['result'] == 'draw':
                    h2h_draws += 1
                else:
                    h2h_away_wins += 1
                h2h_home_gd += item['gd']
            else:
                if item['result'] == 'loss':
                    h2h_home_wins += 1
                elif item['result'] == 'draw':
                    h2h_draws += 1
                else:
                    h2h_away_wins += 1
                h2h_home_gd -= item['gd']

        rd_home = rest_days(hs.last_played, dt)
        rd_away = rest_days(aw.last_played, dt)
        fatigue_edge = (rd_home - rd_away) if rd_home is not None and rd_away is not None else None

        home_ppg = safe_div(hs.points, hs.gp)
        away_ppg = safe_div(aw.points, aw.gp)
        home_winrate = safe_div(hs.wins, hs.gp)
        away_winrate = safe_div(aw.wins, aw.gp)
        home_drawrate = safe_div(hs.draws, hs.gp)
        away_drawrate = safe_div(aw.draws, aw.gp)
        home_lossrate = safe_div(hs.losses, hs.gp)
        away_lossrate = safe_div(aw.losses, aw.gp)
        home_home_ppg = safe_div(hs.home_points, hs.home_gp)
        away_away_ppg = safe_div(aw.away_points, aw.away_gp)

        row = (
            m.id, m.league, season_key, m.match_date, m.match_time, m.home_team, m.away_team,
            m.home_score, m.away_score, result_1x2(m.home_score, m.away_score),
            m.odds_home, m.odds_draw, m.odds_away,
            market_home, market_draw, market_away,
            hs.gp, hs.points, hs.gf, hs.ga, hs.gf - hs.ga,
            home_ppg, home_winrate, home_drawrate, home_lossrate, home_home_ppg,
            aw.gp, aw.points, aw.gf, aw.ga, aw.gf - aw.ga,
            away_ppg, away_winrate, away_drawrate, away_lossrate, away_away_ppg,
            table_pos_home, table_pos_away,
            (hs.points - aw.points) if hs.gp or aw.gp else None,
            ((hs.gf - hs.ga) - (aw.gf - aw.ga)) if hs.gp or aw.gp else None,
            home_form5_pts, home_form5_gd, home_form5_wr,
            away_form5_pts, away_form5_gd, away_form5_wr,
            home_form10_pts, home_form10_gd, home_form10_wr,
            away_form10_pts, away_form10_gd, away_form10_wr,
            h2h_home_wins, h2h_draws, h2h_away_wins, h2h_home_gd,
            rd_home, rd_away, fatigue_edge,
            (home_home_ppg - away_away_ppg) if home_home_ppg is not None and away_away_ppg is not None else None,
            (home_ppg - away_ppg) if home_ppg is not None and away_ppg is not None else None,
            (home_form5_pts - away_form5_pts) if home_form5_pts is not None and away_form5_pts is not None else None,
            (home_form10_pts - away_form10_pts) if home_form10_pts is not None and away_form10_pts is not None else None,
        )
        conn.execute(insert_sql, row)
        inserted += 1

        # update after storing features
        if m.home_score is not None and m.away_score is not None:
            if m.home_score > m.away_score:
                h_res = 'win'
                a_res = 'loss'
                h_pts, a_pts = 3, 0
            elif m.home_score < m.away_score:
                h_res = 'loss'
                a_res = 'win'
                h_pts, a_pts = 0, 3
            else:
                h_res = 'draw'
                a_res = 'draw'
                h_pts = a_pts = 1

            hs.gp += 1
            hs.gf += m.home_score
            hs.ga += m.away_score
            hs.points += h_pts
            hs.home_gp += 1
            hs.home_points += h_pts
            hs.last_played = dt
            if h_res == 'win': hs.wins += 1
            elif h_res == 'draw': hs.draws += 1
            else: hs.losses += 1
            hs.last5.append({'points': h_pts, 'gd': m.home_score - m.away_score, 'result': h_res})
            hs.last10.append({'points': h_pts, 'gd': m.home_score - m.away_score, 'result': h_res})

            aw.gp += 1
            aw.gf += m.away_score
            aw.ga += m.home_score
            aw.points += a_pts
            aw.away_gp += 1
            aw.away_points += a_pts
            aw.last_played = dt
            if a_res == 'win': aw.wins += 1
            elif a_res == 'draw': aw.draws += 1
            else: aw.losses += 1
            aw.last5.append({'points': a_pts, 'gd': m.away_score - m.home_score, 'result': a_res})
            aw.last10.append({'points': a_pts, 'gd': m.away_score - m.home_score, 'result': a_res})

            h2h.last5.append({
                'perspective_home_team': m.home_team,
                'result': h_res,
                'gd': m.home_score - m.away_score,
            })

    conn.commit()
    logging.info("Inserted features rows: %s", inserted)

    print("\n=== Features summary ===")
    cnt = conn.execute("SELECT COUNT(*) FROM backtest_hockey_features").fetchone()[0]
    print(f"Rows in backtest_hockey_features: {cnt}")
    for r in conn.execute(
        """
        SELECT match_id, league, season_key, match_date, home_team, away_team,
               table_pos_home_before, table_pos_away_before,
               strength_diff_ppg, strength_diff_form5, h2h5_home_wins, h2h5_away_wins
        FROM backtest_hockey_features
        ORDER BY match_id
        LIMIT 10
        """
    ):
        print(dict(r))



def parse_args():
    p = argparse.ArgumentParser(description='Inspect hockey historical DB and build backtest features')
    p.add_argument('--db', required=True, help='Path to SQLite DB')
    p.add_argument('--inspect', action='store_true', help='Inspect inserted data and schema')
    p.add_argument('--build-features', action='store_true', help='Build backtest_hockey_features table')
    return p.parse_args()



def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    conn = sqlite3.connect(args.db)
    try:
        if args.inspect:
            inspect_db(conn)
        if args.build_features:
            build_features(conn)
        if not args.inspect and not args.build_features:
            print('Choose at least one action: --inspect and/or --build-features')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
