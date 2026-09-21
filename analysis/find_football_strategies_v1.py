#!/usr/bin/env python3
"""
Football Strategies Systematic Search v1
BetAgent - football_features_ml_v1

Evaluates strategies where outcome data exists:
1. Base Total O/U (home_score + away_score vs total_line)
2. BTTS (home_score > 0 AND away_score > 0)

NOTE: Corners and Yellow Cards have odds/lines in the DB but NO outcome columns
(home_corners, away_corners, home_yellow_cards, away_yellow_cards are absent).
These markets are reported as coverage-only until outcome data is added.

Method: systematic grid search over odds, lines, margins, probabilities, ratios.
"""

import sqlite3
import json
import os
from collections import defaultdict
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"
REPORT_PATH = "/root/betagent/analysis/football_strategies_v1_report.md"

# ============================================================
# DATA LOADING
# ============================================================

def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM football_features_ml_v1")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_year(date_str):
    if not date_str:
        return None
    return int(date_str[:4])


# ============================================================
# STRATEGY EVALUATION ENGINE
# ============================================================

def evaluate_strategy(rows, market, bet_outcome, filter_fn, label):
    """
    Evaluate a strategy:
    - filter rows by filter_fn
    - compute hit rate, avg odds, ROI overall and by year
    """
    filtered = [r for r in rows if filter_fn(r)]
    n = len(filtered)
    if n == 0:
        return None

    # Compute results
    total_stake = 0.0
    total_return = 0.0
    hits = 0
    by_year = defaultdict(lambda: {"stake": 0.0, "return": 0.0, "hits": 0, "n": 0})

    for r in filtered:
        yr = get_year(r.get("match_date"))
        if yr is None:
            continue

        # Get the odds for this bet
        odds = r.get(bet_outcome)
        if odds is None or odds <= 0 or odds > 100:
            continue

        stake = 1.0
        total_stake += stake

        # Skip rows without scores
        hs = r.get("home_score")
        as_ = r.get("away_score")
        if hs is None or as_ is None:
            continue

        # Determine if bet won
        won = False
        if bet_outcome == "odds_total_over":
            if r.get("total_line") is None:
                continue
            won = (hs + as_) > r["total_line"]
        elif bet_outcome == "odds_total_under":
            if r.get("total_line") is None:
                continue
            won = (hs + as_) < r["total_line"]
        elif bet_outcome == "odds_btts_yes":
            won = (hs > 0 and as_ > 0)
        elif bet_outcome == "odds_btts_no":
            won = (hs == 0 or as_ == 0)
        else:
            continue

        ret = odds if won else 0.0
        total_return += ret
        if won:
            hits += 1

        by_year[yr]["stake"] += stake
        by_year[yr]["return"] += ret
        if won:
            by_year[yr]["hits"] += 1
        by_year[yr]["n"] += 1

    if total_stake == 0:
        return None

    roi = (total_return - total_stake) / total_stake * 100
    hit_rate = hits / n * 100
    avg_odds = total_return / hits if hits > 0 else 0

    # Year-by-year ROI
    year_roi = {}
    for yr in sorted(by_year.keys()):
        d = by_year[yr]
        if d["stake"] > 0:
            year_roi[yr] = {
                "n": d["n"],
                "roi": round((d["return"] - d["stake"]) / d["stake"] * 100, 2),
                "hit_rate": round(d["hits"] / d["n"] * 100, 1) if d["n"] > 0 else 0
            }

    # Recent periods
    recent_2426 = {"stake": 0.0, "return": 0.0, "hits": 0, "n": 0}
    recent_2526 = {"stake": 0.0, "return": 0.0, "hits": 0, "n": 0}
    for yr, d in by_year.items():
        if yr >= 2024:
            recent_2426["stake"] += d["stake"]
            recent_2426["return"] += d["return"]
            recent_2426["hits"] += d["hits"]
            recent_2426["n"] += d["n"]
        if yr >= 2025:
            recent_2526["stake"] += d["stake"]
            recent_2526["return"] += d["return"]
            recent_2526["hits"] += d["hits"]
            recent_2526["n"] += d["n"]

    roi_2426 = None
    roi_2526 = None
    if recent_2426["stake"] > 0:
        roi_2426 = round((recent_2426["return"] - recent_2426["stake"]) / recent_2426["stake"] * 100, 2)
    if recent_2526["stake"] > 0:
        roi_2526 = round((recent_2526["return"] - recent_2526["stake"]) / recent_2526["stake"] * 100, 2)

    return {
        "market": market,
        "label": label,
        "n": n,
        "hits": hits,
        "hit_rate": round(hit_rate, 1),
        "avg_odds": round(avg_odds, 3),
        "roi": round(roi, 2),
        "year_roi": year_roi,
        "roi_2426": roi_2426,
        "n_2426": recent_2426["n"],
        "roi_2526": roi_2526,
        "n_2526": recent_2526["n"],
    }


# ============================================================
# CLASSIFICATION
# ============================================================

def classify(s):
    if s is None:
        return "REJECT"
    n = s["n"]
    roi = s["roi"]
    roi_2426 = s["roi_2426"]
    roi_2526 = s["roi_2526"]

    # Minimum sample
    min_n = 80

    if n < min_n:
        return "REJECT"

    # STRONG criteria
    if roi >= 2.0 and n >= 80:
        # Check recent periods aren't collapsing badly
        if roi_2426 is not None and roi_2426 < -5:
            return "WATCHLIST"
        if roi_2526 is not None and roi_2526 < -8:
            return "WATCHLIST"
        if roi_2426 is not None and roi_2426 >= 0:
            return "STRONG"
        if roi_2526 is not None and roi_2526 >= 0:
            return "STRONG"
        # Overall positive but recent slightly negative - watchlist
        return "WATCHLIST"

    if roi >= 0 and n >= 80:
        return "WATCHLIST"

    if n >= 50 and n < 80:
        if roi >= 3.0:
            return "FRAGILE"
        return "REJECT"

    return "REJECT"


