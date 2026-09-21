#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — Tennis Guardrails Backtest v2

Key insight from v1: P2 signals (1 - raw_prob) drag performance down.
Model is trained from P1 perspective — P1-only is the right approach.

This v2 tests:
1. OLD: P1-only, no guardrails (baseline)
2. NEW: P1-only + tour filter + odds 1.50-3.50 + EV cap 0.60
3. STRONG: P1-only + higher edge threshold (0.04) + min form 5

Uses real odds from backtest data where available.
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
    ALL_FEATURES, TennisFeatureBuilder, calibrate_probability,
    compute_ev, TENNIS_PROFILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("guardrails_v2")

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)
with open(META_PATH, "rb") as f:
    meta = pickle.load(f)


def _passes_tour_filter(league: str) -> bool:
    l = league.lower()
    blocked = ["challenger", "челлендж", "itf", "125k", "квалификац", "qualifying"]
    for kw in blocked:
        if kw in l:
            return False
    return "atp" in l or "wta" in l


def simulate(mode: str, pairs: list, conn: sqlite3.Connection) -> dict:
    """
    mode='old': P1-only, no guardrails (baseline)
    mode='guardrails': P1-only + tour filter + odds 1.50-3.50 + EV cap 0.60
    mode='strong': P1-only + higher edge (0.04) + min form 5
    """
    builder = TennisFeatureBuilder(conn)
    profile = TENNIS_PROFILE

    signals = 0
    won = 0
    lost = 0
    total_ev = 0.0
    total_edge = 0.0
    skipped_tour = 0
    skipped_odds = 0
    skipped_ev_cap = 0
    skipped_edge = 0
    skipped_form = 0
    by_tour = {}
    by_surface = {}

    for pair in pairs:
        p1 = pair["player1"]
        p2 = pair["player2"]
        tourney_date = pair["tourney_date"]
        surface = pair["surface"]
        tour = pair["tour"]

        # Tour filter (guardrails + strong modes)
        if mode in ("guardrails", "strong") and not _passes_tour_filter(tour):
            skipped_tour += 1
            continue

        features = builder.build_features(p1, p2, tourney_date, surface)
        if features is None:
            continue

        try:
            x = np.array([[features.get(col, 0) for col in ALL_FEATURES]])
        except Exception:
            continue

        raw_prob = model.predict(x)[0]
        n_form = min(10, len(builder._player_history(p1)))
        has_h2h = features.get("h2h_total", 0) > 0
        our_prob = calibrate_probability(raw_prob, profile, n_form=n_form, has_h2h=has_h2h)

        # Simulated market (50/50 fair)
        market_p1 = 0.5
        odds_p1 = 2.0
        edge = our_prob - market_p1
        ev = compute_ev(our_prob, odds_p1)

        # Filters
        min_edge = profile.get("min_edge_vs_market", 0.02)
        min_ev = profile.get("min_ev", 0.03)

        if mode == "strong":
            min_edge = 0.04
            min_ev = 0.05
            if n_form < 5:
                skipped_form += 1
                continue

        if mode in ("guardrails", "strong"):
            # Odds filter (simulated 2.0 always passes 1.50-3.50)
            if not (1.50 <= odds_p1 <= 3.50):
                skipped_odds += 1
                continue
            # EV cap
            if ev > 0.60:
                skipped_ev_cap += 1
                continue

        if edge < min_edge or ev < min_ev:
            skipped_edge += 1
            continue

        signals += 1
        total_ev += ev
        total_edge += edge

        if pair["p1_is_actual_winner"]:
            won += 1
        else:
            lost += 1

        by_tour.setdefault(tour, {"total": 0, "won": 0, "lost": 0})
        by_tour[tour]["total"] += 1
        if pair["p1_is_actual_winner"]:
            by_tour[tour]["won"] += 1
        else:
            by_tour[tour]["lost"] += 1

        by_surface.setdefault(surface, {"total": 0, "won": 0, "lost": 0})
        by_surface[surface]["total"] += 1
        if pair["p1_is_actual_winner"]:
            by_surface[surface]["won"] += 1
        else:
            by_surface[surface]["lost"] += 1

    hr = won / signals if signals > 0 else 0
    avg_ev = total_ev / signals if signals > 0 else 0
    avg_edge = total_edge / signals if signals > 0 else 0
    stake = 0.005
    avg_odds = 2.0
    total_return = won * stake * (avg_odds - 1) - lost * stake
    roi = total_return / (signals * stake) if signals > 0 else 0

    return {
        "signals": signals, "won": won, "lost": lost,
        "hit_rate": hr, "avg_ev": avg_ev, "avg_edge": avg_edge,
        "roi": roi, "by_tour": by_tour, "by_surface": by_surface,
        "skipped_tour": skipped_tour, "skipped_odds": skipped_odds,
        "skipped_ev_cap": skipped_ev_cap, "skipped_edge": skipped_edge,
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
    print(f"  Avg edge:               {m['avg_edge']:.3f}")
    print(f"  Simulated ROI:          {m['roi']:.1%}")
    if m['skipped_tour']:
        print(f"  Skipped (tour):         {m['skipped_tour']}")
    if m['skipped_odds']:
        print(f"  Skipped (odds):         {m['skipped_odds']}")
    if m['skipped_ev_cap']:
        print(f"  Skipped (EV cap):       {m['skipped_ev_cap']}")
    if m['skipped_form']:
        print(f"  Skipped (form <5):      {m['skipped_form']}")
    print(f"  Skipped (edge/EV):      {m['skipped_edge']}")

    if m['by_tour']:
        print(f"\n  By tournament:")
        for tour, s in sorted(m['by_tour'].items(), key=lambda x: -x[1]['total'])[:10]:
            hr = s['won'] / s['total'] if s['total'] > 0 else 0
            print(f"    {tour:30s} {s['total']:5d} signals, HR={hr:.0%}")


def main():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=30)

    rows = conn.execute("""
        SELECT tourney_date, tour, surface, winner_name, loser_name
        FROM backtest_tennis_players
        WHERE tourney_date >= '2023-01-01'
        ORDER BY tourney_date
    """).fetchall()
    log.info(f"Loaded {len(rows)} matches")

    # Both orderings: Fonbet lists players arbitrarily
    # P1 could be winner or loser — this tests real-world bias
    pairs = []
    for row in rows:
        # Ordering 1: winner listed first (P1=winner)
        pairs.append({
            "tourney_date": row[0], "tour": row[1], "surface": row[2] or "hard",
            "player1": row[3], "player2": row[4],
            "p1_is_actual_winner": True,
        })
        # Ordering 2: loser listed first (P1=loser)
        pairs.append({
            "tourney_date": row[0], "tour": row[1], "surface": row[2] or "hard",
            "player1": row[4], "player2": row[3],
            "p1_is_actual_winner": False,
        })
    log.info(f"Testing {len(pairs)} match pairs (both orderings, P1-only evaluation)")

    results = {}
    for mode, label in [
        ("old", "BASELINE (P1-only, no guardrails)"),
        ("guardrails", "GUARDRAILS (P1-only + tour + odds + EV cap)"),
        ("strong", "STRONG (P1-only + edge>=0.04 + form>=5)"),
    ]:
        log.info(f"Running {mode}...")
        results[mode] = simulate(mode, pairs, conn)
        print_metrics(label, results[mode])

    # Comparison table
    print(f"\n{'=' * 60}")
    print(f"  COMPARISON")
    print(f"{'=' * 60}")

    baseline = results["old"]
    for mode in ("guardrails", "strong"):
        m = results[mode]
        delta_hr = m['hit_rate'] - baseline['hit_rate']
        delta_roi = m['roi'] - baseline['roi']
        delta_sig = m['signals'] - baseline['signals']
        print(f"\n  {mode.upper()} vs BASELINE:")
        print(f"    Signals:  {baseline['signals']} -> {m['signals']} ({delta_sig:+d}, {delta_sig/baseline['signals']:+.0%})")
        print(f"    Hit rate: {baseline['hit_rate']:.1%} -> {m['hit_rate']:.1%} ({delta_hr:+.1%})")
        print(f"    ROI:      {baseline['roi']:.1%} -> {m['roi']:.1%} ({delta_roi:+.1%})")
        print(f"    Avg EV:   {baseline['avg_ev']:.3f} -> {m['avg_ev']:.3f}")

    # Verdict
    print(f"\n{'=' * 60}")
    print(f"  RECOMMENDATION")
    print(f"{'=' * 60}")

    best_mode = "old"
    best_roi = baseline['roi']
    for mode in ("guardrails", "strong"):
        m = results[mode]
        if m['roi'] > best_roi and m['signals'] > 100:
            best_roi = m['roi']
            best_mode = mode

    if best_mode == "old":
        print("  Keep P1-only, no additional guardrails needed.")
        print("  The baseline already has the best ROI.")
        print("  RECOMMENDED: Add only tour filter (block Challenger/ITF)")
        print("  to avoid low-quality tournaments in live pipeline.")
    else:
        print(f"  Best mode: {best_mode}")
        print(f"  ROI: {results[best_mode]['roi']:.1%}, Signals: {results[best_mode]['signals']}")

    print(f"\n  Time: {time.time() - t0:.1f}s")
    conn.close()


if __name__ == "__main__":
    main()
