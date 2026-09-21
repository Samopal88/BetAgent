#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import itertools
import logging
import math
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

RESULT_HOME = 'home'
RESULT_DRAW = 'draw'
RESULT_AWAY = 'away'

DEFAULT_STRATEGIES = [
    'ppg_core',
    'form5_momentum',
    'form10_stability',
    'table_rank',
    'rest_spot',
    'h2h_small',
    'home_ice',
    'balanced',
    'balanced_no_h2h',
    'underdog_hunter',
    'draw_tight',
]

DEFAULT_STAKE_MODES = ['flat_1000', 'pct_0.75', 'pct_1.0', 'pct_1.25', 'pct_1.5']

PRESET_GRIDS = {
    'quick': {
        'thresholds': [0.02, 0.03],
        'min_histories': [10],
        'strategies': ['h2h_small', 'balanced', 'ppg_core'],
        'stake_modes': ['flat_1000', 'pct_0.75', 'pct_1.0'],
    },
    'core': {
        'thresholds': [0.015, 0.02, 0.03],
        'min_histories': [5, 10],
        'strategies': ['h2h_small', 'balanced', 'balanced_no_h2h', 'ppg_core', 'table_rank'],
        'stake_modes': ['flat_1000', 'pct_0.75', 'pct_1.0', 'pct_1.25'],
    },
    'wide': {
        'thresholds': [0.015, 0.02, 0.03, 0.04],
        'min_histories': [5, 10, 15],
        'strategies': DEFAULT_STRATEGIES,
        'stake_modes': DEFAULT_STAKE_MODES,
    },
}


@dataclass
class BacktestSummary:
    strategy: str
    stake_mode: str
    threshold: float
    min_history: int
    bets: int
    hit_rate: float
    avg_odds: float
    net_profit: float
    roi: float
    max_drawdown: float
    max_drawdown_pct: float
    max_losing_streak: int
    ending_bankroll: float
    profitable_years: int
    total_years: int


class FeatureRow(dict):
    pass


class ComboAccumulator:
    def __init__(self) -> None:
        self.bets = 0
        self.stake = 0.0
        self.pnl = 0.0
        self.wins = 0
        self.odds_sum = 0.0

    def add(self, stake: float, pnl: float, won: int, odds: float) -> None:
        self.bets += 1
        self.stake += stake
        self.pnl += pnl
        self.wins += won
        self.odds_sum += odds

    def to_row(self, key: str) -> dict:
        roi = (self.pnl / self.stake) if self.stake else 0.0
        hit_rate = (self.wins / self.bets) if self.bets else 0.0
        avg_odds = (self.odds_sum / self.bets) if self.bets else 0.0
        return {
            'key': key,
            'bets': self.bets,
            'stake': round(self.stake, 2),
            'pnl': round(self.pnl, 2),
            'roi': roi,
            'hit_rate': hit_rate,
            'avg_odds': avg_odds,
        }


def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%d.%m.%Y")


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def nz(value, default=0.0):
    return default if value is None else value


def safe_div(a: float, b: float) -> Optional[float]:
    return (a / b) if b else None


