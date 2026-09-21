#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — Tennis Symmetric Inference Test

The model is already trained symmetrically (winner row + loser row per match).
The bias is in the inference path: live pipeline only evaluates P1 and hardcodes
"player1_win" as the market.

This test compares three inference strategies on the same historical data:

1. P1-ONLY (current live): evaluate P1 as "player", bet if edge > threshold
2. DUAL-EDGE: evaluate P1 as "player", derive P2 = 1 - prob, bet whichever has edge
3. SWAPPED: evaluate both orderings (P1 as player, then swap and re-evaluate),
   bet whichever side has positive edge

Strategy 3 is the gold standard — it runs the model twice per match with
swapped player/opponent features, which is the correct symmetric inference.
"""
import logging
import pickle
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(BASE_DIR / "betagent.db")
MODEL_PATH = str(BASE_DIR / "models/tennis_winner_model.pkl")
META_PATH = str(BASE_DIR / "models/tennis_winner_meta.pkl")

sys.path.insert(0, str(BASE_DIR))
from tennis_live_pipeline import (
    ALL_FEATURES, FEATURE_COLS, TennisFeatureBuilder,
    calibrate_probability, compute_ev, TENNIS_PROFILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("symmetric_test")

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)
with open(META_PATH, "rb") as f:
    meta = pickle.load(f)


def build_feature_vector(builder, p_a, p_b, date, surface):
    """Build features with p_a as 'player' and p_b as 'opponent'."""
    feat = builder.build_features(p_a, p_b, date, surface)
    if feat is None:
        return None
    return np.array([[feat.get(col, 0) for col in ALL_FEATURES]])


def run_strategy(strategy: str, matches: list, conn: sqlite3.Connection) -> dict:
    """
    strategy='p1_only': Current live — P1 as player, bet P1 if edge passes
    strategy='dual_edge': P1 as player, derive P2 = 1 - prob, bet best edge
    strategy='swapped': Run model twice (P1-as-player, P2-as-player), bet best
    """
    builder = TennisFeatureBuilder(conn)
    profile = TENNIS_PROFILE

    signals = 0
    won = 0
    lost = 0
    total_ev = 0.0
    p1_bets = 0
    p2_bets = 0
    by_surface = {}
    by_tour = {}

    # Strategy-specific thresholds
    if strategy == "p1_only":
        min_edge = 0.04
        min_ev = 0.05
        min_form = 5
    elif strategy == "dual_edge":
        min_edge = 0.04
        min_ev = 0.05
        min_form = 5
    else:  # swapped
        min_edge = 0.04
        min_ev = 0.05
        min_form = 5

    skipped_no_features = 0
    skipped_no_edge = 0
    skipped_form = 0

    for m in matches:
        p1 = m["player1"]
        p2 = m["player2"]
        actual_winner = m["actual_winner"]
        date = m["date"]
        surface = m["surface"]
        tour = m["tour"]
        # Simulated odds
        odds = 2.0
        market_p = 0.5

        # Check form for P1
        hist1 = builder._player_history(p1)
        n_form = min(10, len(hist1))
        if n_form < min_form:
            skipped_form += 1
            continue

        # --- P1 as "player" ---
        x_p1 = build_feature_vector(builder, p1, p2, date, surface)
        if x_p1 is None:
            skipped_no_features += 1
            continue

        raw_p1 = model.predict(x_p1)[0]
        has_h2h = builder._h2h(p1, p2)
        our_p1 = calibrate_probability(raw_p1, profile, n_form=n_form, has_h2h=len(has_h2h) > 0)
        edge_p1 = our_p1 - market_p
        ev_p1 = compute_ev(our_p1, odds)

        if strategy == "p1_only":
            # Only bet P1
            if edge_p1 < min_edge or ev_p1 < min_ev:
                skipped_no_edge += 1
                continue

            signals += 1
            p1_bets += 1
            total_ev += ev_p1
            if actual_winner == p1:
                won += 1
            else:
                lost += 1

        elif strategy == "dual_edge":
            # Derive P2 probability from P1 model output
            our_p2_derived = 1.0 - our_p1
            edge_p2 = our_p2_derived - market_p
            ev_p2 = compute_ev(our_p2_derived, odds)

            # Pick best side
            best_side = None
            best_edge = -999
            best_ev = 0
            best_our_p = 0

            if edge_p1 >= min_edge and ev_p1 >= min_ev:
                best_side = "p1"
                best_edge = edge_p1
                best_ev = ev_p1
                best_our_p = our_p1

            if edge_p2 >= min_edge and ev_p2 >= min_ev:
                if edge_p2 > best_edge:
                    best_side = "p2"
                    best_edge = edge_p2
                    best_ev = ev_p2
                    best_our_p = our_p2_derived

            if best_side is None:
                skipped_no_edge += 1
                continue

            signals += 1
            total_ev += best_ev
            if best_side == "p1":
                p1_bets += 1
                if actual_winner == p1:
                    won += 1
                else:
                    lost += 1
            else:
                p2_bets += 1
                if actual_winner == p2:
                    won += 1
                else:
                    lost += 1

        elif strategy == "swapped":
            # Run model with P2 as "player" too
            hist2 = builder._player_history(p2)
            n_form2 = min(10, len(hist2))

            x_p2 = build_feature_vector(builder, p2, p1, date, surface)
            if x_p2 is not None:
                raw_p2 = model.predict(x_p2)[0]
                our_p2 = calibrate_probability(raw_p2, profile, n_form=n_form2, has_h2h=len(has_h2h) > 0)
            else:
                # Fallback: derive from P1
                our_p2 = 1.0 - our_p1

            edge_p2 = our_p2 - market_p
            ev_p2 = compute_ev(our_p2, odds)

            # Pick best side
            best_side = None
            best_edge = -999
            best_ev = 0

            if edge_p1 >= min_edge and ev_p1 >= min_ev:
                best_side = "p1"
                best_edge = edge_p1
                best_ev = ev_p1

            if edge_p2 >= min_edge and ev_p2 >= min_ev:
                if edge_p2 > best_edge:
                    best_side = "p2"
                    best_edge = edge_p2
                    best_ev = ev_p2

            if best_side is None:
                skipped_no_edge += 1
                continue

            signals += 1
            total_ev += best_ev
            if best_side == "p1":
                p1_bets += 1
                if actual_winner == p1:
                    won += 1
                else:
                    lost += 1
            else:
                p2_bets += 1
                if actual_winner == p2:
                    won += 1
                else:
                    lost += 1

        # Track by surface/tour
        surf_key = surface
        by_surface.setdefault(surf_key, {"total": 0, "won": 0, "lost": 0})
        by_surface[surf_key]["total"] += 1
        if (best_side if strategy != "p1_only" else "p1") == "p1":
            if actual_winner == p1:
                by_surface[surf_key]["won"] += 1
            else:
                by_surface[surf_key]["lost"] += 1
        else:
            if actual_winner == p2:
                by_surface[surf_key]["won"] += 1
            else:
                by_surface[surf_key]["lost"] += 1

        by_tour.setdefault(tour, {"total": 0, "won": 0, "lost": 0})
        by_tour[tour]["total"] += 1
        if (best_side if strategy != "p1_only" else "p1") == "p1":
            if actual_winner == p1:
                by_tour[tour]["won"] += 1
            else:
                by_tour[tour]["lost"] += 1
        else:
            if actual_winner == p2:
                by_tour[tour]["won"] += 1
            else:
                by_tour[tour]["lost"] += 1

    hr = won / signals if signals > 0 else 0
    avg_ev = total_ev / signals if signals > 0 else 0
    stake = 0.005
    avg_odds = 2.0
    total_return = won * stake * (avg_odds - 1) - lost * stake
    roi = total_return / (signals * stake) if signals > 0 else 0

    return {
        "signals": signals, "won": won, "lost": lost,
        "hit_rate": hr, "avg_ev": avg_ev, "roi": roi,
        "p1_bets": p1_bets, "p2_bets": p2_bets,
        "p1_ratio": p1_bets / signals if signals > 0 else 0,
        "p2_ratio": p2_bets / signals if signals > 0 else 0,
        "by_surface": by_surface, "by_tour": by_tour,
        "skipped_no_features": skipped_no_features,
        "skipped_no_edge": skipped_no_edge,
        "skipped_form": skipped_form,
    }


def print_metrics(label, m):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Signals:                {m['signals']}")
    print(f"  Won/Lost:               {m['won']}W / {m['lost']}L")
    print(f"  Hit rate:               {m['hit_rate']:.1%}")
    print(f"  Avg EV:                 {m['avg_ev']:.3f}")
    print(f"  Simulated ROI:          {m['roi']:.1%}")
    print(f"  P1 bets:                {m['p1_bets']} ({m['p1_ratio']:.0%})")
    print(f"  P2 bets:                {m['p2_bets']} ({m['p2_ratio']:.0%})")
    print(f"  Skipped (form <5):      {m['skipped_form']}")
    print(f"  Skipped (no features):  {m['skipped_no_features']}")
    print(f"  Skipped (no edge/EV):   {m['skipped_no_edge']}")

    if m['by_surface']:
        print(f"\n  By surface:")
        for s, st in sorted(m['by_surface'].items(), key=lambda x: -x[1]['total']):
            hr = st['won'] / st['total'] if st['total'] > 0 else 0
            print(f"    {s:10s} {st['total']:5d} signals, HR={hr:.0%}")

    if m['by_tour']:
        print(f"\n  By tour:")
        for t, st in sorted(m['by_tour'].items(), key=lambda x: -x[1]['total'])[:10]:
            hr = st['won'] / st['total'] if st['total'] > 0 else 0
            print(f"    {t:30s} {st['total']:5d} signals, HR={hr:.0%}")


def main():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=30)

    # Load historical matches
    rows = conn.execute("""
        SELECT tourney_date, tour, surface, winner_name, loser_name
        FROM backtest_tennis_players
        WHERE tourney_date >= '2023-01-01'
        ORDER BY tourney_date
    """).fetchall()
    log.info(f"Loaded {len(rows)} historical matches")

    # Build match list: each match as it would appear in Fonbet (arbitrary ordering)
    # We use both orderings to simulate real-world randomness
    matches = []
    for row in rows:
        # Ordering 1: winner listed first
        matches.append({
            "player1": row[3], "player2": row[4],
            "actual_winner": row[3], "date": row[0],
            "surface": row[2] or "hard", "tour": row[1],
        })
        # Ordering 2: loser listed first
        matches.append({
            "player1": row[4], "player2": row[3],
            "actual_winner": row[3], "date": row[0],
            "surface": row[2] or "hard", "tour": row[1],
        })
    log.info(f"Testing {len(matches)} match evaluations (both orderings)")

    results = {}
    for strategy, label in [
        ("p1_only", "P1-ONLY (current live)"),
        ("dual_edge", "DUAL-EDGE (derive P2 = 1 - prob)"),
        ("swapped", "SWAPPED (run model twice, true symmetric)"),
    ]:
        log.info(f"Running {strategy}...")
        results[strategy] = run_strategy(strategy, matches, conn)
        print_metrics(label, results[strategy])

    # Comparison
    print(f"\n{'=' * 60}")
    print(f"  COMPARISON")
    print(f"{'=' * 60}")

    baseline = results["p1_only"]
    for strat in ("dual_edge", "swapped"):
        m = results[strat]
        delta_hr = m['hit_rate'] - baseline['hit_rate']
        delta_roi = m['roi'] - baseline['roi']
        delta_sig = m['signals'] - baseline['signals']
        print(f"\n  {strat.upper()} vs P1-ONLY:")
        print(f"    Signals:    {baseline['signals']} -> {m['signals']} ({delta_sig:+d}, {delta_sig/baseline['signals']:+.0%})")
        print(f"    Hit rate:   {baseline['hit_rate']:.1%} -> {m['hit_rate']:.1%} ({delta_hr:+.1%})")
        print(f"    ROI:        {baseline['roi']:.1%} -> {m['roi']:.1%} ({delta_roi:+.1%})")
        print(f"    Avg EV:     {baseline['avg_ev']:.3f} -> {m['avg_ev']:.3f}")
        print(f"    P1/P2:      {m['p1_ratio']:.0%}/{m['p2_ratio']:.0%}")

    # Consistency check: does swapped model output satisfy P2 ≈ 1 - P1?
    log.info("\nChecking model symmetry: P2(swapped) vs 1-P1...")
    builder = TennisFeatureBuilder(conn)
    sample = matches[:100]
    diffs = []
    for m in sample:
        x1 = build_feature_vector(builder, m["player1"], m["player2"], m["date"], m["surface"])
        x2 = build_feature_vector(builder, m["player2"], m["player1"], m["date"], m["surface"])
        if x1 is not None and x2 is not None:
            p1 = model.predict(x1)[0]
            p2 = model.predict(x2)[0]
            diffs.append(abs(p2 - (1 - p1)))
    if diffs:
        log.info(f"  Mean |P2_swapped - (1-P1)|: {np.mean(diffs):.6f}")
        log.info(f"  Max  |P2_swapped - (1-P1)|: {np.max(diffs):.6f}")
        log.info(f"  Median: {np.median(diffs):.6f}")
        if np.mean(diffs) < 0.01:
            log.info("  -> Model is nearly symmetric. dual_edge ≈ swapped.")
        else:
            log.info("  -> Model has asymmetry. swapped is more accurate than dual_edge.")

    print(f"\n  Time: {time.time() - t0:.1f}s")
    conn.close()


if __name__ == "__main__":
    main()
