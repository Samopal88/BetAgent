#!/usr/bin/env python3
import argparse, csv, math, sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

FEATURE_TABLE = 'backtest_hockey_features_v2'


def safe_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def implied_probs(odds_home, odds_draw, odds_away):
    if not odds_home or not odds_draw or not odds_away:
        return None
    invs = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    s = sum(invs)
    if s <= 0:
        return None
    return {'H': invs[0] / s, 'D': invs[1] / s, 'A': invs[2] / s}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def norm(x, scale):
    if x is None:
        return 0.0
    return clamp(x / scale, -1.0, 1.0)


def avg_nonnull(*xs):
    vals = [x for x in xs if x is not None]
    return None if not vals else sum(vals) / len(vals)


def year_month(match_date: str):
    dt = datetime.strptime(match_date, '%d.%m.%Y')
    return dt.strftime('%Y-%m'), dt.year


@dataclass
class BetResult:
    stake: float
    odds: float
    won: bool
    pnl: float


class BankrollTracker:
    def __init__(self, starting: float, mode: str, flat_stake: float):
        self.starting = starting
        self.mode = mode
        self.flat_stake = flat_stake
        self.bank = starting
        self.peak = starting
        self.max_dd_abs = 0.0
        self.max_dd_pct = 0.0
        self.losing_streak = 0
        self.max_losing_streak = 0
        self.net_profit = 0.0
        self.total_staked = 0.0
        self.bets = 0
        self.wins = 0
        self.odds_sum = 0.0

    def current_stake(self):
        if self.mode == 'flat_1000':
            return self.flat_stake
        pct = float(self.mode.split('_')[1]) / 100.0
        stake = self.bank * pct
        return max(1.0, stake)

    def settle(self, odds: float, won: bool):
        stake = self.current_stake()
        pnl = stake * (odds - 1.0) if won else -stake
        self.bank += pnl
        self.net_profit += pnl
        self.total_staked += stake
        self.bets += 1
        self.odds_sum += odds
        if won:
            self.wins += 1
            self.losing_streak = 0
        else:
            self.losing_streak += 1
            self.max_losing_streak = max(self.max_losing_streak, self.losing_streak)
        self.peak = max(self.peak, self.bank)
        dd_abs = self.peak - self.bank
        dd_pct = 0.0 if self.peak <= 0 else dd_abs / self.peak * 100.0
        self.max_dd_abs = max(self.max_dd_abs, dd_abs)
        self.max_dd_pct = max(self.max_dd_pct, dd_pct)
        return BetResult(stake=stake, odds=odds, won=won, pnl=pnl)


def estimate_probs(row: sqlite3.Row) -> Dict[str, float]:
    # Base market probabilities
    market = implied_probs(row['odds_home'], row['odds_draw'], row['odds_away'])
    if market is None:
        return {}
    pH, pD, pA = market['H'], market['D'], market['A']

    # Feature transforms
    ppg = norm(row['strength_diff_ppg'], 2.0)
    form5 = norm(row['strength_diff_form5'], 1.5)
    form10 = norm(row['strength_diff_form10'], 1.5)
    expdiff = norm(row['expected_goal_diff_proxy'], 1.5)
    tight = 1.0 - clamp((row['expected_match_tightness'] or 0.0) / 1.4, 0.0, 1.0)
    low_total = 1.0 - clamp(((row['expected_total_goals_proxy'] or 6.0) - 4.8) / 2.0, 0.0, 1.0)
    def_bal = 1.0 - clamp((row['expected_defense_balance'] or 0.0) / 1.2, 0.0, 1.0)
    h2h = norm((row['h2h5_home_wins'] or 0) - (row['h2h5_away_wins'] or 0), 3.0)
    rest = norm(row['fatigue_edge'], 4.0)
    home_attack = norm(avg_nonnull(row['home_home_gf_avg'], row['home_gf_avg10']) or 0.0, 4.0)
    away_attack = norm(avg_nonnull(row['away_away_gf_avg'], row['away_gf_avg10']) or 0.0, 4.0)
    home_def = norm(avg_nonnull(row['home_home_ga_avg'], row['home_ga_avg10']) or 0.0, 4.0)
    away_def = norm(avg_nonnull(row['away_away_ga_avg'], row['away_ga_avg10']) or 0.0, 4.0)
    vol = avg_nonnull(row['home_goal_diff_vol5'], row['away_goal_diff_vol5']) or 0.0
    low_vol = 1.0 - clamp(vol / 2.2, 0.0, 1.0)

    # Draw uplift is based on closeness + low-event + balanced defenses + low volatility
    draw_uplift = 0.10 * tight + 0.05 * low_total + 0.04 * def_bal + 0.03 * low_vol - 0.03 * abs(expdiff)
    # Home/Away directional shifts
    dir_shift = 0.11 * ppg + 0.08 * form5 + 0.05 * form10 + 0.10 * expdiff + 0.03 * h2h + 0.03 * rest
    dir_shift += 0.03 * (home_attack - away_def) - 0.03 * (away_attack - home_def)

    pD2 = clamp(pD + draw_uplift, 0.05, 0.55)
    remaining = max(0.01, 1.0 - pD2)
    bias = clamp((pH - pA) + dir_shift * 0.35, -0.90, 0.90)
    pH2 = remaining * (0.5 + bias / 2.0)
    pA2 = remaining - pH2
    pH2 = clamp(pH2, 0.02, 0.90)
    pA2 = clamp(pA2, 0.02, 0.90)
    s = pH2 + pD2 + pA2
    return {'H': pH2 / s, 'D': pD2 / s, 'A': pA2 / s}


