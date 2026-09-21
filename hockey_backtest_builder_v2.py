#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterable


@dataclass
class Match:
    id: int
    league: str
    match_date: str  # expected YYYY-MM-DD
    match_time: Optional[str]
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]
    result_raw: Optional[str]
    periods_raw: Optional[str]
    result_type: Optional[str]
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    odds_total_over: Optional[float]
    odds_total_under: Optional[float]
    total_line: Optional[float]


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
    result_final TEXT,
    regulation_home_score INTEGER,
    regulation_away_score INTEGER,
    result_regulation TEXT,
    result_type TEXT,

    odds_home REAL,
    odds_draw REAL,
    odds_away REAL,
    odds_total_over REAL,
    odds_total_under REAL,
    total_line REAL,
    market_prob_home REAL,
    market_prob_draw REAL,
    market_prob_away REAL,
    market_prob_over REAL,
    market_prob_under REAL,

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

CREATE_HYP_SQL = """
CREATE TABLE IF NOT EXISTS backtest_hockey_hypothesis_results (
    hypothesis_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    split_key TEXT,
    bets INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    pushes INTEGER NOT NULL,
    hit_rate REAL,
    avg_odds REAL,
    profit_units REAL,
    roi REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (hypothesis_name, market_type, split_key)
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


class HypothesisTracker:
    def __init__(self):
        self.rows = []

    def add(self, hypothesis_name: str, market_type: str, split_key: str, won: bool, odds: Optional[float]):
        if odds is None or odds <= 1.0:
            return
        profit = (odds - 1.0) if won else -1.0
        self.rows.append((hypothesis_name, market_type, split_key, 1, 1 if won else 0, 0 if won else 1, 0, odds, profit))

    def summarize(self):
        agg = defaultdict(lambda: {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "odds_sum": 0.0, "profit": 0.0})
        for hyp, mkt, split_key, bets, wins, losses, pushes, odds, profit in self.rows:
            rec = agg[(hyp, mkt, split_key)]
            rec["bets"] += bets
            rec["wins"] += wins
            rec["losses"] += losses
            rec["pushes"] += pushes
            rec["odds_sum"] += odds
            rec["profit"] += profit
        out = []
        for (hyp, mkt, split_key), rec in agg.items():
            bets = rec["bets"]
            hit_rate = rec["wins"] / bets if bets else None
            avg_odds = rec["odds_sum"] / bets if bets else None
            roi = rec["profit"] / bets if bets else None
            out.append((hyp, mkt, split_key, bets, rec["wins"], rec["losses"], rec["pushes"], hit_rate, avg_odds, rec["profit"], roi))
        return sorted(out, key=lambda x: (x[0], x[2] or ""))



def parse_dt(date_text: str, time_text: Optional[str]) -> datetime:
    raw = f"{date_text} {time_text or '00:00'}"
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:len(fmt.replace("%Y","0000").replace("%m","00").replace("%d","00").replace("%H","00").replace("%M","00"))], fmt)
        except Exception:
            pass
    raise ValueError(f"Cannot parse date: {raw!r}")



def season_key_from_dt(dt: datetime) -> str:
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



def market_probs(*odds_values):
    vals = []
    for x in odds_values:
        vals.append((1 / x) if x and x > 1e-9 else None)
    if all(v is None for v in vals):
        return tuple(None for _ in odds_values)
    s = sum(v for v in vals if v is not None)
    if not s:
        return tuple(None for _ in odds_values)
    return tuple((v / s) if v is not None else None for v in vals)



def summarize_form(items: Iterable[dict]):
    items = list(items)
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



def parse_regulation_scores(periods_raw: Optional[str], home_final: Optional[int], away_final: Optional[int], result_type: Optional[str]):
    if home_final is None or away_final is None:
        return None, None
    if not periods_raw:
        return home_final, away_final

    pairs = []
    for part in periods_raw.split(','):
        part = part.strip()
        if ':' not in part:
            continue
        try:
            h, a = [int(x.strip()) for x in part.split(':', 1)]
            pairs.append((h, a))
        except Exception:
            continue

    if len(pairs) >= 3:
        reg_home = sum(h for h, _ in pairs[:3])
        reg_away = sum(a for _, a in pairs[:3])
        return reg_home, reg_away

    if result_type == 'regular':
        return home_final, away_final
    return None, None



def fetch_matches(conn) -> list[Match]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, league, match_date, match_time, home_team, away_team,
               home_score, away_score, result_raw, periods_raw, result_type,
               odds_home, odds_draw, odds_away,
               odds_total_over, odds_total_under, total_line
        FROM backtest_hockey_matches
        WHERE home_team IS NOT NULL
          AND away_team IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY match_date, COALESCE(match_time, '00:00'), league, home_team, away_team, id
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
        print(f"{r['cid']:>2} | {r['name']:<20} | {r['type']}")

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

    print("\n=== Top leagues ===")
    for r in conn.execute(
        """
        SELECT league, COUNT(*) cnt
        FROM backtest_hockey_matches
        GROUP BY league
        ORDER BY cnt DESC, league
        LIMIT 20
        """
    ):
        print(f"{r['cnt']:>5} | {r['league']}")



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
            home_score, away_score, result_final, regulation_home_score, regulation_away_score, result_regulation, result_type,
            odds_home, odds_draw, odds_away, odds_total_over, odds_total_under, total_line,
            market_prob_home, market_prob_draw, market_prob_away, market_prob_over, market_prob_under,
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
        ) VALUES (
            ?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,
            ?,?,?,?,?,?,
            ?,?,?,?,?,?,
            ?,?,?,?,
            ?,?,?,?,
            ?,?,?,?
        )
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

        ranking = sorted(
            team_states.items(),
            key=lambda kv: (
                kv[1].points,
                (kv[1].gf - kv[1].ga),
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
        market_over, market_under = market_probs(m.odds_total_over, m.odds_total_under)

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

        reg_home_score, reg_away_score = parse_regulation_scores(m.periods_raw, m.home_score, m.away_score, m.result_type)
        result_regulation = result_1x2(reg_home_score, reg_away_score)
        result_final = result_1x2(m.home_score, m.away_score)

        row = (
            m.id, m.league, season_key, m.match_date, m.match_time, m.home_team, m.away_team,
            m.home_score, m.away_score, result_final, reg_home_score, reg_away_score, result_regulation, m.result_type,
            m.odds_home, m.odds_draw, m.odds_away, m.odds_total_over, m.odds_total_under, m.total_line,
            market_home, market_draw, market_away, market_over, market_under,
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

        if reg_home_score is not None and reg_away_score is not None:
            if reg_home_score > reg_away_score:
                h_res = 'win'; a_res = 'loss'; h_pts, a_pts = 3, 0
            elif reg_home_score < reg_away_score:
                h_res = 'loss'; a_res = 'win'; h_pts, a_pts = 0, 3
            else:
                h_res = 'draw'; a_res = 'draw'; h_pts = a_pts = 1

            hs.gp += 1; hs.gf += reg_home_score; hs.ga += reg_away_score; hs.points += h_pts
            hs.home_gp += 1; hs.home_points += h_pts; hs.last_played = dt
            if h_res == 'win': hs.wins += 1
            elif h_res == 'draw': hs.draws += 1
            else: hs.losses += 1
            hs.last5.append({'points': h_pts, 'gd': reg_home_score - reg_away_score, 'result': h_res})
            hs.last10.append({'points': h_pts, 'gd': reg_home_score - reg_away_score, 'result': h_res})

            aw.gp += 1; aw.gf += reg_away_score; aw.ga += reg_home_score; aw.points += a_pts
            aw.away_gp += 1; aw.away_points += a_pts; aw.last_played = dt
            if a_res == 'win': aw.wins += 1
            elif a_res == 'draw': aw.draws += 1
            else: aw.losses += 1
            aw.last5.append({'points': a_pts, 'gd': reg_away_score - reg_home_score, 'result': a_res})
            aw.last10.append({'points': a_pts, 'gd': reg_away_score - reg_home_score, 'result': a_res})

            h2h.last5.append({'perspective_home_team': m.home_team, 'result': h_res, 'gd': reg_home_score - reg_away_score})

    conn.commit()
    logging.info("Inserted features rows: %s", inserted)



def scan_hypotheses(conn):
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_HYP_SQL)
    conn.execute("DELETE FROM backtest_hockey_hypothesis_results")
    tracker = HypothesisTracker()

    rows = conn.execute(
        """
        SELECT *
        FROM backtest_hockey_features
        WHERE result_regulation IS NOT NULL
        ORDER BY match_date, COALESCE(match_time, '00:00'), match_id
        """
    ).fetchall()

    for r in rows:
        league = (r['league'] or '').lower()
        is_nhl = 'нхл' in league or 'nhl' in league
        is_khl = 'кхл' in league

        # Hypothesis 1: NHL home moneyline in the proven odds zone with strength edge
        if (
            is_nhl
            and r['odds_home'] is not None and 1.80 <= r['odds_home'] <= 2.19
            and (r['strength_diff_ppg'] is not None and r['strength_diff_ppg'] >= 0)
            and (r['strength_diff_form5'] is not None and r['strength_diff_form5'] >= 0)
        ):
            tracker.add('NHL_HOME_180_219_STRENGTH', '1x2_home', r['season_key'], r['result_regulation'] == 'home', r['odds_home'])

        # Hypothesis 2: NHL any side in 1.80-2.19 but only with aligned ppg + form edge
        if (
            is_nhl and r['odds_home'] is not None and 1.80 <= r['odds_home'] <= 2.19
            and (r['strength_diff_ppg'] is not None and r['strength_diff_ppg'] > 0)
            and (r['strength_diff_form10'] is not None and r['strength_diff_form10'] > 0)
        ):
            tracker.add('NHL_HOME_180_219_FORM10', '1x2_home', r['season_key'], r['result_regulation'] == 'home', r['odds_home'])
        if (
            is_nhl and r['odds_away'] is not None and 1.80 <= r['odds_away'] <= 2.19
            and (r['strength_diff_ppg'] is not None and r['strength_diff_ppg'] < 0)
            and (r['strength_diff_form10'] is not None and r['strength_diff_form10'] < 0)
        ):
            tracker.add('NHL_AWAY_180_219_FORM10', '1x2_away', r['season_key'], r['result_regulation'] == 'away', r['odds_away'])

        # Hypothesis 3: KHL away dogs 2.80+ are bad and should be faded/skipped.
        # We store the performance of taking them to prove the negative hypothesis.
        if is_khl and r['odds_away'] is not None and r['odds_away'] >= 2.80:
            tracker.add('KHL_AWAY_DOGS_280_PLUS_BAD', '1x2_away', r['season_key'], r['result_regulation'] == 'away', r['odds_away'])

        # Hypothesis 4: Home rest edge + moderate odds.
        if (
            r['odds_home'] is not None and 1.80 <= r['odds_home'] <= 2.40
            and (r['fatigue_edge'] is not None and r['fatigue_edge'] >= 1.0)
            and (r['strength_diff_ppg'] is not None and r['strength_diff_ppg'] >= 0)
        ):
            tracker.add('HOME_REST_EDGE_180_240', '1x2_home', r['season_key'], r['result_regulation'] == 'home', r['odds_home'])

        # Hypothesis 5: Totals under in lower-total games if line exists and teams defensively stronger.
        if (
            r['total_line'] is not None and r['odds_total_under'] is not None
            and r['total_line'] <= 5.5
            and (r['home_ga_before'] is not None and r['away_ga_before'] is not None)
            and (r['home_gp_before'] or 0) >= 5 and (r['away_gp_before'] or 0) >= 5
            and ((r['home_ga_before'] / max(r['home_gp_before'], 1)) + (r['away_ga_before'] / max(r['away_gp_before'], 1))) <= 5.6
            and r['home_score'] is not None and r['away_score'] is not None
        ):
            won = (r['home_score'] + r['away_score']) < r['total_line']
            tracker.add('UNDER_DEFENSIVE_55_OR_LESS', 'total_under', r['season_key'], won, r['odds_total_under'])

    summaries = tracker.summarize()
    conn.executemany(
        """
        INSERT INTO backtest_hockey_hypothesis_results (
            hypothesis_name, market_type, split_key, bets, wins, losses, pushes,
            hit_rate, avg_odds, profit_units, roi
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        summaries,
    )
    conn.commit()

    print("\n=== Hypothesis results ===")
    for row in summaries:
        print({
            'hypothesis_name': row[0],
            'market_type': row[1],
            'split_key': row[2],
            'bets': row[3],
            'wins': row[4],
            'losses': row[5],
            'hit_rate': round(row[7], 4) if row[7] is not None else None,
            'avg_odds': round(row[8], 3) if row[8] is not None else None,
            'profit_units': round(row[9], 3),
            'roi': round(row[10], 4) if row[10] is not None else None,
        })



def parse_args():
    p = argparse.ArgumentParser(description='Inspect hockey historical DB, build features, and scan hypotheses')
    p.add_argument('--db', required=True, help='Path to SQLite DB')
    p.add_argument('--inspect', action='store_true', help='Inspect inserted data and schema')
    p.add_argument('--build-features', action='store_true', help='Build backtest_hockey_features table')
    p.add_argument('--scan-hypotheses', action='store_true', help='Run embedded hockey hypothesis scans')
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
        if args.scan_hypotheses:
            scan_hypotheses(conn)
        if not args.inspect and not args.build_features and not args.scan_hypotheses:
            print('Choose at least one action: --inspect, --build-features, --scan-hypotheses')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
