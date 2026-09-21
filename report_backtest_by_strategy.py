import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime

DB_PATH = "betagent.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_json_safe(x):
    if not x:
        return {}
    try:
        return json.loads(x)
    except Exception:
        return {}


def detect_strategy(row):
    rec = parse_json_safe(row["recommendation_json"])

    live_rule_family = rec.get("live_rule_family")
    strategy_name = rec.get("strategy_name")
    strategy_family = rec.get("strategy_family")
    market_error = str(rec.get("market_error") or "")
    market_error_summary = str(rec.get("market_error_summary") or "")

    if live_rule_family:
        return str(live_rule_family)

    if strategy_name:
        return str(strategy_name)

    if strategy_family:
        return str(strategy_family)

    if market_error_summary.startswith("Rule-driven:"):
        return market_error_summary.split(":", 1)[1].strip()

    if market_error.startswith("Hockey strategy "):
        tmp = market_error.replace("Hockey strategy ", "", 1)
        return tmp.split(":", 1)[0].strip()

    if rec.get("shadow_only") or "Heuristic fallback without LLM" in market_error:
        return "heuristic_shadow"

    if rec.get("rule_driven"):
        return f"rule_driven:{rec.get('market', 'unknown')}"

    return "llm_main"


def load_handoff_rows(conn, sport=None, run_mode="backtest", only_valid=False):
    q = """
    SELECT *
    FROM handoff_decisions
    WHERE run_mode = ?
    """
    params = [run_mode]

    if sport:
        q += " AND sport = ?"
        params.append(sport)

    if only_valid:
        q += " AND valid = 1"

    q += " ORDER BY id"

    return conn.execute(q, params).fetchall()


def get_actual_result_football(conn, match_id):
    row = conn.execute("""
        SELECT home_score, away_score
        FROM backtest_matches
        WHERE id = ?
    """, (match_id,)).fetchone()

    if not row:
        return None

    hs, aw = row["home_score"], row["away_score"]
    if hs is None or aw is None:
        return None

    if hs > aw:
        return "home"
    if aw > hs:
        return "away"
    return "draw"


def get_actual_result_hockey(conn, match_id):
    row = conn.execute("""
        SELECT home_score, away_score, result_1x2_rt
        FROM backtest_hockey_matches
        WHERE id = ?
    """, (match_id,)).fetchone()

    if not row:
        return None

    r = row["result_1x2_rt"]
    if r:
        r = str(r).upper()
        if r == "H":
            return "home"
        if r == "A":
            return "away"
        if r == "D":
            return "draw"

    hs, aw = row["home_score"], row["away_score"]
    if hs is None or aw is None:
        return None

    if hs > aw:
        return "home"
    if aw > hs:
        return "away"
    return "draw"


def settle_market(sport, market, actual_result):
    if actual_result is None:
        return None

    if market in ("home", "away", "draw"):
        return market == actual_result

    return None


def init_stat():
    return {
        "seen": 0,
        "bet": 0,
        "small": 0,
        "pass": 0,
        "valid": 0,
        "invalid": 0,
        "validator_rejected": 0,
        "scored": 0,
        "won": 0,
        "lost": 0,
        "staked": 0.0,
        "profit": 0.0,
        "ev_sum": 0.0,
        "odds_sum": 0.0,
        "stake_sum": 0.0,
        "equity": 0.0,
        "peak": 0.0,
        "max_dd_abs": 0.0,
        "max_dd_pct": 0.0,
        "cur_ls": 0,
        "max_ls": 0,
        "cur_ws": 0,
        "max_ws": 0,
    }


def update_drawdown(stat, pnl):
    stat["equity"] += pnl
    if stat["equity"] > stat["peak"]:
        stat["peak"] = stat["equity"]
    dd_abs = stat["peak"] - stat["equity"]
    if dd_abs > stat["max_dd_abs"]:
        stat["max_dd_abs"] = dd_abs
    if stat["peak"] > 0:
        dd_pct = dd_abs / stat["peak"] * 100.0
        if dd_pct > stat["max_dd_pct"]:
            stat["max_dd_pct"] = dd_pct