def strategy_pick(strategy: str, row: sqlite3.Row, probs: Dict[str, float], threshold: float) -> Optional[str]:
    if not probs:
        return None
    market = implied_probs(row['odds_home'], row['odds_draw'], row['odds_away'])
    edges = {k: probs[k] - market[k] for k in ('H', 'D', 'A')}
    if strategy == 'draw_tight_v2':
        cond = (
            row['home_matches_before'] >= 8 and row['away_matches_before'] >= 8 and
            abs(row['strength_diff_ppg'] or 0.0) <= 0.55 and
            abs(row['strength_diff_form5'] or 0.0) <= 0.70 and
            (row['expected_match_tightness'] or 99.0) <= 0.60 and
            (row['expected_total_goals_proxy'] or 99.0) <= 5.6 and
            (row['home_goal_diff_vol5'] or 99.0) <= 1.8 and
            (row['away_goal_diff_vol5'] or 99.0) <= 1.8
        )
        return 'D' if cond and edges['D'] >= threshold else None
    if strategy == 'low_event_draw_v2':
        cond = (
            row['home_matches_before'] >= 8 and row['away_matches_before'] >= 8 and
            (row['expected_total_goals_proxy'] or 99.0) <= 4.9 and
            (row['home_ga_avg10'] or 99.0) <= 2.2 and (row['away_ga_avg10'] or 99.0) <= 2.2 and
            abs(row['expected_goal_diff_proxy'] or 99.0) <= 0.55
        )
        return 'D' if cond and edges['D'] >= threshold else None
    if strategy == 'underdog_live_v2':
        # Bet underdog in regulation when market leans too hard but current matchup/profile is live
        if row['odds_home'] and row['odds_away']:
            market_side = 'H' if row['odds_home'] < row['odds_away'] else 'A'
            dog = 'A' if market_side == 'H' else 'H'
            dog_edge = edges[dog]
            cond = (
                row['home_matches_before'] >= 10 and row['away_matches_before'] >= 10 and
                abs(row['strength_diff_form5'] or 0.0) <= 0.8 and
                abs(row['expected_goal_diff_proxy'] or 0.0) <= 0.9 and
                ((dog == 'H' and (row['home_form5_ppg'] or 0) >= (row['away_form5_ppg'] or 0) - 0.15) or
                 (dog == 'A' and (row['away_form5_ppg'] or 0) >= (row['home_form5_ppg'] or 0) - 0.15)) and
                ((dog == 'H' and (row['home_home_ga_avg'] or 99) <= 2.6) or
                 (dog == 'A' and (row['away_away_ga_avg'] or 99) <= 2.6))
            )
            return dog if cond and dog_edge >= threshold else None
        return None
    if strategy == 'favorite_mismatch_v2':
        side = 'H' if (row['expected_goal_diff_proxy'] or 0) >= 0 else 'A'
        cond = (
            row['home_matches_before'] >= 10 and row['away_matches_before'] >= 10 and
            abs(row['strength_diff_ppg'] or 0.0) >= 0.8 and
            abs(row['strength_diff_form5'] or 0.0) >= 0.6 and
            abs(row['expected_goal_diff_proxy'] or 0.0) >= 0.9 and
            (row['expected_match_tightness'] or 99) <= 1.6
        )
        return side if cond and edges[side] >= threshold else None
    if strategy == 'defensive_dog_v2':
        if row['odds_home'] and row['odds_away']:
            market_side = 'H' if row['odds_home'] < row['odds_away'] else 'A'
            dog = 'A' if market_side == 'H' else 'H'
            cond = (
                row['home_matches_before'] >= 10 and row['away_matches_before'] >= 10 and
                (row['expected_total_goals_proxy'] or 99.0) <= 5.3 and
                abs(row['expected_goal_diff_proxy'] or 0.0) <= 0.8 and
                ((dog == 'H' and (row['home_home_ga_avg'] or 99) <= 2.3) or
                 (dog == 'A' and (row['away_away_ga_avg'] or 99) <= 2.3)) and
                abs(row['strength_diff_form10'] or 0.0) <= 0.8
            )
            return dog if cond and edges[dog] >= threshold else None
        return None
    if strategy == 'balanced_v2':
        best_side = max(edges, key=lambda k: edges[k])
        cond = row['home_matches_before'] >= 8 and row['away_matches_before'] >= 8
        return best_side if cond and edges[best_side] >= threshold else None
    return None


