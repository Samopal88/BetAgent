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


class Tracker:
    def __init__(self, starting_bankroll: float):
        self.starting_bankroll = starting_bankroll
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
        self.monthly = defaultdict(lambda: {"bets": 0, "wins": 0, "staked": 0.0, "profit": 0.0, "bankroll": None})
        self.yearly = defaultdict(lambda: {"bets": 0, "wins": 0, "staked": 0.0, "profit": 0.0, "bankroll": None})
        self.seasonal = defaultdict(lambda: {"bets": 0, "wins": 0, "staked": 0.0, "profit": 0.0, "bankroll": None})

    def add_bet(self, won: bool, odds: float, stake: float, month_key: str, year_key: str, season_key: str):
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

        for bucket_name in (month_key, year_key, season_key):
            pass

        for key, bucket_dict in (
            (month_key, self.monthly),
            (year_key, self.yearly),
            (season_key, self.seasonal),
        ):
            bucket = bucket_dict[key]
            bucket["bets"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["staked"] += stake
            bucket["profit"] += profit
            bucket["bankroll"] = self.bankroll

    def summary(self) -> dict:
        profit = self.total_return - self.total_staked
        roi = (profit / self.total_staked * 100.0) if self.total_staked else 0.0
        hit = (self.wins / self.bets * 100.0) if self.bets else 0.0
        avg_odds = (self.total_odds / self.bets) if self.bets else 0.0
        return {
            "bets": self.bets,
            "wins": self.wins,
            "hit_rate": round(hit, 4),
            "avg_odds": round(avg_odds, 4),
            "profit": round(profit, 2),
            "roi": round(roi, 4),
            "ending_bankroll": round(self.bankroll, 2),
            "max_drawdown_abs": round(self.max_dd_abs, 2),
            "max_drawdown_pct": round(self.max_dd_pct, 4),
            "max_losing_streak": self.max_losing_streak,
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


def getv(row: sqlite3.Row, key: str, default: float = 0.0) -> float:
    try:
        v = safe_float(row[key])
        return default if v is None else v
    except Exception:
        return default


def parse_ddmmyyyy(s: str) -> Tuple[int, int, int]:
    if not s or len(s) < 10:
        return 0, 0, 0
    return int(s[6:10]), int(s[3:5]), int(s[0:2])


def season_key_from_date(date_str: str) -> str:
    y, m, _ = parse_ddmmyyyy(date_str)
    if not y:
        return "unknown"
    if m >= 9:
        return f"{y}/{y+1}"
    return f"{y-1}/{y}"


def season_year_start_from_key(sk: str) -> str:
    if sk and "/" in sk:
        return sk.split("/")[0]
    return "unknown"


def month_key_from_date(date_str: str) -> str:
    y, m, _ = parse_ddmmyyyy(date_str)
    return f"{y:04d}-{m:02d}" if y and m else "unknown"


def classify_competition(league: str) -> str:
    s = (league or "").lower()
    if any(x in s for x in ["плей-офф", "playoff", "play-offs", "play off"]):
        return "playoff"
    if any(x in s for x in ["cup", "кубок", "champions league", "лига чемпионов", "memorial", "мемориал"]):
        return "cup"
    return "regular"


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


def odds_for_market(row: sqlite3.Row, market: str) -> Optional[float]:
    mapping = {"H": "odds_home", "D": "odds_draw", "A": "odds_away"}
    try:
        val = safe_float(row[mapping[market]])
    except Exception:
        val = None
    if not val or val <= 1.01:
        return None
    return val


def history_games(row: sqlite3.Row) -> int:
    candidates = [
        "home_games_before", "away_games_before",
        "team_games_before_home", "team_games_before_away",
        "form5_games_home", "form5_games_away",
    ]
    vals = []
    for c in candidates:
        try:
            vals.append(int(row[c] or 0))
        except Exception:
            pass
    return min(vals) if vals else 999999


# ----- strategies -----

def strategy_underdog_live(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None

    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = (getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5")
           + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0
    home_edge = getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before")
    home_attack = getv(row, "home_gf_avg5") - getv(row, "away_ga_avg5")
    away_attack = getv(row, "away_gf_avg5") - getv(row, "home_ga_avg5")

    if imp["H"] < imp["A"]:
        signal = 0.0
        signal += clamp(-ppg, 0, 3) * 0.18
        signal += clamp(-form5, 0, 3) * 0.24
        signal += clamp(home_edge, -2, 2) * 0.12
        signal += clamp(home_attack, -2, 2) * 0.14
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(1.0 - vol, -1, 1) * 0.08
        prob = clamp(imp["H"] + signal * 0.07, 0.02, 0.90)
        return StrategyPick("H", prob, prob - imp["H"], signal)
    else:
        signal = 0.0
        signal += clamp(ppg, 0, 3) * 0.18
        signal += clamp(form5, 0, 3) * 0.24
        signal += clamp(-home_edge, -2, 2) * 0.12
        signal += clamp(away_attack, -2, 2) * 0.14
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(1.0 - vol, -1, 1) * 0.08
        prob = clamp(imp["A"] + signal * 0.07, 0.02, 0.90)
        return StrategyPick("A", prob, prob - imp["A"], signal)


def strategy_collapse_favorite_fade(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None

    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"

    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = (getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5")
           + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0

    if fav == "H":
        fav_ga = getv(row, "home_ga_avg5")
        signal = 0.0
        signal += clamp(-form5, -3, 3) * 0.26
        signal += clamp(-form10, -3, 3) * 0.10
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(fav_ga - 2.5, -2, 2) * 0.18
        signal += clamp(vol - 0.8, -1, 1) * 0.10
        signal += clamp(-ppg, -3, 3) * 0.10
        prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.90)
        return StrategyPick(dog, prob, prob - imp[dog], signal)
    else:
        fav_ga = getv(row, "away_ga_avg5")
        signal = 0.0
        signal += clamp(form5, -3, 3) * 0.26
        signal += clamp(form10, -3, 3) * 0.10
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(fav_ga - 2.5, -2, 2) * 0.18
        signal += clamp(vol - 0.8, -1, 1) * 0.10
        signal += clamp(ppg, -3, 3) * 0.10
        prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.90)
        return StrategyPick(dog, prob, prob - imp[dog], signal)


def strategy_defensive_wall(row: sqlite3.Row) -> Optional[StrategyPick]:
    imp = implied_probs(row)
    if not imp:
        return None

    dog = "H" if imp["H"] < imp["A"] else "A"
    exp_total = getv(row, "expected_total_goals_proxy")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    tight = getv(row, "expected_match_tightness")
    def_bal = getv(row, "expected_defense_balance")
    form5 = getv(row, "strength_diff_form5")
    ppg = getv(row, "strength_diff_ppg")

    if dog == "H":
        ga10 = getv(row, "home_ga_avg10")
        signal = 0.0
        signal += clamp(2.4 - ga10, -1.5, 1.5) * 0.24
        signal += clamp(5.4 - exp_total, -2, 2) * 0.18
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(tight, -2, 2) * 0.10
        signal += clamp(def_bal, -2, 2) * 0.10
        signal += clamp(-form5, -3, 3) * 0.12
        signal += clamp(-ppg, -3, 3) * 0.08
        prob = clamp(imp["H"] + signal * 0.07, 0.02, 0.90)
        return StrategyPick("H", prob, prob - imp["H"], signal)
    else:
        ga10 = getv(row, "away_ga_avg10")
        signal = 0.0
        signal += clamp(2.4 - ga10, -1.5, 1.5) * 0.24
        signal += clamp(5.4 - exp_total, -2, 2) * 0.18
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(tight, -2, 2) * 0.10
        signal += clamp(def_bal, -2, 2) * 0.10
        signal += clamp(form5, -3, 3) * 0.12
        signal += clamp(ppg, -3, 3) * 0.08
        prob = clamp(imp["A"] + signal * 0.07, 0.02, 0.90)
        return StrategyPick("A", prob, prob - imp["A"], signal)


STRATEGIES = {
    "underdog_live": strategy_underdog_live,
    "collapse_favorite_fade": strategy_collapse_favorite_fade,
    "defensive_wall": strategy_defensive_wall,
}


def load_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    q = f"""
        SELECT *
        FROM {FEATURE_TABLE}
        WHERE result_1x2_rt IN ('H','D','A')
          AND odds_home IS NOT NULL
          AND odds_draw IS NOT NULL
          AND odds_away IS NOT NULL
        ORDER BY substr(match_date, 7, 4), substr(match_date, 4, 2), substr(match_date, 1, 2), league, home_team, away_team
    """
    return conn.execute(q).fetchall()


def league_filter_ok(league: str, wanted: List[str]) -> bool:
    if not wanted:
        return True
    s = (league or "").lower()
    return any(w.lower() in s for w in wanted)


def comp_filter_ok(league: str, wanted: List[str]) -> bool:
    if not wanted:
        return True
    comp = classify_competition(league)
    return comp in wanted


def market_side_ok(row: sqlite3.Row, side_mode: str) -> bool:
    if side_mode == "any":
        return True
    imp = implied_probs(row)
    if not imp:
        return False
    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"
    if side_mode == "favorite":
        return True
    if side_mode == "underdog":
        return True
    return True


def row_passes_entry_filters(
    row: sqlite3.Row,
    pick: StrategyPick,
    min_history: int,
    odds_min: float,
    odds_max: float,
    comp_types: List[str],
    leagues: List[str],
    market_mode: str,
    score_min: Optional[float],
    score_max: Optional[float],
) -> bool:
    if history_games(row) < min_history:
        return False
    if not league_filter_ok(row["league"], leagues):
        return False
    if not comp_filter_ok(row["league"], comp_types):
        return False

    odds = odds_for_market(row, pick.market)
    if not odds:
        return False
    if odds < odds_min or odds > odds_max:
        return False

    imp = implied_probs(row)
    if not imp:
        return False
    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"

    if market_mode == "favorite" and pick.market != fav:
        return False
    if market_mode == "underdog" and pick.market != dog:
        return False
    if market_mode == "home" and pick.market != "H":
        return False
    if market_mode == "away" and pick.market != "A":
        return False
    if market_mode == "draw" and pick.market != "D":
        return False

    if score_min is not None and pick.score < score_min:
        return False
    if score_max is not None and pick.score > score_max:
        return False
    return True


def backtest_combo(
    rows: List[sqlite3.Row],
    strategy_name: str,
    threshold: float,
    min_history: int,
    stake: float,
    starting_bankroll: float,
    odds_min: float,
    odds_max: float,
    comp_types: List[str],
    leagues: List[str],
    market_mode: str,
    score_min: Optional[float],
    score_max: Optional[float],
) -> Tuple[dict, List[dict], List[dict], List[dict]]:
    fn = STRATEGIES[strategy_name]
    tracker = Tracker(starting_bankroll)

    for row in rows:
        pick = fn(row)
        if not pick:
            continue
        if pick.edge < threshold:
            continue
        if not row_passes_entry_filters(row, pick, min_history, odds_min, odds_max, comp_types, leagues, market_mode, score_min, score_max):
            continue
        odds = odds_for_market(row, pick.market)
        if not odds:
            continue
        won = row["result_1x2_rt"] == pick.market
        month_key = month_key_from_date(row["match_date"])
        season_key = row["season_key"] if "season_key" in row.keys() and row["season_key"] else season_key_from_date(row["match_date"])
        year_key = season_year_start_from_key(season_key)
        tracker.add_bet(won, odds, stake, month_key, year_key, season_key)

    base = tracker.summary()
    base.update({
        "strategy": strategy_name,
        "threshold": threshold,
        "min_history": min_history,
        "odds_min": odds_min,
        "odds_max": odds_max,
        "competition_types": ",".join(comp_types) if comp_types else "all",
        "league_filter": ",".join(leagues) if leagues else "all",
        "market_mode": market_mode,
        "score_min": "" if score_min is None else score_min,
        "score_max": "" if score_max is None else score_max,
    })

    month_rows = []
    for key, d in tracker.monthly.items():
        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
        month_rows.append({
            **{k: base[k] for k in ["strategy", "threshold", "min_history", "odds_min", "odds_max",
                                    "competition_types", "league_filter", "market_mode", "score_min", "score_max"]},
            "month": key,
            "bets": d["bets"],
            "wins": d["wins"],
            "hit_rate": round((d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0, 4),
            "profit": round(d["profit"], 2),
            "roi": round(roi, 4),
            "ending_bankroll": round(d["bankroll"] or 0.0, 2),
        })

    year_rows = []
    for key, d in tracker.yearly.items():
        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
        year_rows.append({
            **{k: base[k] for k in ["strategy", "threshold", "min_history", "odds_min", "odds_max",
                                    "competition_types", "league_filter", "market_mode", "score_min", "score_max"]},
            "year": key,
            "bets": d["bets"],
            "wins": d["wins"],
            "hit_rate": round((d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0, 4),
            "profit": round(d["profit"], 2),
            "roi": round(roi, 4),
            "ending_bankroll": round(d["bankroll"] or 0.0, 2),
        })

    season_rows = []
    for key, d in tracker.seasonal.items():
        roi = (d["profit"] / d["staked"] * 100.0) if d["staked"] else 0.0
        season_rows.append({
            **{k: base[k] for k in ["strategy", "threshold", "min_history", "odds_min", "odds_max",
                                    "competition_types", "league_filter", "market_mode", "score_min", "score_max"]},
            "season": key,
            "bets": d["bets"],
            "wins": d["wins"],
            "hit_rate": round((d["wins"] / d["bets"] * 100.0) if d["bets"] else 0.0, 4),
            "profit": round(d["profit"], 2),
            "roi": round(roi, 4),
            "ending_bankroll": round(d["bankroll"] or 0.0, 2),
        })

    return base, month_rows, year_rows, season_rows


def write_csv(path: str, rows: List[dict]):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: str, scan_rows: List[dict]):
    ranked = sorted(
        [r for r in scan_rows if r["bets"] > 0],
        key=lambda x: (x["roi"], x["profit"], -x["max_drawdown_pct"]),
        reverse=True,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Hockey v4 league-first report\n\n")
        f.write("## Top combos\n\n")
        for r in ranked[:50]:
            f.write(
                f"- {r['strategy']} | league={r['league_filter']} | comp={r['competition_types']} | market={r['market_mode']} "
                f"| thr={r['threshold']:.4f} | mh={r['min_history']} | odds={r['odds_min']:.2f}-{r['odds_max']:.2f} "
                f"| bets={r['bets']} | ROI={r['roi']:.2f}% | profit={r['profit']:.2f} | bank={r['ending_bankroll']:.2f} "
                f"| DD={r['max_drawdown_pct']:.2f}% | LS={r['max_losing_streak']}\n"
            )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--reports-dir", required=True)
    p.add_argument("--starting-bankroll", type=float, default=100000.0)
    p.add_argument("--flat-stake", type=float, default=1000.0)
    p.add_argument("--strategies", nargs="*", default=list(STRATEGIES.keys()))
    p.add_argument("--thresholds", type=float, nargs="*", default=[0.0, 0.001, 0.002, 0.005, 0.01])
    p.add_argument("--min-history-grid", type=int, nargs="*", default=[3, 5, 10])
    p.add_argument("--odds-ranges", nargs="*", default=["1.10:2.20", "1.20:1.90", "1.30:1.80", "1.50:2.50", "2.20:6.00"])
    p.add_argument("--competition-types", nargs="*", default=["regular", "playoff", "cup"])
    p.add_argument("--league-filters", nargs="*", default=[])
    p.add_argument("--market-modes", nargs="*", default=["any", "underdog", "favorite"])
    p.add_argument("--score-min-grid", type=float, nargs="*", default=[])
    p.add_argument("--score-max-grid", type=float, nargs="*", default=[])
    return p.parse_args()


def parse_odds_ranges(items: List[str]) -> List[Tuple[float, float]]:
    out = []
    for item in items:
        a, b = item.split(":")
        out.append((float(a), float(b)))
    return out


def main():
    args = parse_args()
    os.makedirs(args.reports_dir, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    print(f"Loaded feature rows: {len(rows)}")

    league_filters = args.league_filters if args.league_filters else []
    if not league_filters:
        leagues = sorted({r["league"] for r in rows if r["league"]})
        league_filters = leagues

    odds_ranges = parse_odds_ranges(args.odds_ranges)
    comp_modes = [["regular"], ["playoff"], ["cup"], ["regular", "playoff", "cup"]]
    # if user passed limited comp types, keep only subsets relevant to them
    allowed = set(args.competition_types)
    comp_modes = [c for c in comp_modes if set(c).issubset(allowed)]

    score_min_grid = args.score_min_grid if args.score_min_grid else [None]
    score_max_grid = args.score_max_grid if args.score_max_grid else [None]

    scan_rows: List[dict] = []
    month_rows: List[dict] = []
    year_rows: List[dict] = []
    season_rows: List[dict] = []

    total_combos = 0
    for strategy in args.strategies:
        for threshold in args.thresholds:
            for min_history in args.min_history_grid:
                for odds_min, odds_max in odds_ranges:
                    for comp_types in comp_modes:
                        for league in league_filters:
                            for market_mode in args.market_modes:
                                for score_min in score_min_grid:
                                    for score_max in score_max_grid:
                                        if score_min is not None and score_max is not None and score_min > score_max:
                                            continue
                                        total_combos += 1
                                        base, mrows, yrows, srows = backtest_combo(
                                            rows=rows,
                                            strategy_name=strategy,
                                            threshold=threshold,
                                            min_history=min_history,
                                            stake=args.flat_stake,
                                            starting_bankroll=args.starting_bankroll,
                                            odds_min=odds_min,
                                            odds_max=odds_max,
                                            comp_types=comp_types,
                                            leagues=[league],
                                            market_mode=market_mode,
                                            score_min=score_min,
                                            score_max=score_max,
                                        )
                                        base["league_filter"] = league
                                        scan_rows.append(base)
                                        month_rows.extend(mrows)
                                        year_rows.extend(yrows)
                                        season_rows.extend(srows)

    scan_rows.sort(key=lambda x: (x["roi"], x["profit"], -x["max_drawdown_pct"]), reverse=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    scan_path = os.path.join(args.reports_dir, f"hockey_v4_scan_{ts}.csv")
    month_path = os.path.join(args.reports_dir, f"hockey_v4_monthly_{ts}.csv")
    year_path = os.path.join(args.reports_dir, f"hockey_v4_yearly_{ts}.csv")
    season_path = os.path.join(args.reports_dir, f"hockey_v4_seasonal_{ts}.csv")
    report_path = os.path.join(args.reports_dir, f"hockey_v4_report_{ts}.md")

    write_csv(scan_path, scan_rows)
    write_csv(month_path, month_rows)
    write_csv(year_path, year_rows)
    write_csv(season_path, season_rows)
    write_report(report_path, scan_rows)

    print(f"Total combos tested: {total_combos}")
    print("Saved files:")
    print(scan_path)
    print(month_path)
    print(year_path)
    print(season_path)
    print(report_path)

    print("\nTop 20:")
    for r in [x for x in scan_rows if x["bets"] > 0][:20]:
        print(
            f"{r['strategy']:<24} | {r['league_filter'][:38]:<38} | {r['competition_types']:<18} "
            f"| {r['market_mode']:<8} | thr={r['threshold']:.4f} | mh={r['min_history']:<2} "
            f"| odds={r['odds_min']:.2f}-{r['odds_max']:.2f} | bets={r['bets']:<4} | ROI={r['roi']:.2f}% | bank={r['ending_bankroll']:.2f}"
        )


if __name__ == "__main__":
    main()