def fetch_feature_rows(conn: sqlite3.Connection, min_history: int) -> List[FeatureRow]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT *
        FROM backtest_hockey_features
        WHERE result_1x2 IS NOT NULL
          AND odds_home IS NOT NULL
          AND odds_draw IS NOT NULL
          AND odds_away IS NOT NULL
          AND COALESCE(home_gp_before, 0) >= ?
          AND COALESCE(away_gp_before, 0) >= ?
        ORDER BY substr(match_date, 7, 4) || '-' || substr(match_date, 4, 2) || '-' || substr(match_date, 1, 2),
                 COALESCE(match_time, '00:00'),
                 league, home_team, away_team, match_id
        """,
        (min_history, min_history),
    ).fetchall()
    return [FeatureRow(dict(r)) for r in rows]


def z_strength_diff_ppg(r):
    return clamp(nz(r['strength_diff_ppg']) / 1.2, -2.5, 2.5)


def z_form5(r):
    return clamp(nz(r['strength_diff_form5']) / 1.0, -2.5, 2.5)


def z_form10(r):
    return clamp(nz(r['strength_diff_form10']) / 1.0, -2.5, 2.5)


def z_home_adv(r):
    return clamp(nz(r['home_advantage_ppg']) / 1.0, -2.0, 2.0)


def z_table_pos(r):
    h = r['table_pos_home_before']
    a = r['table_pos_away_before']
    if h is None or a is None:
        return 0.0
    return clamp((a - h) / 8.0, -2.0, 2.0)


def z_table_points(r):
    return clamp(nz(r['table_gap_points_before']) / 8.0, -2.0, 2.0)


def z_table_gd(r):
    return clamp(nz(r['table_gap_gd_before']) / 10.0, -2.0, 2.0)


def z_rest(r):
    return clamp(nz(r['fatigue_edge']) / 2.0, -2.0, 2.0)


def z_h2h(r):
    wins = nz(r['h2h5_home_wins'])
    losses = nz(r['h2h5_away_wins'])
    gd = nz(r['h2h5_home_gd'])
    return clamp((wins - losses) / 3.0 + gd / 8.0, -2.0, 2.0)


def z_market_home_edge(r):
    mph = nz(r['market_prob_home'])
    mpa = nz(r['market_prob_away'])
    return clamp((mph - mpa) / 0.25, -2.0, 2.0)


def closeness_score(r):
    score = 0.0
    score += 0.70 * (1.0 - min(1.0, abs(nz(r['strength_diff_ppg'])) / 1.2))
    score += 0.55 * (1.0 - min(1.0, abs(nz(r['strength_diff_form5'])) / 1.0))
    score += 0.45 * (1.0 - min(1.0, abs(nz(r['table_gap_points_before'])) / 8.0))
    score += 0.30 * (1.0 - min(1.0, abs(nz(r['home_advantage_ppg'])) / 1.0))
    return clamp(score / 2.0, 0.0, 1.0)


def make_probs_from_scores(r: FeatureRow, home_score: float, away_score: float, draw_bias: float, prior_weight: float) -> Dict[str, float]:
    mph = r['market_prob_home'] or (1.0 / 3.0)
    mpd = r['market_prob_draw'] or (1.0 / 3.0)
    mpa = r['market_prob_away'] or (1.0 / 3.0)

    close = closeness_score(r)
    draw_score = math.log(max(mpd, 1e-9)) * prior_weight + draw_bias * close
    home_score = math.log(max(mph, 1e-9)) * prior_weight + home_score
    away_score = math.log(max(mpa, 1e-9)) * prior_weight + away_score

    mx = max(home_score, draw_score, away_score)
    eh = math.exp(home_score - mx)
    ed = math.exp(draw_score - mx)
    ea = math.exp(away_score - mx)
    s = eh + ed + ea
    return {RESULT_HOME: eh / s, RESULT_DRAW: ed / s, RESULT_AWAY: ea / s}


def strategy_probs(strategy: str, r: FeatureRow) -> Dict[str, float]:
    s_ppg = z_strength_diff_ppg(r)
    s_f5 = z_form5(r)
    s_f10 = z_form10(r)
    s_home = z_home_adv(r)
    s_pos = z_table_pos(r)
    s_pts = z_table_points(r)
    s_gd = z_table_gd(r)
    s_rest = z_rest(r)
    s_h2h = z_h2h(r)
    s_mkt = z_market_home_edge(r)

    if strategy == 'ppg_core':
        hs = 1.15 * s_ppg + 0.55 * s_home + 0.30 * s_pts + 0.15 * s_rest
        aw = -1.15 * s_ppg - 0.25 * s_home - 0.30 * s_pts - 0.15 * s_rest
        return make_probs_from_scores(r, hs, aw, draw_bias=0.35, prior_weight=0.70)
    if strategy == 'form5_momentum':
        hs = 1.20 * s_f5 + 0.40 * s_home + 0.25 * s_rest + 0.20 * s_h2h
        aw = -1.20 * s_f5 - 0.20 * s_home - 0.25 * s_rest - 0.15 * s_h2h
        return make_probs_from_scores(r, hs, aw, draw_bias=0.20, prior_weight=0.72)
    if strategy == 'form10_stability':
        hs = 1.10 * s_f10 + 0.50 * s_ppg + 0.35 * s_home + 0.20 * s_pts
        aw = -1.10 * s_f10 - 0.20 * s_home - 0.50 * s_ppg - 0.20 * s_pts
        return make_probs_from_scores(r, hs, aw, draw_bias=0.25, prior_weight=0.76)
    if strategy == 'table_rank':
        hs = 0.95 * s_pos + 0.75 * s_pts + 0.65 * s_gd + 0.25 * s_home
        aw = -0.95 * s_pos - 0.75 * s_pts - 0.65 * s_gd - 0.15 * s_home
        return make_probs_from_scores(r, hs, aw, draw_bias=0.30, prior_weight=0.78)
    if strategy == 'rest_spot':
        hs = 1.00 * s_rest + 0.55 * s_home + 0.35 * s_f5 + 0.25 * s_ppg
        aw = -1.00 * s_rest - 0.25 * s_home - 0.35 * s_f5 - 0.25 * s_ppg
        return make_probs_from_scores(r, hs, aw, draw_bias=0.28, prior_weight=0.80)
    if strategy == 'h2h_small':
        hs = 0.55 * s_h2h + 0.55 * s_f5 + 0.45 * s_home + 0.35 * s_ppg
        aw = -0.45 * s_h2h - 0.25 * s_home - 0.55 * s_f5 - 0.35 * s_ppg
        return make_probs_from_scores(r, hs, aw, draw_bias=0.24, prior_weight=0.84)
    if strategy == 'home_ice':
        hs = 1.25 * s_home + 0.55 * s_ppg + 0.35 * s_f10 + 0.20 * s_rest
        aw = -0.25 * s_home - 0.55 * s_ppg - 0.35 * s_f10 - 0.20 * s_rest
        return make_probs_from_scores(r, hs, aw, draw_bias=0.22, prior_weight=0.82)
    if strategy == 'balanced':
        hs = 0.85 * s_ppg + 0.75 * s_f5 + 0.55 * s_f10 + 0.45 * s_home + 0.35 * s_pos + 0.20 * s_rest + 0.10 * s_h2h
        aw = -0.85 * s_ppg - 0.30 * s_home - 0.75 * s_f5 - 0.55 * s_f10 - 0.35 * s_pos - 0.20 * s_rest - 0.08 * s_h2h
        return make_probs_from_scores(r, hs, aw, draw_bias=0.25, prior_weight=0.78)
    if strategy == 'balanced_no_h2h':
        hs = 0.90 * s_ppg + 0.80 * s_f5 + 0.55 * s_f10 + 0.45 * s_home + 0.35 * s_pos + 0.20 * s_rest
        aw = -0.90 * s_ppg - 0.30 * s_home - 0.80 * s_f5 - 0.55 * s_f10 - 0.35 * s_pos - 0.20 * s_rest
        return make_probs_from_scores(r, hs, aw, draw_bias=0.25, prior_weight=0.76)
    if strategy == 'underdog_hunter':
        hs = 0.55 * s_ppg + 0.35 * s_home + 0.35 * s_f10 + 0.25 * s_mkt
        aw = -0.90 * s_ppg - 0.05 * s_home - 0.50 * s_f10 - 0.45 * s_mkt - 0.25 * s_rest
        return make_probs_from_scores(r, hs, aw, draw_bias=0.32, prior_weight=0.92)
    if strategy == 'draw_tight':
        hs = 0.65 * s_ppg + 0.45 * s_f5 + 0.30 * s_home
        aw = -0.65 * s_ppg - 0.10 * s_home - 0.45 * s_f5
        return make_probs_from_scores(r, hs, aw, draw_bias=1.05, prior_weight=0.82)
    raise ValueError(f'Unknown strategy: {strategy}')


def select_bet(strategy: str, r: FeatureRow, probs: Dict[str, float], threshold: float, min_odds: float, max_odds: float) -> Optional[Tuple[str, float, float, float]]:
    options = []
    for outcome, odds_key, mp_key in (
        (RESULT_HOME, 'odds_home', 'market_prob_home'),
        (RESULT_DRAW, 'odds_draw', 'market_prob_draw'),
        (RESULT_AWAY, 'odds_away', 'market_prob_away'),
    ):
        odds = r[odds_key]
        market_prob = r[mp_key]
        if odds is None or market_prob is None:
            continue
        if odds < min_odds or odds > max_odds:
            continue
        model_prob = probs[outcome]
        edge = model_prob - market_prob
        ev = model_prob * odds - 1.0
        if edge >= threshold and ev >= 0:
            options.append((outcome, odds, model_prob, edge, ev))

    if not options:
        return None
    if strategy == 'draw_tight':
        options = [x for x in options if x[0] == RESULT_DRAW]
    elif strategy == 'underdog_hunter':
        options = [x for x in options if x[0] == RESULT_AWAY and x[1] >= 2.0]
    elif strategy == 'home_ice':
        options = [x for x in options if x[0] == RESULT_HOME]
    if not options:
        return None
    best = max(options, key=lambda x: (x[4], x[3], x[1]))
    return best[0], best[1], best[2], best[3]


def calc_stake(bankroll: float, flat_stake: float, stake_mode: str) -> float:
    if stake_mode == 'flat_1000':
        return min(flat_stake, bankroll)
    pct_map = {
        'pct_0.75': 0.0075,
        'pct_1.0': 0.0100,
        'pct_1.25': 0.0125,
        'pct_1.5': 0.0150,
    }
    pct = pct_map[stake_mode]
    return max(0.0, min(bankroll, round(bankroll * pct, 2)))


def run_backtest_stream(
    rows: List[FeatureRow],
    strategy: str,
    threshold: float,
    stake_mode: str,
    min_history: int,
    starting_bankroll: float,
    flat_stake: float,
    min_odds: float,
    max_odds: float,
) -> Tuple[BacktestSummary, Dict[str, List[dict]]]:
    bankroll = starting_bankroll
    peak = bankroll
    max_dd = 0.0
    max_dd_pct = 0.0
    losing_streak = 0
    max_losing_streak = 0
    bets = 0
    wins = 0
    odds_sum = 0.0
    turnover = 0.0
    years = defaultdict(float)
    monthly = defaultdict(ComboAccumulator)
    league = defaultdict(ComboAccumulator)
    yearly = defaultdict(ComboAccumulator)

    for r in rows:
        probs = strategy_probs(strategy, r)
        bet = select_bet(strategy, r, probs, threshold, min_odds, max_odds)
        if not bet:
            continue
        outcome, odds, model_prob, edge = bet
        stake = calc_stake(bankroll, flat_stake, stake_mode)
        if stake <= 0:
            continue
        market_prob = r['market_prob_home'] if outcome == RESULT_HOME else r['market_prob_draw'] if outcome == RESULT_DRAW else r['market_prob_away']
        won = 1 if r['result_1x2'] == outcome else 0
        pnl = round(stake * (odds - 1.0), 2) if won else round(-stake, 2)
        bankroll = round(bankroll + pnl, 2)
        peak = max(peak, bankroll)
        dd = peak - bankroll
        dd_pct = (dd / peak * 100.0) if peak else 0.0
        max_dd = max(max_dd, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)
        if won:
            losing_streak = 0
        else:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)

        dt = parse_date(r['match_date'])
        month_key = dt.strftime('%Y-%m')
        year_key = dt.strftime('%Y')
        league_key = r['league']

        bets += 1
        wins += won
        odds_sum += odds
        turnover += stake
        years[year_key] += pnl
        monthly[month_key].add(stake, pnl, won, odds)
        league[league_key].add(stake, pnl, won, odds)
        yearly[year_key].add(stake, pnl, won, odds)

    net_profit = round(bankroll - starting_bankroll, 2)
    hit_rate = safe_div(wins, bets) or 0.0
    avg_odds = safe_div(odds_sum, bets) or 0.0
    roi = safe_div(net_profit, turnover) or 0.0
    profitable_years = sum(1 for pnl in years.values() if pnl > 0)

    summary = BacktestSummary(
        strategy=strategy,
        stake_mode=stake_mode,
        threshold=threshold,
        min_history=min_history,
        bets=bets,
        hit_rate=hit_rate,
        avg_odds=avg_odds,
        net_profit=net_profit,
        roi=roi,
        max_drawdown=round(max_dd, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        max_losing_streak=max_losing_streak,
        ending_bankroll=bankroll,
        profitable_years=profitable_years,
        total_years=len(years),
    )
    details = {
        'monthly': [acc.to_row(k) for k, acc in sorted(monthly.items())],
        'league': [acc.to_row(k) for k, acc in sorted(league.items())],
        'yearly': [acc.to_row(k) for k, acc in sorted(yearly.items())],
    }
    return summary, details


def ensure_reports_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_csv(path: str, rows: Iterable[dict], fieldnames: List[str]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def pick_families(summaries: List[BacktestSummary], min_bets: int, top_n: int) -> List[BacktestSummary]:
    eligible = [s for s in summaries if s.bets >= min_bets]
    eligible.sort(
        key=lambda s: (
            s.profitable_years,
            s.total_years,
            s.roi,
            s.net_profit,
            -s.max_drawdown_pct,
            s.bets,
        ),
        reverse=True,
    )
    return eligible[:top_n]


def build_report_text(
    top_summaries: List[BacktestSummary],
    detail_map: Dict[Tuple[str, str, float, int], Dict[str, List[dict]]],
    starting_bankroll: float,
    flat_stake: float,
    thresholds: List[float],
    min_histories: List[int],
) -> str:
    lines = []
    lines.append('# Hockey backtest report')
    lines.append('')
    lines.append(f'- Starting bankroll: {starting_bankroll:.2f}')
    lines.append(f'- Flat stake: {flat_stake:.2f}')
    lines.append(f'- Threshold grid: {", ".join(str(x) for x in thresholds)}')
    lines.append(f'- Min-history grid: {", ".join(str(x) for x in min_histories)}')
    lines.append('')
    lines.append('## Top combinations')
    lines.append('')

    for s in top_summaries:
        key = (s.strategy, s.stake_mode, s.threshold, s.min_history)
        detail = detail_map[key]
        lines.append(f"### {s.strategy} | {s.stake_mode} | threshold={s.threshold} | min_history={s.min_history}")
        lines.append(f"- Bets: {s.bets}")
        lines.append(f"- Hit rate: {s.hit_rate:.2%}")
        lines.append(f"- Avg odds: {s.avg_odds:.3f}")
        lines.append(f"- Net profit: {s.net_profit:.2f}")
        lines.append(f"- ROI: {s.roi:.2%}")
        lines.append(f"- Max drawdown: {s.max_drawdown:.2f} ({s.max_drawdown_pct:.2f}%)")
        lines.append(f"- Max losing streak: {s.max_losing_streak}")
        lines.append(f"- Ending bankroll: {s.ending_bankroll:.2f}")
        lines.append(f"- Profitable years: {s.profitable_years}/{s.total_years}")
        lines.append('')
        lines.append('#### Breakdown by years')
        for row in detail['yearly']:
            lines.append(f"- {row['key']}: pnl={row['pnl']:.2f}, roi={row['roi']:.2%}, bets={row['bets']}")
        lines.append('')
        lines.append('#### Breakdown by months (top 8 / bottom 8)')
        for row in sorted(detail['monthly'], key=lambda x: x['pnl'], reverse=True)[:8]:
            lines.append(f"- TOP {row['key']}: pnl={row['pnl']:.2f}, roi={row['roi']:.2%}, bets={row['bets']}")
        for row in sorted(detail['monthly'], key=lambda x: x['pnl'])[:8]:
            lines.append(f"- BOT {row['key']}: pnl={row['pnl']:.2f}, roi={row['roi']:.2%}, bets={row['bets']}")
        lines.append('')
        lines.append('#### Breakdown by leagues (top 12 / bottom 12)')
        lines.append('Only leagues with at least 30 bets should be treated as remotely informative.')
        for row in sorted(detail['league'], key=lambda x: (x['roi'], x['pnl'], x['bets']), reverse=True)[:12]:
            lines.append(f"- TOP {row['key']}: pnl={row['pnl']:.2f}, roi={row['roi']:.2%}, bets={row['bets']}")
        for row in sorted(detail['league'], key=lambda x: (x['roi'], x['pnl'], x['bets']))[:12]:
            lines.append(f"- BOT {row['key']}: pnl={row['pnl']:.2f}, roi={row['roi']:.2%}, bets={row['bets']}")
        lines.append('')
    return '\n'.join(lines)


def expand_with_preset(args) -> Tuple[List[str], List[str], List[float], List[int]]:
    if not args.preset:
        return args.strategies, args.stake_modes, args.thresholds, args.min_history_grid
    preset = PRESET_GRIDS[args.preset]
    strategies = args.strategies or preset['strategies']
    stake_modes = args.stake_modes or preset['stake_modes']
    thresholds = args.thresholds or preset['thresholds']
    min_histories = args.min_history_grid or preset['min_histories']
    return strategies, stake_modes, thresholds, min_histories


def parse_args():
    p = argparse.ArgumentParser(description='Lightweight hockey 1X2 backtest model with explicit league/month/year breakdowns')
    p.add_argument('--db', required=True, help='Path to SQLite DB')
    p.add_argument('--reports-dir', default='/root/betagent/reports', help='Directory for reports')
    p.add_argument('--starting-bankroll', type=float, default=100000.0)
    p.add_argument('--flat-stake', type=float, default=1000.0)
    p.add_argument('--thresholds', nargs='*', type=float, default=None)
    p.add_argument('--min-history-grid', nargs='*', type=int, default=None)
    p.add_argument('--preset', choices=sorted(PRESET_GRIDS.keys()), default='core')
    p.add_argument('--strategies', nargs='*', default=None)
    p.add_argument('--stake-modes', nargs='*', default=None)
    p.add_argument('--min-bets', type=int, default=50, help='Min bets for combo to appear in top list')
    p.add_argument('--min-odds', type=float, default=1.50)
    p.add_argument('--max-odds', type=float, default=6.50)
    p.add_argument('--top-n', type=int, default=12)
    p.add_argument('--league-min-bets', type=int, default=30)
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    strategies, stake_modes, thresholds, min_histories = expand_with_preset(args)
    if not thresholds:
        thresholds = PRESET_GRIDS['core']['thresholds']
    if not min_histories:
        min_histories = PRESET_GRIDS['core']['min_histories']
    strategies = strategies or DEFAULT_STRATEGIES
    stake_modes = stake_modes or DEFAULT_STAKE_MODES

    ensure_reports_dir(args.reports_dir)
    conn = sqlite3.connect(args.db)
    try:
        rows_by_history: Dict[int, List[FeatureRow]] = {}
        for mh in min_histories:
            rows_by_history[mh] = fetch_feature_rows(conn, mh)
            logging.info('Loaded feature rows for min_history=%s: %s', mh, len(rows_by_history[mh]))
    finally:
        conn.close()

    summaries: List[BacktestSummary] = []
    detail_map: Dict[Tuple[str, str, float, int], Dict[str, List[dict]]] = {}
    league_rows: List[dict] = []
    monthly_rows: List[dict] = []
    yearly_rows: List[dict] = []

    combos = list(itertools.product(min_histories, strategies, stake_modes, thresholds))
    total = len(combos)
    for idx, (min_history, strategy, stake_mode, threshold) in enumerate(combos, start=1):
        logging.info('[%s/%s] Backtesting %s | %s | thr=%s | min_history=%s', idx, total, strategy, stake_mode, threshold, min_history)
        summary, details = run_backtest_stream(
            rows=rows_by_history[min_history],
            strategy=strategy,
            threshold=threshold,
            stake_mode=stake_mode,
            min_history=min_history,
            starting_bankroll=args.starting_bankroll,
            flat_stake=args.flat_stake,
            min_odds=args.min_odds,
            max_odds=args.max_odds,
        )
        summaries.append(summary)
        combo_key = (strategy, stake_mode, threshold, min_history)
        detail_map[combo_key] = details

        for bucket_name, storage in (('league', league_rows), ('monthly', monthly_rows), ('yearly', yearly_rows)):
            for row in details[bucket_name]:
                storage.append({
                    'strategy': strategy,
                    'stake_mode': stake_mode,
                    'threshold': threshold,
                    'min_history': min_history,
                    'bucket': row['key'],
                    'bets': row['bets'],
                    'stake': row['stake'],
                    'pnl': row['pnl'],
                    'roi': round(row['roi'], 6),
                    'hit_rate': round(row['hit_rate'], 6),
                    'avg_odds': round(row['avg_odds'], 4),
                })

    top = pick_families(summaries, args.min_bets, args.top_n)
    summary_rows = [
        {
            'strategy': s.strategy,
            'stake_mode': s.stake_mode,
            'threshold': s.threshold,
            'min_history': s.min_history,
            'bets': s.bets,
            'hit_rate': round(s.hit_rate, 6),
            'avg_odds': round(s.avg_odds, 4),
            'net_profit': round(s.net_profit, 2),
            'roi': round(s.roi, 6),
            'max_drawdown': round(s.max_drawdown, 2),
            'max_drawdown_pct': round(s.max_drawdown_pct, 2),
            'max_losing_streak': s.max_losing_streak,
            'ending_bankroll': round(s.ending_bankroll, 2),
            'profitable_years': s.profitable_years,
            'total_years': s.total_years,
        }
        for s in sorted(
            summaries,
            key=lambda x: (x.profitable_years, x.total_years, x.roi, x.net_profit, -x.max_drawdown_pct, x.bets),
            reverse=True,
        )
    ]

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_csv = os.path.join(args.reports_dir, f'hockey_strategy_scan_{ts}.csv')
    report_md = os.path.join(args.reports_dir, f'hockey_strategy_report_{ts}.md')
    league_csv = os.path.join(args.reports_dir, f'hockey_strategy_leagues_{ts}.csv')
    monthly_csv = os.path.join(args.reports_dir, f'hockey_strategy_monthly_{ts}.csv')
    yearly_csv = os.path.join(args.reports_dir, f'hockey_strategy_yearly_{ts}.csv')

    write_csv(summary_csv, summary_rows, list(summary_rows[0].keys()) if summary_rows else [
        'strategy', 'stake_mode', 'threshold', 'min_history', 'bets', 'hit_rate', 'avg_odds', 'net_profit', 'roi',
        'max_drawdown', 'max_drawdown_pct', 'max_losing_streak', 'ending_bankroll', 'profitable_years', 'total_years'
    ])
    write_csv(league_csv, league_rows, list(league_rows[0].keys()) if league_rows else [
        'strategy', 'stake_mode', 'threshold', 'min_history', 'bucket', 'bets', 'stake', 'pnl', 'roi', 'hit_rate', 'avg_odds'
    ])
    write_csv(monthly_csv, monthly_rows, list(monthly_rows[0].keys()) if monthly_rows else [
        'strategy', 'stake_mode', 'threshold', 'min_history', 'bucket', 'bets', 'stake', 'pnl', 'roi', 'hit_rate', 'avg_odds'
    ])
    write_csv(yearly_csv, yearly_rows, list(yearly_rows[0].keys()) if yearly_rows else [
        'strategy', 'stake_mode', 'threshold', 'min_history', 'bucket', 'bets', 'stake', 'pnl', 'roi', 'hit_rate', 'avg_odds'
    ])

    with open(report_md, 'w', encoding='utf-8') as f:
        f.write(build_report_text(top, detail_map, args.starting_bankroll, args.flat_stake, thresholds, min_histories))

    print('\n=== TOP COMBINATIONS ===')
    for s in top:
        print(
            f"{s.strategy:18s} | {s.stake_mode:8s} | thr={s.threshold:.3f} | mh={s.min_history:2d} | bets={s.bets:5d} | "
            f"ROI={s.roi:.2%} | profit={s.net_profit:10.2f} | years={s.profitable_years}/{s.total_years} | "
            f"DD={s.max_drawdown_pct:6.2f}% | end={s.ending_bankroll:10.2f}"
        )
    print('\nSaved files:')
    print(report_md)
    print(summary_csv)
    print(league_csv)
    print(monthly_csv)
    print(yearly_csv)


if __name__ == '__main__':
    main()