def load_rows(conn: sqlite3.Connection, min_history: int) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    q = f"""
    SELECT *
    FROM {FEATURE_TABLE}
    WHERE home_matches_before >= ?
      AND away_matches_before >= ?
      AND odds_home IS NOT NULL AND odds_draw IS NOT NULL AND odds_away IS NOT NULL
    ORDER BY match_ts, match_id
    """
    return conn.execute(q, (min_history, min_history)).fetchall()


def run_combo(rows, strategy, stake_mode, threshold, starting_bankroll, flat_stake):
    tracker = BankrollTracker(starting_bankroll, stake_mode, flat_stake)
    by_month = defaultdict(lambda: {'bets':0,'profit':0.0,'staked':0.0})
    by_year = defaultdict(lambda: {'bets':0,'profit':0.0,'staked':0.0})
    by_league = defaultdict(lambda: {'bets':0,'profit':0.0,'staked':0.0})

    for row in rows:
        probs = estimate_probs(row)
        pick = strategy_pick(strategy, row, probs, threshold)
        if not pick:
            continue
        odds = row['odds_home'] if pick == 'H' else row['odds_draw'] if pick == 'D' else row['odds_away']
        res = tracker.settle(float(odds), row['result_1x2_rt'] == pick)
        ym, y = year_month(row['match_date'])
        for bucket in (by_month[ym], by_year[y], by_league[row['league']]):
            bucket['bets'] += 1
            bucket['profit'] += res.pnl
            bucket['staked'] += res.stake

    years_sorted = sorted(by_year)
    profitable_years = sum(1 for y in years_sorted if by_year[y]['profit'] > 0)
    return {
        'bets': tracker.bets,
        'hit_rate': 0.0 if tracker.bets == 0 else tracker.wins / tracker.bets * 100.0,
        'avg_odds': 0.0 if tracker.bets == 0 else tracker.odds_sum / tracker.bets,
        'net_profit': tracker.net_profit,
        'roi': 0.0 if tracker.total_staked == 0 else tracker.net_profit / tracker.total_staked * 100.0,
        'max_dd_abs': tracker.max_dd_abs,
        'max_dd_pct': tracker.max_dd_pct,
        'max_losing_streak': tracker.max_losing_streak,
        'ending_bankroll': tracker.bank,
        'profitable_years': profitable_years,
        'total_years': len(years_sorted),
        'monthly': by_month,
        'yearly': by_year,
        'leagues': by_league,
    }


