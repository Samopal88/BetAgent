#!/usr/bin/env python3
import argparse
import csv
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

FEATURE_TABLE = "backtest_hockey_features_v2"


@dataclass(frozen=True)
class StrategyPick:
    market: str
    model_prob: float
    edge: float
    score: float


class ComboTracker:
    def __init__(self, starting_bankroll: float, flat_stake: float, stake_mode: str):
        self.starting_bankroll = starting_bankroll
        self.flat_stake = flat_stake
        self.stake_mode = stake_mode
        self.bankroll = starting_bankroll
        self.peak = starting_bankroll
        self.max_dd_abs = 0.0
        self.max_dd_pct = 0.0
        self.max_losing_streak = 0
        self.current_losing_streak = 0
        self.bets = 0
        self.wins = 0
        self.total_staked = 0.0
        self.total_return = 0.0
        self.total_odds = 0.0
        self.profitable_years = 0
        self.total_years = 0
        self.monthly = defaultdict(lambda: {"bets": 0, "profit": 0.0, "staked": 0.0, "wins": 0})
        self.yearly = defaultdict(lambda: {"bets": 0, "profit": 0.0, "staked": 0.0, "wins": 0})
        self.leagues = defaultdict(lambda: {"bets": 0, "profit": 0.0, "staked": 0.0, "wins": 0})

    def _calc_stake(self) -> float:
        if self.stake_mode == "flat_1000":
            return self.flat_stake
        pct_map = {
            "pct_0.75": 0.0075,
            "pct_1.0": 0.01,
            "pct_1.25": 0.0125,
            "pct_1.5": 0.015,
        }
        pct = pct_map[self.stake_mode]
        return max(1.0, self.bankroll * pct)

    def add_bet(self, won: bool, odds: float, year_key: str, month_key: str, league: str):
        stake = self._calc_stake()
        profit = stake * (odds - 1.0) if won else -stake
        ret = stake * odds if won else 0.0

        self.bets += 1
        self.wins += 1 if won else 0
        self.total_staked += stake
        self.total_return += ret
        self.total_odds += odds
        self.bankroll += profit

        if won:
            self.current_losing_streak = 0
        else:
            self.current_losing_streak += 1
            self.max_losing_streak = max(self.max_losing_streak, self.current_losing_streak)

        self.peak = max(self.peak, self.bankroll)
        dd_abs = self.peak - self.bankroll
        dd_pct = (dd_abs / self.peak * 100.0) if self.peak > 0 else 0.0
        self.max_dd_abs = max(self.max_dd_abs, dd_abs)
        self.max_dd_pct = max(self.max_dd_pct, dd_pct)

        for bucket in (self.monthly[month_key], self.yearly[year_key], self.leagues[league]):
            bucket["bets"] += 1
            bucket["profit"] += profit
            bucket["staked"] += stake
            bucket["wins"] += 1 if won else 0

    def finalize(self):
        years = sorted(self.yearly.keys())
        self.total_years = len(years)
        self.profitable_years = sum(1 for y in years if self.yearly[y]["profit"] > 0)

    def scan_row(self, strategy: str, stake_mode: str, threshold: float, min_history: int) -> dict:
        roi = (self.total_return - self.total_staked) / self.total_staked * 100.0 if self.total_staked else 0.0
        profit = self.total_return - self.total_staked
        hit_rate = self.wins / self.bets * 100.0 if self.bets else 0.0
        avg_odds = self.total_odds / self.bets if self.bets else 0.0
        return {
            "strategy": strategy,
            "stake_mode": stake_mode,
            "threshold": threshold,
            "min_history": min_history,
            "bets": self.bets,
            "wins": self.wins,
            "hit_rate": round(hit_rate, 4),
            "avg_odds": round(avg_odds, 4),
            "net_profit": round(profit, 2),
            "roi": round(roi, 4),
            "max_drawdown_abs": round(self.max_dd_abs, 2),
            "max_drawdown_pct": round(self.max_dd_pct, 4),
            "max_losing_streak": self.max_losing_streak,
            "ending_bankroll": round(self.bankroll, 2),
            "profitable_years": self.profitable_years,
            "total_years": self.total_years,
        }


def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def implied_probs(row: sqlite3.Row) -> Optional[Dict[str, float]]:
    oh = safe_float(row["odds_home"])
    od = safe_float(row["odds_draw"])
    oa = safe_float(row["odds_away"])
    if not oh or not od or not oa or oh <= 1.01 or od <= 1.01 or oa <= 1.01:
        return None
    ih, idr, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
    s = ih + idr + ia
    if s <= 0:
        return None
    return {"H": ih / s, "D": idr / s, "A": ia / s}