# ============================================================
# STRATEGY DEFINITIONS
# ============================================================

def run_all_strategies(rows):
    results = []

    # ================================================================
    # SECTION A: BASE TOTAL O/U
    # ================================================================
    print("=== A. Base Total O/U ===")

    # A1. Low margin total markets
    for margin_max in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | margin_total <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("margin_total") is not None and
                    0 < r["margin_total"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A2. Total line ranges
    for line_min, line_max in [(0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0), (4.0, 4.5), (4.5, 5.5), (5.5, 10)]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line [{line_min}, {line_max})"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, lo=line_min, hi=line_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("total_line") is not None and
                    lo <= r["total_line"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A3. Exact total lines
    for line in [1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0, 4.5]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line={line}"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, ln=line, oc=outcome: (
                    r.get("has_total") and
                    r.get("total_line") is not None and
                    abs(r["total_line"] - ln) < 0.01 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A4. Odds ranges for total
    for odds_min, odds_max in [(1.05, 1.3), (1.3, 1.5), (1.5, 1.7), (1.7, 1.9), (1.9, 2.1), (2.1, 2.3), (2.3, 2.5), (2.5, 2.8), (2.8, 3.2), (3.2, 4.0), (4.0, 6.0)]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | odds [{odds_min}, {odds_max})"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, lo=odds_min, hi=odds_max, oc=outcome: (
                    r.get("has_total") and
                    r.get(oc) is not None and lo <= r.get(oc, 0) < hi
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A5. 1X2 Imbalance + Total (home favorite)
    for prob_thresh in [50, 55, 60, 65, 70, 75, 80]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | home_prob > {prob_thresh}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, pt=prob_thresh, oc=outcome: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A6. Away favorite + total
    for prob_thresh in [50, 55, 60, 65, 70, 75, 80]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | away_prob > {prob_thresh}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, pt=prob_thresh, oc=outcome: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A7. Draw-ish matches (prob_draw > X%) + total
    for prob_thresh in [26, 28, 30, 32, 34, 36]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | draw_prob > {prob_thresh}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, pt=prob_thresh, oc=outcome: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > pt/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A8. Low margin + specific line combos
    for margin_max in [2.0, 3.0, 4.0, 5.0]:
        for line_min, line_max in [(2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (1.5, 2.5)]:
            for outcome in ["odds_total_over", "odds_total_under"]:
                label = f"Total {'Over' if 'over' in outcome else 'Under'} | margin <= {margin_max}%, line [{line_min}, {line_max})"
                s = evaluate_strategy(
                    rows, "Base Total", outcome,
                    lambda r, mm=margin_max, lo=line_min, hi=line_max, oc=outcome: (
                        r.get("has_total") and
                        r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                        r.get("total_line") is not None and lo <= r["total_line"] < hi and
                        r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                    ),
                    label
                )
                if s:
                    s["classification"] = classify(s)
                    results.append(s)

    # A9. Imbalance ratio: home vs away prob > X + total
    for ratio_thresh in [1.5, 2.0, 2.5, 3.0, 4.0]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | home/away prob ratio > {ratio_thresh}"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, rt=ratio_thresh, oc=outcome: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_home") is not None and r.get("prob_1x2_away") is not None and
                    r["prob_1x2_away"] > 0 and
                    r["prob_1x2_home"] / r["prob_1x2_away"] > rt and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A10. Combined: low margin + draw-ish + total under
    for margin_max in [3.0, 4.0, 5.0, 6.0]:
        for draw_min in [28, 30, 32, 34, 36]:
            label = f"Total Under | margin <= {margin_max}%, draw_prob > {draw_min}%"
            s = evaluate_strategy(
                rows, "Base Total", "odds_total_under",
                lambda r, mm=margin_max, dm=draw_min: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                    r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A11. Contrarian: prob_total_over very high -> bet under
    for prob_thresh in [55, 60, 65, 70, 75, 80]:
        label = f"Total Under | prob_over > {prob_thresh}% (contrarian)"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_under",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and
                r.get("prob_total_over") is not None and r["prob_total_over"] > pt/100 and
                r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A12. Contrarian: prob_total_under very high -> bet over
    for prob_thresh in [55, 60, 65, 70, 75, 80]:
        label = f"Total Over | prob_under > {prob_thresh}% (contrarian)"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and
                r.get("prob_total_under") is not None and r["prob_total_under"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A13. Home favorite + total under (dominant defense)
    for prob_thresh in [60, 65, 70, 75, 80]:
        for line_min in [2.0, 2.5, 3.0]:
            label = f"Total Under | home_prob > {prob_thresh}%, line >= {line_min}"
            s = evaluate_strategy(
                rows, "Base Total", "odds_total_under",
                lambda r, pt=prob_thresh, lm=line_min: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                    r.get("total_line") is not None and r["total_line"] >= lm and
                    r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A14. Away favorite + total under
    for prob_thresh in [60, 65, 70, 75]:
        for line_min in [2.0, 2.5, 3.0]:
            label = f"Total Under | away_prob > {prob_thresh}%, line >= {line_min}"
            s = evaluate_strategy(
                rows, "Base Total", "odds_total_under",
                lambda r, pt=prob_thresh, lm=line_min: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                    r.get("total_line") is not None and r["total_line"] >= lm and
                    r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A15. Home favorite + total over (expecting goals from dominant team)
    for prob_thresh in [60, 65, 70, 75]:
        label = f"Total Over | home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A16. Balanced match (both teams 30-45%) + total
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | balanced (both 30-45%)"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r.get("prob_1x2_away") is not None and
                0.30 <= r["prob_1x2_home"] <= 0.45 and
                0.30 <= r["prob_1x2_away"] <= 0.45 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A17. Very unbalanced (home > 75%) + total over
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | home_prob > 75%"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > 0.75 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A18. Total line 2.5 + low margin
    for outcome in ["odds_total_over", "odds_total_under"]:
        for margin_max in [1.0, 2.0, 3.0, 4.0, 5.0]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=2.5, margin <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A19. Total line 3.0 + low margin
    for outcome in ["odds_total_over", "odds_total_under"]:
        for margin_max in [2.0, 3.0, 4.0, 5.0]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=3.0, margin <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("total_line") is not None and abs(r["total_line"] - 3.0) < 0.01 and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A20. Total line 2.0 + low margin
    for outcome in ["odds_total_over", "odds_total_under"]:
        for margin_max in [2.0, 3.0, 4.0]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=2.0, margin <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("total_line") is not None and abs(r["total_line"] - 2.0) < 0.01 and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A21. prob_total_over in specific ranges
    for prob_min, prob_max in [(0.40, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.90)]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | prob_over [{prob_min}, {prob_max})"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, lo=prob_min, hi=prob_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("prob_total_over") is not None and lo <= r["prob_total_over"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A22. margin_total in ranges
    for margin_min, margin_max in [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 15)]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | margin [{margin_min}, {margin_max})"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, lo=margin_min, hi=margin_max, oc=outcome: (
                    r.get("has_total") and
                    r.get("margin_total") is not None and lo <= r["margin_total"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A23. Home underdog (prob < 30%) + total over
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | home_prob < 30%"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] < 0.30 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A24. Home underdog + total under
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | home_prob < 25%"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] < 0.25 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A25. Total line 3.5+
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | line >= 3.5"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] >= 3.5 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A26. Total line <= 2.0
    for outcome in ["odds_total_over", "odds_total_under"]:
        label = f"Total {'Over' if 'over' in outcome else 'Under'} | line <= 2.0"
        s = evaluate_strategy(
            rows, "Base Total", outcome,
            lambda r, oc=outcome: (
                r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] <= 2.0 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A27. Draw-ish + total over (contrarian)
    for prob_thresh in [28, 30, 32, 34]:
        label = f"Total Over | draw_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A28. Away favorite + total over
    for prob_thresh in [50, 55, 60, 65]:
        label = f"Total Over | away_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # A29. Home favorite + total under + low margin
    for prob_thresh in [60, 65, 70]:
        for margin_max in [3.0, 4.0, 5.0]:
            label = f"Total Under | home_prob > {prob_thresh}%, margin <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", "odds_total_under",
                lambda r, pt=prob_thresh, mm=margin_max: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # A30. Total line 2.5 + draw-ish
    for draw_min in [28, 30, 32, 34]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=2.5, draw_prob > {draw_min}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, dm=draw_min, oc=outcome: (
                    r.get("has_total") and r.get("has_1x2") and
                    r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                    r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # ================================================================
    # SECTION B: BTTS
    # ================================================================
    print("=== B. BTTS ===")

    # B1. BTTS odds ranges
    for odds_min, odds_max in [(1.05, 1.4), (1.4, 1.6), (1.6, 1.8), (1.8, 1.95), (1.95, 2.1), (2.1, 2.3), (2.3, 2.5), (2.5, 2.8), (2.8, 3.2), (3.2, 4.0), (4.0, 6.0)]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | odds [{odds_min}, {odds_max})"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, lo=odds_min, hi=odds_max, oc=outcome: (
                    r.get("has_btts") and
                    r.get(oc) is not None and lo <= r.get(oc, 0) < hi
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B2. BTTS + total line combos
    for line_min, line_max in [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0), (4.0, 5.0)]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | total_line [{line_min}, {line_max})"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, lo=line_min, hi=line_max, oc=outcome: (
                    r.get("has_btts") and r.get("has_total") and
                    r.get("total_line") is not None and lo <= r["total_line"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B3. BTTS + 1X2 imbalance (home favorite)
    for prob_thresh in [50, 55, 60, 65, 70, 75, 80]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | home_prob > {prob_thresh}%"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, pt=prob_thresh, oc=outcome: (
                    r.get("has_btts") and r.get("has_1x2") and
                    r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B4. BTTS + draw-ish matches
    for prob_thresh in [26, 28, 30, 32, 34, 36]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | draw_prob > {prob_thresh}%"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, pt=prob_thresh, oc=outcome: (
                    r.get("has_btts") and r.get("has_1x2") and
                    r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > pt/100 and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B5. BTTS + low margin
    for margin_max in [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | margin_btts <= {margin_max}%"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_btts") and
                    r.get("margin_btts") is not None and 0 < r["margin_btts"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B6. BTTS + high total line (3.0+)
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | total_line >= 3.0"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] >= 3.0 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B7. BTTS + low total line (2.0 or less)
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | total_line <= 2.0"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] <= 2.0 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B8. BTTS Yes + away favorite
    for prob_thresh in [50, 55, 60, 65]:
        label = f"BTTS Yes | away_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_yes",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B9. BTTS No + strong home favorite
    for prob_thresh in [55, 60, 65, 70, 75, 80]:
        label = f"BTTS No | home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B10. BTTS + balanced match (both teams 30-45%)
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | balanced (both 30-45%)"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r.get("prob_1x2_away") is not None and
                0.30 <= r["prob_1x2_home"] <= 0.45 and
                0.30 <= r["prob_1x2_away"] <= 0.45 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B11. BTTS + prob_btts_yes ranges
    for prob_min, prob_max in [(0.35, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.85)]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | prob_yes [{prob_min}, {prob_max})"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, lo=prob_min, hi=prob_max, oc=outcome: (
                    r.get("has_btts") and
                    r.get("prob_btts_yes") is not None and lo <= r["prob_btts_yes"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B12. BTTS No + prob_btts_yes high (contrarian)
    for prob_thresh in [55, 60, 65, 70, 75]:
        label = f"BTTS No | prob_yes > {prob_thresh}% (contrarian)"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and
                r.get("prob_btts_yes") is not None and r["prob_btts_yes"] > pt/100 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B13. BTTS Yes + prob_btts_yes low (value)
    for prob_thresh in [40, 45, 50, 55]:
        label = f"BTTS Yes | prob_yes < {prob_thresh}% (value)"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_yes",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and
                r.get("prob_btts_yes") is not None and r["prob_btts_yes"] < pt/100 and
                r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B14. BTTS No + away favorite
    for prob_thresh in [55, 60, 65, 70]:
        label = f"BTTS No | away_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B15. BTTS Yes + home underdog (prob < 30%)
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | home_prob < 30%"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] < 0.30 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B16. BTTS margin ranges
    for margin_min, margin_max in [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 15)]:
        for outcome in ["odds_btts_yes", "odds_btts_no"]:
            label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | margin [{margin_min}, {margin_max})"
            s = evaluate_strategy(
                rows, "BTTS", outcome,
                lambda r, lo=margin_min, hi=margin_max, oc=outcome: (
                    r.get("has_btts") and
                    r.get("margin_btts") is not None and lo <= r["margin_btts"] < hi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # B17. BTTS Yes + total line 2.5
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | total_line = 2.5"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_total") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B18. BTTS Yes + total line 3.0+
    for outcome in ["odds_btts_yes", "odds_btts_no"]:
        label = f"BTTS {'Yes' if 'yes' in outcome else 'No'} | total_line >= 3.5"
        s = evaluate_strategy(
            rows, "BTTS", outcome,
            lambda r, oc=outcome: (
                r.get("has_btts") and r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] >= 3.5 and
                r.get(oc) is not None and 0 < r.get(oc, 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B19. BTTS No + draw-ish + total line <= 2.5
    for draw_min in [28, 30, 32, 34]:
        label = f"BTTS No | draw_prob > {draw_min}%, total_line <= 2.5"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, dm=draw_min: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                r.get("total_line") is not None and r["total_line"] <= 2.5 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # B20. BTTS Yes + home_prob > 60% (big favorite should score, opponent too?)
    for prob_thresh in [60, 65, 70]:
        label = f"BTTS Yes | home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_yes",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # ================================================================
    # SECTION X: CROSS-MARKET STRATEGIES (Total + BTTS)
    # ================================================================
    print("=== X. Cross-Market (Total + BTTS) ===")

    # X1. Low margin on both total and BTTS
    for margin_max in [2.0, 3.0, 4.0, 5.0]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | margin_total <= {margin_max}% AND margin_btts <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and r.get("has_btts") and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get("margin_btts") is not None and 0 < r["margin_btts"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # X2. Total line 2.5 + BTTS Yes odds range
    for btts_lo, btts_hi in [(1.5, 1.8), (1.8, 2.0), (2.0, 2.3), (2.3, 2.7)]:
        for outcome in ["odds_total_over", "odds_total_under"]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=2.5, BTTS Yes odds [{btts_lo},{btts_hi})"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, blo=btts_lo, bhi=btts_hi, oc=outcome: (
                    r.get("has_total") and r.get("has_btts") and
                    r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                    r.get("odds_btts_yes") is not None and blo <= r["odds_btts_yes"] < bhi and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # X3. BTTS Yes + total over (both signal goals)
    for btts_lo, btts_hi in [(1.5, 1.8), (1.8, 2.0), (2.0, 2.3)]:
        for total_lo, total_hi in [(1.7, 2.0), (2.0, 2.3), (2.3, 2.7)]:
            label = f"BTTS Yes | BTTS odds [{btts_lo},{btts_hi}), Total Over odds [{total_lo},{total_hi})"
            s = evaluate_strategy(
                rows, "BTTS", "odds_btts_yes",
                lambda r, blo=btts_lo, bhi=btts_hi, tlo=total_lo, thi=total_hi: (
                    r.get("has_btts") and r.get("has_total") and
                    r.get("odds_btts_yes") is not None and blo <= r["odds_btts_yes"] < bhi and
                    r.get("odds_total_over") is not None and tlo <= r["odds_total_over"] < thi
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # X4. Total line 2.5 + draw-ish + BTTS No
    for draw_min in [28, 30, 32, 34]:
        label = f"BTTS No | line=2.5, draw_prob > {draw_min}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, dm=draw_min: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X5. Total line 2.5 + low margin total + low margin BTTS
    for outcome in ["odds_total_over", "odds_total_under"]:
        for margin_max in [2.0, 3.0]:
            label = f"Total {'Over' if 'over' in outcome else 'Under'} | line=2.5, margin_total <= {margin_max}%, margin_btts <= {margin_max}%"
            s = evaluate_strategy(
                rows, "Base Total", outcome,
                lambda r, mm=margin_max, oc=outcome: (
                    r.get("has_total") and r.get("has_btts") and
                    r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                    r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                    r.get("margin_btts") is not None and 0 < r["margin_btts"] <= mm and
                    r.get(oc) is not None and 0 < r.get(oc, 0) < 100
                ),
                label
            )
            if s:
                s["classification"] = classify(s)
                results.append(s)

    # X6. BTTS No + total under + draw-ish (triple defensive signal)
    for draw_min in [28, 30, 32]:
        label = f"BTTS No | draw_prob > {draw_min}%, total_line <= 2.5"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, dm=draw_min: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                r.get("total_line") is not None and r["total_line"] <= 2.5 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X7. Total Over + BTTS Yes (both signal high scoring)
    for total_odds_lo, total_odds_hi in [(1.7, 2.0), (2.0, 2.5)]:
        label = f"Total Over | total_odds [{total_odds_lo},{total_odds_hi}), BTTS Yes odds < 2.0"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, tlo=total_odds_lo, thi=total_odds_hi: (
                r.get("has_total") and r.get("has_btts") and
                r.get("odds_total_over") is not None and tlo <= r["odds_total_over"] < thi and
                r.get("odds_btts_yes") is not None and r["odds_btts_yes"] < 2.0
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X8. Home strong favorite + total under (dominant defense)
    for prob_thresh in [65, 70, 75, 80]:
        label = f"Total Under | home_prob > {prob_thresh}%, line >= 2.5"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_under",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("total_line") is not None and r["total_line"] >= 2.5 and
                r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X9. BTTS No + home_prob > 70% (dominant home keeps clean sheet)
    for prob_thresh in [70, 75, 80]:
        label = f"BTTS No | home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_1x2") and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X10. BTTS Yes + balanced match + total line >= 2.5
    label = f"BTTS Yes | balanced, total_line >= 2.5"
    s = evaluate_strategy(
        rows, "BTTS", "odds_btts_yes",
        lambda r: (
            r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
            r.get("prob_1x2_home") is not None and r.get("prob_1x2_away") is not None and
            0.30 <= r["prob_1x2_home"] <= 0.45 and
            0.30 <= r["prob_1x2_away"] <= 0.45 and
            r.get("total_line") is not None and r["total_line"] >= 2.5 and
            r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
        ),
        label
    )
    if s:
        s["classification"] = classify(s)
        results.append(s)

    # X11. Total Over | line=2.5, home_prob > 55%
    for prob_thresh in [55, 60, 65]:
        label = f"Total Over | line=2.5, home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X12. Total Under | line=2.5, draw_prob > 30%
    for draw_min in [30, 32, 34]:
        label = f"Total Under | line=2.5, draw_prob > {draw_min}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_under",
            lambda r, dm=draw_min: (
                r.get("has_total") and r.get("has_1x2") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X13. BTTS No | total_line <= 2.0, margin_btts <= 5%
    for margin_max in [3.0, 4.0, 5.0, 6.0]:
        label = f"BTTS No | total_line <= 2.0, margin_btts <= {margin_max}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, mm=margin_max: (
                r.get("has_btts") and r.get("has_total") and
                r.get("total_line") is not None and r["total_line"] <= 2.0 and
                r.get("margin_btts") is not None and 0 < r["margin_btts"] <= mm and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X14. Total Over | line=3.0, margin_total <= 4%
    for margin_max in [2.0, 3.0, 4.0, 5.0]:
        label = f"Total Over | line=3.0, margin_total <= {margin_max}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, mm=margin_max: (
                r.get("has_total") and
                r.get("total_line") is not None and abs(r["total_line"] - 3.0) < 0.01 and
                r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X15. Total Under | line=3.0, margin_total <= 4%
    for margin_max in [2.0, 3.0, 4.0, 5.0]:
        label = f"Total Under | line=3.0, margin_total <= {margin_max}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_under",
            lambda r, mm=margin_max: (
                r.get("has_total") and
                r.get("total_line") is not None and abs(r["total_line"] - 3.0) < 0.01 and
                r.get("margin_total") is not None and 0 < r["margin_total"] <= mm and
                r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X16. BTTS Yes | total_line >= 3.0, home_prob > 50%
    for prob_thresh in [50, 55, 60]:
        label = f"BTTS Yes | total_line >= 3.0, home_prob > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_yes",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("total_line") is not None and r["total_line"] >= 3.0 and
                r.get("prob_1x2_home") is not None and r["prob_1x2_home"] > pt/100 and
                r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X17. BTTS No | away_prob > 55%, total_line <= 2.5
    for prob_thresh in [55, 60, 65]:
        label = f"BTTS No | away_prob > {prob_thresh}%, total_line <= 2.5"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_no",
            lambda r, pt=prob_thresh: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_away") is not None and r["prob_1x2_away"] > pt/100 and
                r.get("total_line") is not None and r["total_line"] <= 2.5 and
                r.get("odds_btts_no") is not None and 0 < r.get("odds_btts_no", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X18. Total Over | line=2.5, BTTS Yes prob > 55%
    for prob_thresh in [50, 55, 60, 65]:
        label = f"Total Over | line=2.5, prob_btts_yes > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_over",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_btts") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get("prob_btts_yes") is not None and r["prob_btts_yes"] > pt/100 and
                r.get("odds_total_over") is not None and 0 < r.get("odds_total_over", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X19. Total Under | line=2.5, BTTS No prob > 55%
    for prob_thresh in [50, 55, 60, 65]:
        label = f"Total Under | line=2.5, prob_btts_no > {prob_thresh}%"
        s = evaluate_strategy(
            rows, "Base Total", "odds_total_under",
            lambda r, pt=prob_thresh: (
                r.get("has_total") and r.get("has_btts") and
                r.get("total_line") is not None and abs(r["total_line"] - 2.5) < 0.01 and
                r.get("prob_btts_no") is not None and r["prob_btts_no"] > pt/100 and
                r.get("odds_total_under") is not None and 0 < r.get("odds_total_under", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    # X20. BTTS Yes | draw_prob > 30%, total_line >= 2.5
    for draw_min in [30, 32, 34]:
        label = f"BTTS Yes | draw_prob > {draw_min}%, total_line >= 2.5"
        s = evaluate_strategy(
            rows, "BTTS", "odds_btts_yes",
            lambda r, dm=draw_min: (
                r.get("has_btts") and r.get("has_total") and r.get("has_1x2") and
                r.get("prob_1x2_draw") is not None and r["prob_1x2_draw"] > dm/100 and
                r.get("total_line") is not None and r["total_line"] >= 2.5 and
                r.get("odds_btts_yes") is not None and 0 < r.get("odds_btts_yes", 0) < 100
            ),
            label
        )
        if s:
            s["classification"] = classify(s)
            results.append(s)

    return results


# ================================================================
# REPORT GENERATION
# ================================================================

def generate_report(all_results, rows):
    # Sort by ROI descending
    all_results.sort(key=lambda x: x["roi"] if x["roi"] is not None else -999, reverse=True)

    # Coverage summary
    total = len(rows)
    has_1x2 = sum(1 for r in rows if r.get("has_1x2"))
    has_total = sum(1 for r in rows if r.get("has_total"))
    has_btts = sum(1 for r in rows if r.get("has_btts"))
    has_corners = sum(1 for r in rows if r.get("has_corners"))
    has_yc = sum(1 for r in rows if r.get("has_yellow_cards"))

    # Separate by market
    by_market = defaultdict(list)
    for r in all_results:
        by_market[r["market"]].append(r)

    # Get top strategies per classification
    strong = [r for r in all_results if r["classification"] == "STRONG"]
    watchlist = [r for r in all_results if r["classification"] == "WATCHLIST"]
    fragile = [r for r in all_results if r["classification"] == "FRAGILE"]
    reject = [r for r in all_results if r["classification"] == "REJECT"]

    # Count hypotheses tested
    total_tested = len(all_results)

    lines = []
    lines.append("# Football Strategies v1 — Full Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Database:** betagent.db / football_features_ml_v1")
    lines.append(f"**Total matches:** {total:,}")
    lines.append(f"**Date range:** 2019–2026")
    lines.append(f"**Hypotheses tested:** {total_tested}")
    lines.append("")

    # 1. Coverage Summary
    lines.append("## 1. Coverage Summary")
    lines.append("")
    lines.append("| Market | Matches | Coverage % | Evaluable? |")
    lines.append("|--------|---------|------------|------------|")
    lines.append(f"| 1X2 | {has_1x2:,} | {has_1x2/total*100:.1f}% | Yes (but not priority) |")
    lines.append(f"| Total O/U | {has_total:,} | {has_total/total*100:.1f}% | **Yes** |")
    lines.append(f"| BTTS | {has_btts:,} | {has_btts/total*100:.1f}% | **Yes** |")
    lines.append(f"| Corners | {has_corners:,} | {has_corners/total*100:.1f}% | No (no outcome data) |")
    lines.append(f"| Yellow Cards | {has_yc:,} | {has_yc/total*100:.1f}% | No (no outcome data) |")
    lines.append("")
    lines.append("> **NOTE:** Corners and Yellow Cards have odds/lines in the database but NO outcome columns")
    lines.append("> (`home_corners`, `away_corners`, `home_yellow_cards`, `away_yellow_cards` are absent).")
    lines.append("> These markets will become evaluable once outcome data is added to the pipeline.")
    lines.append("")

    # 2. Hypotheses Tested
    lines.append("## 2. Hypotheses Tested")
    lines.append("")
    lines.append("### A. Base Total O/U")
    lines.append("- Low margin total markets (1–8%)")
    lines.append("- Total line ranges (0–1.5 to 5.5+)")
    lines.append("- Exact total lines (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0, 4.5)")
    lines.append("- Odds ranges (1.05–6.0)")
    lines.append("- 1X2 imbalance + total (home/away favorite at various thresholds)")
    lines.append("- Draw-ish matches + total")
    lines.append("- Low margin + specific line combos")
    lines.append("- Home/away prob ratio + total")
    lines.append("- Contrarian: high implied prob -> bet opposite")
    lines.append("- Home underdog + total")
    lines.append("- Balanced matches + total")
    lines.append("- Margin ranges")
    lines.append("")
    lines.append("### B. BTTS")
    lines.append("- BTTS odds ranges (1.05–6.0)")
    lines.append("- BTTS + total line combos")
    lines.append("- BTTS + 1X2 imbalance (home/away favorite)")
    lines.append("- BTTS + draw-ish matches")
    lines.append("- BTTS + low margin (2–8%)")
    lines.append("- BTTS + high/low total line")
    lines.append("- BTTS + balanced matches")
    lines.append("- Contrarian: high prob_btts_yes -> bet No")
    lines.append("- BTTS + prob_btts_yes ranges")
    lines.append("- BTTS + home underdog")
    lines.append("- BTTS margin ranges")
    lines.append("")
    lines.append("### X. Cross-Market (Total + BTTS)")
    lines.append("- Low margin on both total and BTTS simultaneously")
    lines.append("- Total line 2.5 + BTTS odds combos")
    lines.append("- Total Over + BTTS Yes (both signal goals)")
    lines.append("- BTTS No + total under + draw-ish (triple defensive)")
    lines.append("- Home strong favorite + total under")
    lines.append("- BTTS No + dominant home (clean sheet)")
    lines.append("- Total line 2.5/3.0 + margin filters")
    lines.append("- BTTS + total line + 1X2 combos")
    lines.append("- prob_btts_yes/no + total line combos")
    lines.append("")

    # 3. Classification Summary
    lines.append("## 3. Classification Summary")
    lines.append("")
    lines.append(f"| Class | Count |")
    lines.append(f"|-------|-------|")
    lines.append(f"| STRONG | {len(strong)} |")
    lines.append(f"| WATCHLIST | {len(watchlist)} |")
    lines.append(f"| FRAGILE | {len(fragile)} |")
    lines.append(f"| REJECT | {len(reject)} |")
    lines.append("")

    # 4. Top Strategies
    lines.append("## 4. Top Strategies")
    lines.append("")

    # Show all STRONG first
    if strong:
        lines.append("### STRONG Strategies")
        lines.append("")
        for i, s in enumerate(strong[:30], 1):
            lines.append(f"#### {i}. {s['label']}")
            lines.append("")
            lines.append(f"- **Market:** {s['market']}")
            lines.append(f"- **Sample:** n = {s['n']:,}")
            lines.append(f"- **Hits:** {s['hits']:,}")
            lines.append(f"- **Hit Rate:** {s['hit_rate']}%")
            lines.append(f"- **Avg Odds:** {s['avg_odds']}")
            lines.append(f"- **ROI:** {s['roi']}%")
            if s['roi_2426'] is not None:
                lines.append(f"- **ROI 2024–2026:** {s['roi_2426']}% (n={s['n_2426']:,})")
            if s['roi_2526'] is not None:
                lines.append(f"- **ROI 2025–2026:** {s['roi_2526']}% (n={s['n_2526']:,})")
            if s['year_roi']:
                lines.append(f"- **ROI by year:**")
                for yr, yr_data in s['year_roi'].items():
                    lines.append(f"  - {yr}: ROI={yr_data['roi']}%, HR={yr_data['hit_rate']}%, n={yr_data['n']:,}")
            lines.append("")

    if watchlist:
        lines.append("### WATCHLIST Strategies (Top 20)")
        lines.append("")
        for i, s in enumerate(watchlist[:20], 1):
            lines.append(f"#### {i}. {s['label']}")
            lines.append("")
            lines.append(f"- **Market:** {s['market']}")
            lines.append(f"- **Sample:** n = {s['n']:,}")
            lines.append(f"- **Hits:** {s['hits']:,}")
            lines.append(f"- **Hit Rate:** {s['hit_rate']}%")
            lines.append(f"- **Avg Odds:** {s['avg_odds']}")
            lines.append(f"- **ROI:** {s['roi']}%")
            if s['roi_2426'] is not None:
                lines.append(f"- **ROI 2024–2026:** {s['roi_2426']}% (n={s['n_2426']:,})")
            if s['roi_2526'] is not None:
                lines.append(f"- **ROI 2025–2026:** {s['roi_2526']}% (n={s['n_2526']:,})")
            if s['year_roi']:
                lines.append(f"- **ROI by year:**")
                for yr, yr_data in s['year_roi'].items():
                    lines.append(f"  - {yr}: ROI={yr_data['roi']}%, HR={yr_data['hit_rate']}%, n={yr_data['n']:,}")
            lines.append("")

    if fragile:
        lines.append("### FRAGILE Strategies (Top 10)")
        lines.append("")
        for i, s in enumerate(fragile[:10], 1):
            lines.append(f"#### {i}. {s['label']}")
            lines.append("")
            lines.append(f"- **Market:** {s['market']}")
            lines.append(f"- **Sample:** n = {s['n']:,}")
            lines.append(f"- **Hits:** {s['hits']:,}")
            lines.append(f"- **Hit Rate:** {s['hit_rate']}%")
            lines.append(f"- **Avg Odds:** {s['avg_odds']}")
            lines.append(f"- **ROI:** {s['roi']}%")
            if s['roi_2426'] is not None:
                lines.append(f"- **ROI 2024–2026:** {s['roi_2426']}% (n={s['n_2426']:,})")
            if s['roi_2526'] is not None:
                lines.append(f"- **ROI 2025–2026:** {s['roi_2526']}% (n={s['n_2526']:,})")
            lines.append("")

    # 5. Per-Market Breakdown
    lines.append("## 5. Per-Market Breakdown")
    lines.append("")

    for market_name in ["Base Total", "BTTS"]:
        market_results = by_market.get(market_name, [])
        if not market_results:
            continue

        market_strong = [r for r in market_results if r["classification"] == "STRONG"]
        market_watch = [r for r in market_results if r["classification"] == "WATCHLIST"]

        lines.append(f"### {market_name}")
        lines.append("")
        lines.append(f"- Total strategies tested: {len(market_results)}")
        lines.append(f"- STRONG: {len(market_strong)}")
        lines.append(f"- WATCHLIST: {len(market_watch)}")
        lines.append("")

        if market_strong:
            lines.append("**STRONG:**")
            lines.append("")
            lines.append("| # | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 |")
            lines.append("|---|--------|---|-----|----------|------|-----------|-----------|")
            for i, s in enumerate(market_strong[:15], 1):
                r24 = f"{s['roi_2426']}%" if s['roi_2426'] is not None else "N/A"
                r25 = f"{s['roi_2526']}%" if s['roi_2526'] is not None else "N/A"
                lines.append(f"| {i} | {s['label']} | {s['n']:,} | {s['hit_rate']} | {s['avg_odds']} | {s['roi']} | {r24} | {r25} |")
            lines.append("")

        if market_watch:
            lines.append("**WATCHLIST (top 10):**")
            lines.append("")
            lines.append("| # | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 |")
            lines.append("|---|--------|---|-----|----------|------|-----------|-----------|")
            for i, s in enumerate(market_watch[:10], 1):
                r24 = f"{s['roi_2426']}%" if s['roi_2426'] is not None else "N/A"
                r25 = f"{s['roi_2526']}%" if s['roi_2526'] is not None else "N/A"
                lines.append(f"| {i} | {s['label']} | {s['n']:,} | {s['hit_rate']} | {s['avg_odds']} | {s['roi']} | {r24} | {r25} |")
            lines.append("")

    # 6. Shortlist
    lines.append("## 6. Shortlist — Top 5 Strategies for Manual Re-Verification")
    lines.append("")

    # Pick top 5 by a composite score: ROI * sqrt(n/80) with recency bonus
    def composite_score(s):
        if s["classification"] == "REJECT":
            return -999
        base = s["roi"] * (s["n"] / 80) ** 0.5
        # Bonus for positive recent performance
        if s["roi_2426"] is not None and s["roi_2426"] > 0:
            base += 2
        if s["roi_2526"] is not None and s["roi_2526"] > 0:
            base += 2
        # Penalty for negative recent
        if s["roi_2426"] is not None and s["roi_2426"] < -3:
            base -= 3
        if s["roi_2526"] is not None and s["roi_2526"] < -5:
            base -= 3
        return base

    scored = [(s, composite_score(s)) for s in all_results if s["classification"] != "REJECT"]
    scored.sort(key=lambda x: x[1], reverse=True)

    lines.append("| Rank | Market | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 | Class |")
    lines.append("|------|--------|--------|---|-----|----------|------|-----------|-----------|-------|")
    for i, (s, score) in enumerate(scored[:5], 1):
        r24 = f"{s['roi_2426']}%" if s['roi_2426'] is not None else "N/A"
        r25 = f"{s['roi_2526']}%" if s['roi_2526'] is not None else "N/A"
        lines.append(f"| {i} | {s['market']} | {s['label']} | {s['n']:,} | {s['hit_rate']} | {s['avg_odds']} | {s['roi']} | {r24} | {r25} | {s['classification']} |")
    lines.append("")

    lines.append("### Notes on Shortlist")
    lines.append("")
    for i, (s, score) in enumerate(scored[:5], 1):
        lines.append(f"**{i}. {s['market']} — {s['label']}**")
        lines.append(f"   - ROI: {s['roi']}% over {s['n']:,} matches")
        if s['roi_2426'] is not None:
            lines.append(f"   - Recent (2024–2026): {s['roi_2426']}% ({s['n_2426']:,} matches)")
        if s['roi_2526'] is not None:
            lines.append(f"   - Very recent (2025–2026): {s['roi_2526']}% ({s['n_2526']:,} matches)")
        lines.append(f"   - Verdict: {s['classification']}")
        lines.append("")

    # 7. Full Results Table (all non-REJECT)
    lines.append("## 7. Full Results (Non-REJECT Strategies)")
    lines.append("")
    lines.append("| Market | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 | Class |")
    lines.append("|--------|--------|---|-----|----------|------|-----------|-----------|-------|")
    for s in all_results:
        if s["classification"] == "REJECT":
            continue
        r24 = f"{s['roi_2426']}%" if s['roi_2426'] is not None else "N/A"
        r25 = f"{s['roi_2526']}%" if s['roi_2526'] is not None else "N/A"
        lines.append(f"| {s['market']} | {s['label']} | {s['n']:,} | {s['hit_rate']} | {s['avg_odds']} | {s['roi']} | {r24} | {r25} | {s['classification']} |")
    lines.append("")

    # 8. Next Steps
    lines.append("## 8. Next Steps / Recommendations")
    lines.append("")
    lines.append("1. **Add outcome data for Corners and Yellow Cards** — currently only odds/lines exist,")
    lines.append("   making these markets unevaluable. Need: `home_corners`, `away_corners`,")
    lines.append("   `home_yellow_cards`, `away_yellow_cards`.")
    lines.append("2. **Manually verify top STRONG strategies** — check for data quality issues,")
    lines.append("   league concentration, and real-world bet availability.")
    lines.append("3. **League-level breakdown** — top strategies may be driven by specific leagues.")
    lines.append("   Run per-league analysis on shortlisted strategies.")
    lines.append("4. **Time-decay analysis** — check if strategies degrade over time or remain stable.")
    lines.append("5. **Kelly criterion sizing** — for confirmed strategies, compute optimal stake sizing.")
    lines.append("")

    report = "\n".join(lines)

    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"\nReport written to {REPORT_PATH}")
    print(f"Total strategies tested: {len(all_results)}")
    print(f"STRONG: {len(strong)}, WATCHLIST: {len(watchlist)}, FRAGILE: {len(fragile)}, REJECT: {len(reject)}")

    return all_results


# ================================================================
# MAIN
# ================================================================

def main():
    print("Loading data...")
    rows = load_data()
    print(f"Loaded {len(rows):,} rows")

    print("\nRunning strategy searches...")
    results = run_all_strategies(rows)
    print(f"Found {len(results)} strategies")

    print(f"\nTotal strategies: {len(results)}")
    print("\nGenerating report...")
    generate_report(results, rows)

    # Also save JSON for programmatic access
    json_path = REPORT_PATH.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"JSON saved to {json_path}")


if __name__ == "__main__":
    main()