def write_csv(path: Path, rows: Iterable[Dict], fieldnames: List[str]):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--reports-dir', required=True)
    ap.add_argument('--starting-bankroll', type=float, default=100000)
    ap.add_argument('--flat-stake', type=float, default=1000)
    ap.add_argument('--thresholds', nargs='+', type=float, default=[0.015,0.02,0.03,0.04])
    ap.add_argument('--min-history-grid', nargs='+', type=int, default=[5,10,15])
    ap.add_argument('--stake-modes', nargs='+', default=['flat_1000','pct_0.75','pct_1.0','pct_1.25','pct_1.5'])
    ap.add_argument('--strategies', nargs='+', default=['draw_tight_v2','low_event_draw_v2','underdog_live_v2','favorite_mismatch_v2','defensive_dog_v2','balanced_v2'])
    args = ap.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    scan_rows = []
    monthly_rows = []
    yearly_rows = []
    league_rows = []

    cache = {}
    for min_history in args.min_history_grid:
        rows = load_rows(conn, min_history)
        cache[min_history] = rows
        print(f'Loaded feature rows for min_history={min_history}: {len(rows)}')

    for min_history in args.min_history_grid:
        rows = cache[min_history]
        for strategy in args.strategies:
            for stake_mode in args.stake_modes:
                for threshold in args.thresholds:
                    result = run_combo(rows, strategy, stake_mode, threshold, args.starting_bankroll, args.flat_stake)
                    combo = {
                        'strategy': strategy,
                        'stake_mode': stake_mode,
                        'threshold': threshold,
                        'min_history': min_history,
                        **{k: result[k] for k in ['bets','hit_rate','avg_odds','net_profit','roi','max_dd_abs','max_dd_pct','max_losing_streak','ending_bankroll','profitable_years','total_years']}
                    }
                    scan_rows.append(combo)
                    print(f"{strategy:18s} | {stake_mode:9s} | thr={threshold:.3f} | mh={min_history:2d} | bets={result['bets']:5d} | ROI={result['roi']:.2f}% | profit={result['net_profit']:.2f}")
                    for ym, vals in result['monthly'].items():
                        monthly_rows.append({'strategy':strategy,'stake_mode':stake_mode,'threshold':threshold,'min_history':min_history,'month':ym, **vals, 'roi': 0.0 if vals['staked']==0 else vals['profit']/vals['staked']*100.0})
                    for y, vals in result['yearly'].items():
                        yearly_rows.append({'strategy':strategy,'stake_mode':stake_mode,'threshold':threshold,'min_history':min_history,'year':y, **vals, 'roi': 0.0 if vals['staked']==0 else vals['profit']/vals['staked']*100.0})
                    for lg, vals in result['leagues'].items():
                        league_rows.append({'strategy':strategy,'stake_mode':stake_mode,'threshold':threshold,'min_history':min_history,'league':lg, **vals, 'roi': 0.0 if vals['staked']==0 else vals['profit']/vals['staked']*100.0})

    scan_rows.sort(key=lambda r: (r['roi'], r['profitable_years'], r['bets']), reverse=True)

    scan_path = reports_dir / f'hockey_v2_strategy_scan_{ts}.csv'
    monthly_path = reports_dir / f'hockey_v2_strategy_monthly_{ts}.csv'
    yearly_path = reports_dir / f'hockey_v2_strategy_yearly_{ts}.csv'
    leagues_path = reports_dir / f'hockey_v2_strategy_leagues_{ts}.csv'
    report_path = reports_dir / f'hockey_v2_strategy_report_{ts}.md'

    write_csv(scan_path, scan_rows, ['strategy','stake_mode','threshold','min_history','bets','hit_rate','avg_odds','net_profit','roi','max_dd_abs','max_dd_pct','max_losing_streak','ending_bankroll','profitable_years','total_years'])
    write_csv(monthly_path, monthly_rows, ['strategy','stake_mode','threshold','min_history','month','bets','profit','staked','roi'])
    write_csv(yearly_path, yearly_rows, ['strategy','stake_mode','threshold','min_history','year','bets','profit','staked','roi'])
    write_csv(leagues_path, league_rows, ['strategy','stake_mode','threshold','min_history','league','bets','profit','staked','roi'])

    with report_path.open('w', encoding='utf-8') as f:
        f.write('# Hockey v2 strategy report\n\n')
        f.write('## Top 30 by ROI\n\n')
        for r in scan_rows[:30]:
            f.write(f"- {r['strategy']} | {r['stake_mode']} | thr={r['threshold']:.3f} | mh={r['min_history']} | bets={r['bets']} | ROI={r['roi']:.2f}% | profit={r['net_profit']:.2f} | years={r['profitable_years']}/{r['total_years']} | DD={r['max_dd_pct']:.2f}% | end={r['ending_bankroll']:.2f}\n")
        f.write('\n## Saved files\n')
        for p in [scan_path, leagues_path, monthly_path, yearly_path]:
            f.write(f'- {p}\n')

    print('\nSaved files:')
    print(scan_path)
    print(leagues_path)
    print(monthly_path)
    print(yearly_path)
    print(report_path)

if __name__ == '__main__':
    main()