def update_streaks(stat, won):
    if won is True:
        stat["cur_ws"] += 1
        stat["cur_ls"] = 0
        stat["max_ws"] = max(stat["max_ws"], stat["cur_ws"])
    elif won is False:
        stat["cur_ls"] += 1
        stat["cur_ws"] = 0
        stat["max_ls"] = max(stat["max_ls"], stat["cur_ls"])
    else:
        stat["cur_ws"] = 0
        stat["cur_ls"] = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["football", "hockey"], default=None)
    ap.add_argument("--run-mode", default="backtest")
    ap.add_argument("--only-valid", action="store_true")
    ap.add_argument("--only-rule-driven", action="store_true")
    ap.add_argument("--exclude-heuristic", action="store_true")
    ap.add_argument("--flat-stake", type=float, default=1000.0)
    args = ap.parse_args()

    conn = get_conn()
    rows = load_handoff_rows(conn, sport=args.sport, run_mode=args.run_mode, only_valid=args.only_valid)

    stats = defaultdict(init_stat)

    for row in rows:
        strategy = detect_strategy(row)
        rec = parse_json_safe(row["recommendation_json"])

        if args.only_rule_driven and not rec.get("rule_driven", False):
            continue

        if args.exclude_heuristic and strategy == "heuristic_shadow":
            continue

        league = row["league"] or "unknown"
        sport = row["sport"] or "unknown"
        key = f"{sport} | {league} | {strategy}"

        stat = stats[key]
        stat["seen"] += 1

        decision = row["decision"] or "PASS"
        if decision == "BET":
            stat["bet"] += 1
        elif decision == "SMALL":
            stat["small"] += 1
        else:
            stat["pass"] += 1

        valid = int(row["valid"] or 0)
        if valid:
            stat["valid"] += 1
        else:
            stat["invalid"] += 1

        if int(row["validator_rejected"] or 0):
            stat["validator_rejected"] += 1

        odds = row["odds"]
        ev = row["ev"]
        market = row["market"]

        if odds is not None and decision in ("BET", "SMALL") and valid:
            stat["odds_sum"] += float(odds)
            if ev is not None:
                stat["ev_sum"] += float(ev)

            stake = float(args.flat_stake)
            stat["stake_sum"] += stake
            stat["staked"] += stake

            if sport == "football":
                actual_result = get_actual_result_football(conn, row["match_id"])
            elif sport == "hockey":
                actual_result = get_actual_result_hockey(conn, row["match_id"])
            else:
                actual_result = None

            won = settle_market(sport, market, actual_result)

            if won is None:
                continue

            stat["scored"] += 1

            if won:
                stat["won"] += 1
                pnl = stake * (float(odds) - 1.0)
                stat["profit"] += pnl
                update_drawdown(stat, pnl)
                update_streaks(stat, True)
            else:
                stat["lost"] += 1
                pnl = -stake
                stat["profit"] += pnl
                update_drawdown(stat, pnl)
                update_streaks(stat, False)

    rows_out = []
    for key, st in stats.items():
        placed = st["bet"] + st["small"]
        roi = (st["profit"] / st["staked"] * 100.0) if st["staked"] > 0 else 0.0
        hit = (st["won"] / st["scored"] * 100.0) if st["scored"] > 0 else 0.0
        avg_odds = (st["odds_sum"] / st["scored"]) if st["scored"] > 0 else 0.0
        avg_ev = (st["ev_sum"] / st["scored"]) if st["scored"] > 0 else 0.0

        rows_out.append({
            "key": key,
            "seen": st["seen"],
            "bet": st["bet"],
            "small": st["small"],
            "pass": st["pass"],
            "valid": st["valid"],
            "invalid": st["invalid"],
            "rejected": st["validator_rejected"],
            "scored": st["scored"],
            "won": st["won"],
            "lost": st["lost"],
            "staked": st["staked"],
            "profit": st["profit"],
            "roi": roi,
            "hit": hit,
            "avg_odds": avg_odds,
            "avg_ev": avg_ev,
            "max_dd_abs": st["max_dd_abs"],
            "max_dd_pct": st["max_dd_pct"],
            "max_ls": st["max_ls"],
            "max_ws": st["max_ws"],
        })

    rows_out.sort(key=lambda x: (x["roi"], x["profit"], x["scored"]), reverse=True)

    print("=" * 120)
    print("WHITE BACKTEST BY STRATEGY")
    print("=" * 120)
    print(f"run_mode={args.run_mode} | sport={args.sport or 'all'} | flat_stake={args.flat_stake:.2f} | "
          f"only_valid={args.only_valid} | only_rule_driven={args.only_rule_driven} | exclude_heuristic={args.exclude_heuristic}")
    print("=" * 120)

    for r in rows_out:
        print(
            f"{r['key']}\n"
            f"  seen={r['seen']} | BET={r['bet']} | SMALL={r['small']} | PASS={r['pass']} | "
            f"valid={r['valid']} | invalid={r['invalid']} | rejected={r['rejected']}\n"
            f"  scored={r['scored']} | W={r['won']} | L={r['lost']} | hit={r['hit']:.2f}%\n"
            f"  staked={r['staked']:.2f} | profit={r['profit']:+.2f} | ROI={r['roi']:+.2f}%\n"
            f"  avg_odds={r['avg_odds']:.3f} | avg_ev={r['avg_ev']:+.4f} | "
            f"maxDD={r['max_dd_abs']:.2f} ({r['max_dd_pct']:.2f}%) | maxLS={r['max_ls']} | maxWS={r['max_ws']}"
        )

    print("=" * 120)
    conn.close()


if __name__ == "__main__":
    main()