def pick_odds(row: sqlite3.Row, market: str) -> Optional[float]:
    mapping = {"H": "odds_home", "D": "odds_draw", "A": "odds_away"}
    odds = safe_float(row[mapping[market]])
    if not odds or odds <= 1.01:
        return None
    return odds


def history_ok(row: sqlite3.Row, min_history: int) -> bool:
    return True


def getv(row: sqlite3.Row, key: str, default: float = 0.0) -> float:
    v = safe_float(row[key])
    return default if v is None else v


def strategy_underdog_live_v2(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    home_adv = (getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before"))
    gf5h = getv(row, "home_gf_avg5")
    ga5h = getv(row, "home_ga_avg5")
    gf5a = getv(row, "away_gf_avg5")
    ga5a = getv(row, "away_ga_avg5")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)

    if imp["H"] < imp["A"]:
        signal = 0.0
        signal += clamp(-ppg, 0, 3) * 0.18
        signal += clamp(-form5, 0, 3) * 0.28
        signal += clamp(home_adv, 0, 2) * 0.12
        signal += clamp(gf5h - ga5a, -2, 2) * 0.12
        signal += clamp(-(ga5h - gf5a), -2, 2) * 0.08
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(0.8 - vol, -1, 1) * 0.06
        prob = clamp(imp["H"] + signal * 0.08, 0.02, 0.93)
        return StrategyPick("H", prob, prob - imp["H"], signal)
    signal = 0.0
    signal += clamp(ppg, 0, 3) * 0.18
    signal += clamp(form5, 0, 3) * 0.28
    signal += clamp(-home_adv, 0, 2) * 0.12
    signal += clamp(gf5a - ga5h, -2, 2) * 0.12
    signal += clamp(-(ga5a - gf5h), -2, 2) * 0.08
    signal += clamp(exp_diff, -2, 2) * 0.18
    signal += clamp(0.8 - vol, -1, 1) * 0.06
    prob = clamp(imp["A"] + signal * 0.08, 0.02, 0.93)
    return StrategyPick("A", prob, prob - imp["A"], signal)


def strategy_draw_tight_lowevent_v3(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    abs_ppg = abs(getv(row, "strength_diff_ppg"))
    abs_form5 = abs(getv(row, "strength_diff_form5"))
    abs_form10 = abs(getv(row, "strength_diff_form10"))
    exp_total = getv(row, "expected_total_goals_proxy")
    exp_diff = abs(getv(row, "expected_goal_diff_proxy"))
    tight = getv(row, "expected_match_tightness")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)
    ga5h = getv(row, "home_ga_avg5")
    ga5a = getv(row, "away_ga_avg5")

    signal = 0.0
    signal += clamp(1.2 - abs_ppg, -1, 1.2) * 0.28
    signal += clamp(1.0 - abs_form5, -1, 1.0) * 0.24
    signal += clamp(1.2 - abs_form10, -1, 1.0) * 0.12
    signal += clamp(5.6 - exp_total, -2, 2) * 0.16
    signal += clamp(1.0 - exp_diff, -1, 1.0) * 0.18
    signal += clamp(tight, -2, 2) * 0.12
    signal += clamp(0.9 - vol, -1, 1) * 0.08
    signal += clamp(2.6 - (ga5h + ga5a) / 2.0, -1, 1) * 0.08

    prob = clamp(imp["D"] + signal * 0.075, 0.02, 0.75)
    return StrategyPick("D", prob, prob - imp["D"], signal)


def strategy_favorite_pressure_v3(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    fav = "H" if imp["H"] > imp["A"] else "A"
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    exp_total = getv(row, "expected_total_goals_proxy")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)
    home_adv = (getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before"))

    if fav == "H":
        signal = 0.0
        signal += clamp(ppg, -3, 3) * 0.20
        signal += clamp(form5, -3, 3) * 0.22
        signal += clamp(form10, -3, 3) * 0.10
        signal += clamp(exp_diff, -2, 2) * 0.24
        signal += clamp(home_adv, -2, 2) * 0.12
        signal += clamp(exp_total - 5.3, -2, 2) * 0.08
        signal += clamp(vol - 0.6, -1, 1) * 0.04
        prob = clamp(imp["H"] + signal * 0.06, 0.03, 0.95)
        return StrategyPick("H", prob, prob - imp["H"], signal)
    signal = 0.0
    signal += clamp(-ppg, -3, 3) * 0.20
    signal += clamp(-form5, -3, 3) * 0.22
    signal += clamp(-form10, -3, 3) * 0.10
    signal += clamp(-exp_diff, -2, 2) * 0.24
    signal += clamp(-home_adv, -2, 2) * 0.12
    signal += clamp(exp_total - 5.3, -2, 2) * 0.08
    signal += clamp(vol - 0.6, -1, 1) * 0.04
    prob = clamp(imp["A"] + signal * 0.06, 0.03, 0.95)
    return StrategyPick("A", prob, prob - imp["A"], signal)


def strategy_collapse_favorite_fade_v3(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)
    ga5h = getv(row, "home_ga_avg5")
    ga5a = getv(row, "away_ga_avg5")
    home_adv = (getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before"))

    if fav == "H":
        signal = 0.0
        signal += clamp(-form5, -3, 3) * 0.26
        signal += clamp(-form10, -3, 3) * 0.12
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(vol - 0.7, -1, 1) * 0.10
        signal += clamp(ga5h - 2.6, -2, 2) * 0.16
        signal += clamp(-home_adv, -2, 2) * 0.08
        signal += clamp(-ppg, -3, 3) * 0.10
        prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.9)
        return StrategyPick(dog, prob, prob - imp[dog], signal)
    signal = 0.0
    signal += clamp(form5, -3, 3) * 0.26
    signal += clamp(form10, -3, 3) * 0.12
    signal += clamp(exp_diff, -2, 2) * 0.18
    signal += clamp(vol - 0.7, -1, 1) * 0.10
    signal += clamp(ga5a - 2.6, -2, 2) * 0.16
    signal += clamp(home_adv, -2, 2) * 0.08
    signal += clamp(ppg, -3, 3) * 0.10
    prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.9)
    return StrategyPick(dog, prob, prob - imp[dog], signal)


def strategy_defensive_wall_v3(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    dog = "H" if imp["H"] < imp["A"] else "A"
    exp_total = getv(row, "expected_total_goals_proxy")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)
    ga10h = getv(row, "home_ga_avg10")
    ga10a = getv(row, "away_ga_avg10")
    form5 = getv(row, "strength_diff_form5")
    ppg = getv(row, "strength_diff_ppg")

    if dog == "H":
        signal = 0.0
        signal += clamp(2.4 - ga10h, -1.5, 1.5) * 0.26
        signal += clamp(5.4 - exp_total, -2, 2) * 0.18
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(0.8 - vol, -1, 1) * 0.10
        signal += clamp(-form5, -3, 3) * 0.16
        signal += clamp(-ppg, -3, 3) * 0.08
        prob = clamp(imp["H"] + signal * 0.075, 0.02, 0.9)
        return StrategyPick("H", prob, prob - imp["H"], signal)
    signal = 0.0
    signal += clamp(2.4 - ga10a, -1.5, 1.5) * 0.26
    signal += clamp(5.4 - exp_total, -2, 2) * 0.18
    signal += clamp(exp_diff, -2, 2) * 0.18
    signal += clamp(0.8 - vol, -1, 1) * 0.10
    signal += clamp(form5, -3, 3) * 0.16
    signal += clamp(ppg, -3, 3) * 0.08
    prob = clamp(imp["A"] + signal * 0.075, 0.02, 0.9)
    return StrategyPick("A", prob, prob - imp["A"], signal)


def strategy_high_event_anti_draw_v3(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None
    exp_total = getv(row, "expected_total_goals_proxy")
    vol = ((getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5") + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0)
    exp_diff = getv(row, "expected_goal_diff_proxy")
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")

    if abs(exp_diff) < 0.25:
        market = "H" if imp["H"] >= imp["A"] else "A"
    else:
        market = "H" if exp_diff > 0 else "A"

    signal = 0.0
    signal += clamp(exp_total - 6.0, -2, 2) * 0.22
    signal += clamp(vol - 0.9, -1, 1) * 0.20
    signal += clamp(abs(exp_diff) - 0.4, -1.5, 1.5) * 0.22
    signal += clamp(abs(ppg) - 0.4, -1.5, 1.5) * 0.10
    signal += clamp(abs(form5) - 0.3, -1.5, 1.5) * 0.10
    signal += clamp(-imp["D"] + 0.28, -0.2, 0.2) * 1.2

    prob = clamp(imp[market] + signal * 0.055, 0.02, 0.9)
    return StrategyPick(market, prob, prob - imp[market], signal)


STRATEGIES = {
    "underdog_live_v2": strategy_underdog_live_v2,
    "draw_tight_lowevent_v3": strategy_draw_tight_lowevent_v3,
    "favorite_pressure_v3": strategy_favorite_pressure_v3,
    "collapse_favorite_fade_v3": strategy_collapse_favorite_fade_v3,
    "defensive_wall_v3": strategy_defensive_wall_v3,
    "high_event_anti_draw_v3": strategy_high_event_anti_draw_v3,
}

PRESETS = {
    "quick": {
        "thresholds": [0.015, 0.02],
        "min_history": [5, 10],
        "stake_modes": ["flat_1000", "pct_1.0"],
    },
    "core": {
        "thresholds": [0.015, 0.02, 0.03],
        "min_history": [5, 10, 15],
        "stake_modes": ["flat_1000", "pct_0.75", "pct_1.0", "pct_1.25"],
    },
    "wide": {
        "thresholds": [0.01, 0.015, 0.02, 0.03, 0.04],
        "min_history": [5, 10, 15, 20],
        "stake_modes": ["flat_1000", "pct_0.75", "pct_1.0", "pct_1.25", "pct_1.5"],
    },
}


def load_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    q = f"""
        SELECT *
        FROM {FEATURE_TABLE}
        WHERE result_1x2_rt IN ('H','D','A')
          AND odds_home IS NOT NULL AND odds_draw IS NOT NULL AND odds_away IS NOT NULL
        ORDER BY substr(match_date, 7, 4), substr(match_date, 4, 2), substr(match_date, 1, 2), league, home_team, away_team
    """
    return conn.execute(q).fetchall()


def iterate_combos(rows: List[sqlite3.Row], starting_bankroll: float, flat_stake: float,
                   thresholds: List[float], min_history_grid: List[int], strategies: List[str],
                   stake_modes: List[str]) -> Tuple[List[dict], List[dict], List[dict], List[dict]]:
    scan_rows: List[dict] = []
    league_rows: List[dict] = []
    monthly_rows: List[dict] = []
    yearly_rows: List[dict] = []

    history_filtered_cache = {}
    for min_history in min_history_grid:
        history_filtered_cache[min_history] = [r for r in rows if history_ok(r, min_history)]

    for strategy in strategies:
        fn = STRATEGIES[strategy]
        for threshold in thresholds:
            for min_history in min_history_grid:
                filtered = history_filtered_cache[min_history]
                for stake_mode in stake_modes:
                    tracker = ComboTracker(starting_bankroll, flat_stake, stake_mode)
                    for row in filtered:
                        pick = fn(row)
                        if not pick or pick.edge < threshold:
                            continue
                        odds = pick_odds(row, pick.market)
                        if not odds:
                            continue
                        result = row["result_1x2_rt"]
                        won = result == pick.market
                        year_key = (str(row["season_key"]).split("/")[0] if row["season_key"] else str(row["match_date"])[6:10])
                        month_key = f"{str(row['match_date'])[6:10]}-{str(row['match_date'])[3:5]}"
                        league = row["league"]
                        tracker.add_bet(won, odds, year_key, month_key, league)
                    tracker.finalize()
                    base = tracker.scan_row(strategy, stake_mode, threshold, min_history)
                    scan_rows.append(base)

                    for league, d in tracker.leagues.items():
                        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
                        hit = (d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0
                        league_rows.append({
                            **{k: base[k] for k in ["strategy", "stake_mode", "threshold", "min_history"]},
                            "league": league,
                            "bets": d["bets"],
                            "wins": d["wins"],
                            "hit_rate": round(hit, 4),
                            "profit": round(d["profit"], 2),
                            "roi": round(roi, 4),
                        })
                    for month, d in tracker.monthly.items():
                        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
                        hit = (d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0
                        monthly_rows.append({
                            **{k: base[k] for k in ["strategy", "stake_mode", "threshold", "min_history"]},
                            "month": month,
                            "bets": d["bets"],
                            "wins": d["wins"],
                            "hit_rate": round(hit, 4),
                            "profit": round(d["profit"], 2),
                            "roi": round(roi, 4),
                        })
                    for year, d in tracker.yearly.items():
                        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
                        hit = (d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0
                        yearly_rows.append({
                            **{k: base[k] for k in ["strategy", "stake_mode", "threshold", "min_history"]},
                            "year": year,
                            "bets": d["bets"],
                            "wins": d["wins"],
                            "hit_rate": round(hit, 4),
                            "profit": round(d["profit"], 2),
                            "roi": round(roi, 4),
                        })
    return scan_rows, league_rows, monthly_rows, yearly_rows


def write_csv(path: str, rows: List[dict]):
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: str, scan_rows: List[dict], league_rows: List[dict]):
    top_scan = sorted(scan_rows, key=lambda x: (x["roi"], x["net_profit"]), reverse=True)[:25]
    league_focus = [r for r in league_rows if r["bets"] >= 20]
    top_leagues = sorted(league_focus, key=lambda x: (x["roi"], x["profit"]), reverse=True)[:40]
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Hockey v3 strategy report\n\n")
        f.write("## Top strategy combinations\n\n")
        for r in top_scan:
            f.write(
                f"- {r['strategy']} | {r['stake_mode']} | thr={r['threshold']:.3f} | mh={r['min_history']} "
                f"| bets={r['bets']} | ROI={r['roi']:.2f}% | profit={r['net_profit']:.2f} "
                f"| years={r['profitable_years']}/{r['total_years']} | DD={r['max_drawdown_pct']:.2f}% | end={r['ending_bankroll']:.2f}\n"
            )
        f.write("\n## Top league slices (min 20 bets)\n\n")
        for r in top_leagues:
            f.write(
                f"- {r['strategy']} | {r['league']} | {r['stake_mode']} | thr={r['threshold']:.3f} | mh={r['min_history']} "
                f"| bets={r['bets']} | ROI={r['roi']:.2f}% | profit={r['profit']:.2f}\n"
            )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--reports-dir", required=True)
    p.add_argument("--starting-bankroll", type=float, default=100000.0)
    p.add_argument("--flat-stake", type=float, default=1000.0)
    p.add_argument("--preset", choices=sorted(PRESETS.keys()), default="core")
    p.add_argument("--thresholds", type=float, nargs="*")
    p.add_argument("--min-history-grid", type=int, nargs="*")
    p.add_argument("--stake-modes", nargs="*")
    p.add_argument("--strategies", nargs="*")
    return p.parse_args()


def main():
    args = parse_args()
    preset = PRESETS[args.preset]
    thresholds = args.thresholds if args.thresholds else preset["thresholds"]
    min_history_grid = args.min_history_grid if args.min_history_grid else preset["min_history"]
    stake_modes = args.stake_modes if args.stake_modes else preset["stake_modes"]
    strategies = args.strategies if args.strategies else list(STRATEGIES.keys())

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    print(f"Loaded feature rows: {len(rows)}")

    scan_rows, league_rows, monthly_rows, yearly_rows = iterate_combos(
        rows, args.starting_bankroll, args.flat_stake,
        thresholds, min_history_grid, strategies, stake_modes
    )

    scan_rows.sort(key=lambda x: (x["roi"], x["net_profit"]), reverse=True)
    league_rows.sort(key=lambda x: (x["roi"], x["profit"], x["bets"]), reverse=True)
    monthly_rows.sort(key=lambda x: (x["strategy"], x["month"], x["stake_mode"], x["threshold"], x["min_history"]))
    yearly_rows.sort(key=lambda x: (x["strategy"], x["year"], x["stake_mode"], x["threshold"], x["min_history"]))

    os.makedirs(args.reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    scan_path = os.path.join(args.reports_dir, f"hockey_v3_strategy_scan_{ts}.csv")
    leagues_path = os.path.join(args.reports_dir, f"hockey_v3_strategy_leagues_{ts}.csv")
    monthly_path = os.path.join(args.reports_dir, f"hockey_v3_strategy_monthly_{ts}.csv")
    yearly_path = os.path.join(args.reports_dir, f"hockey_v3_strategy_yearly_{ts}.csv")
    report_path = os.path.join(args.reports_dir, f"hockey_v3_strategy_report_{ts}.md")

    write_csv(scan_path, scan_rows)
    write_csv(leagues_path, league_rows)
    write_csv(monthly_path, monthly_rows)
    write_csv(yearly_path, yearly_rows)
    write_report(report_path, scan_rows, league_rows)

    print("Saved files:")
    print(scan_path)
    print(leagues_path)
    print(monthly_path)
    print(yearly_path)
    print(report_path)

    print("\nTop 15 combos:")
    for r in scan_rows[:15]:
        print(
            f"{r['strategy']:<28} | {r['stake_mode']:<9} | thr={r['threshold']:.3f} | mh={r['min_history']:<2} "
            f"| bets={r['bets']:<5} | ROI={r['roi']:.2f}% | profit={r['net_profit']:.2f} | years={r['profitable_years']}/{r['total_years']}"
        )


if __name__ == "__main__":
    main()
