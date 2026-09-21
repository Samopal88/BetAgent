#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — Tennis Guardrails Backtest Comparison

Compares OLD pipeline (no guardrails, P1-only) vs NEW pipeline
(tour filter, odds 1.50-3.50, EV cap 0.60, P1/P2 evaluation).

Usage:
    python analysis/tennis_guardrails_backtest.py
"""
import logging
import pickle
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(BASE_DIR / "betagent.db")
MODEL_PATH = str(BASE_DIR / "models/tennis_winner_model.pkl")
META_PATH = str(BASE_DIR / "models/tennis_winner_meta.pkl")

sys.path.insert(0, str(BASE_DIR))
from tennis_live_pipeline import (
    ALL_FEATURES, TennisFeatureBuilder, calibrate_probability,
    compute_ev, compute_kelly, TENNIS_PROFILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("guardrails")

# ------------------------------------------------------------------
# Guardrails configuration
# ------------------------------------------------------------------
GUARDRAILS = {
    # Only main tour tournaments
    "allowed_tours": {"ATP", "WTA"},
    # Block these tournament types
    "blocked_keywords": ["Challenger", "челлендж", "ITF", "125K", "квалификац", "qualifying"],
    # Odds range
    "min_odds": 1.50,
    "max_odds": 3.50,
    # EV cap (don't bet on extremely high EV — likely model error)
    "max_ev": 0.60,
}

# ------------------------------------------------------------------
# Load model
# ------------------------------------------------------------------
with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)
with open(META_PATH, "rb") as f:
    meta = pickle.load(f)
log.info(f"Model loaded: {meta.get('model_version')}, {model.num_trees()} trees")


def _passes_tour_filter(league: str) -> bool:
    """Check if league passes tour filter (main tour only)."""
    l = league.lower()
    # Block keywords
    for kw in GUARDRAILS["blocked_keywords"]:
        if kw.lower() in l:
            return False
    # Must be ATP or WTA main tour
    has_tour = "atp" in l or "wta" in l
    return has_tour


def _passes_odds_filter(odds: float) -> bool:
    return GUARDRAILS["min_odds"] <= odds <= GUARDRAILS["max_odds"]


def _passes_ev_filter(ev: float) -> bool:
    return ev <= GUARDRAILS["max_ev"]


def load_historical_matches(conn: sqlite3.Connection) -> list:
    """Load historical tennis matches for backtesting."""
    rows = conn.execute("""
        SELECT tourney_date, tour, surface, winner_name, loser_name,
               winner_rank, loser_rank,
               w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
               l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
               minutes, sets_loser, straight_sets
        FROM backtest_tennis_players
        WHERE tourney_date >= '2023-01-01'
        ORDER BY tourney_date
    """).fetchall()
    log.info(f"Loaded {len(rows)} historical matches from backtest_tennis_players")
    return rows


def build_match_pairs(historical: list) -> list:
    """
    Build hypothetical match pairs from historical data.
    For each match, we know the actual winner and loser.
    We simulate: what would the pipeline have predicted before this match?

    Returns list of dicts with player1=winner, player2=loser (as listed in source).
    """
    pairs = []
    for row in historical:
        (tourney_date, tour, surface, winner, loser,
         w_rank, l_rank,
         w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
         l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
         minutes, sets_loser, straight) = row

        # Simulate both orderings: winner as P1, and loser as P1
        # This lets us test P1/P2 bias
        pairs.append({
            "tourney_date": tourney_date,
            "tour": tour,
            "surface": surface or "hard",
            "player1": winner,
            "player2": loser,
            "actual_winner": winner,
            "p1_is_actual_winner": True,
        })
        pairs.append({
            "tourney_date": tourney_date,
            "tour": tour,
            "surface": surface or "hard",
            "player1": loser,
            "player2": winner,
            "actual_winner": winner,
            "p1_is_actual_winner": False,
        })

    log.info(f"Built {len(pairs)} match pairs (both orderings)")
    return pairs


def simulate_pipeline(pairs: list, conn: sqlite3.Connection, use_guardrails: bool = False, limit: int = None) -> dict:
    """
    Simulate the tennis pipeline on historical match pairs.

    For each pair:
    1. Build features (player1 perspective)
    2. Predict P1 win probability
    3. Derive P2 win probability = 1 - raw_prob
    4. Apply calibration
    5. Calculate edge vs market (simulated 50/50 market)
    6. Apply filters (with or without guardrails)
    7. Track results

    Returns metrics dict.
    """
    builder = TennisFeatureBuilder(conn)
    profile = TENNIS_PROFILE

    total_evaluated = 0
    signals_generated = 0
    signals_won = 0
    signals_lost = 0
    total_ev = 0.0
    total_edge = 0.0
    p1_signals = 0
    p2_signals = 0

    # Per-tournament breakdown
    by_tour = {}
    by_surface = {}

    skipped_no_features = 0
    skipped_no_edge = 0
    skipped_tour = 0
    skipped_odds = 0
    skipped_ev_cap = 0

    test_pairs = pairs[:limit] if limit else pairs

    for i, pair in enumerate(test_pairs):
        p1 = pair["player1"]
        p2 = pair["player2"]
        actual_winner = pair["actual_winner"]
        tourney_date = pair["tourney_date"]
        surface = pair["surface"]
        tour = pair["tour"]

        # Guardrail: tour filter
        if use_guardrails and not _passes_tour_filter(tour):
            skipped_tour += 1
            continue

        # Build features
        features = builder.build_features(p1, p2, tourney_date, surface)
        if features is None:
            skipped_no_features += 1
            continue

        try:
            x = np.array([[features.get(col, 0) for col in ALL_FEATURES]])
        except Exception:
            continue

        # Predict P1 win probability
        raw_prob_p1 = model.predict(x)[0]
        raw_prob_p2 = 1.0 - raw_prob_p1

        # Calibrate both
        n_form = min(10, len(builder._player_history(p1)))
        has_h2h = features.get("h2h_total", 0) > 0
        our_prob_p1 = calibrate_probability(raw_prob_p1, profile, n_form=n_form, has_h2h=has_h2h)
        our_prob_p2 = calibrate_probability(raw_prob_p2, profile, n_form=n_form, has_h2h=has_h2h)

        # Simulated market probability (50/50, no vig)
        market_p1 = 0.5
        market_p2 = 0.5

        # Simulated odds (fair odds from market prob)
        odds_p1 = 1.0 / market_p1  # 2.0
        odds_p2 = 1.0 / market_p2  # 2.0

        # Edge and EV for both sides
        edge_p1 = our_prob_p1 - market_p1
        edge_p2 = our_prob_p2 - market_p2
        ev_p1 = compute_ev(our_prob_p1, odds_p1)
        ev_p2 = compute_ev(our_prob_p2, odds_p2)

        total_evaluated += 1

        # OLD mode: only check P1
        if not use_guardrails:
            min_edge = profile.get("min_edge_vs_market", 0.02)
            min_ev = profile.get("min_ev", 0.03)

            if edge_p1 < min_edge or ev_p1 < min_ev:
                skipped_no_edge += 1
                continue

            # Signal: bet P1
            signals_generated += 1
            p1_signals += 1
            total_ev += ev_p1
            total_edge += edge_p1

            if pair["p1_is_actual_winner"]:
                signals_won += 1
            else:
                signals_lost += 1

            # Track by tour/surface
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

        # NEW mode: check both P1 and P2, apply all guardrails
        else:
            min_edge = profile.get("min_edge_vs_market", 0.02)
            min_ev = profile.get("min_ev", 0.03)

            # Check P1 (standard thresholds)
            p1_passes = (
                edge_p1 >= min_edge and ev_p1 >= min_ev
                and _passes_odds_filter(odds_p1)
                and _passes_ev_filter(ev_p1)
            )

            # Check P2 (stricter — model is trained from P1 perspective,
            # so P2 probability = 1 - raw_prob is less reliable).
            # Only bet P2 when model is strongly confident P1 will lose
            # (raw_prob < 0.40 means model thinks P2 wins > 60%).
            p2_strong = raw_prob_p1 < 0.40
            p2_passes = (
                p2_strong
                and edge_p2 >= min_edge * 1.5  # 50% higher edge threshold
                and ev_p2 >= min_ev * 1.5
                and _passes_odds_filter(odds_p2)
                and _passes_ev_filter(ev_p2)
            )

            if not p1_passes and not p2_passes:
                skipped_no_edge += 1
                continue

            # If both pass, pick the one with higher edge
            if p1_passes and p2_passes:
                if edge_p1 >= edge_p2:
                    pick = "p1"
                    sig_ev = ev_p1
                    sig_edge = edge_p1
                    sig_prob = our_prob_p1
                    won = pair["p1_is_actual_winner"]
                else:
                    pick = "p2"
                    sig_ev = ev_p2
                    sig_edge = edge_p2
                    sig_prob = our_prob_p2
                    won = not pair["p1_is_actual_winner"]
            elif p1_passes:
                pick = "p1"
                sig_ev = ev_p1
                sig_edge = edge_p1
                sig_prob = our_prob_p1
                won = pair["p1_is_actual_winner"]
            else:
                pick = "p2"
                sig_ev = ev_p2
                sig_edge = edge_p2
                sig_prob = our_prob_p2
                won = not pair["p1_is_actual_winner"]

            signals_generated += 1
            if pick == "p1":
                p1_signals += 1
            else:
                p2_signals += 1
            total_ev += sig_ev
            total_edge += sig_edge

            if won:
                signals_won += 1
            else:
                signals_lost += 1

            by_tour.setdefault(tour, {"total": 0, "won": 0, "lost": 0})
            by_tour[tour]["total"] += 1
            if won:
                by_tour[tour]["won"] += 1
            else:
                by_tour[tour]["lost"] += 1

            by_surface.setdefault(surface, {"total": 0, "won": 0, "lost": 0})
            by_surface[surface]["total"] += 1
            if won:
                by_surface[surface]["won"] += 1
            else:
                by_surface[surface]["lost"] += 1

    # Compute metrics
    hit_rate = signals_won / signals_generated if signals_generated > 0 else 0
    avg_ev = total_ev / signals_generated if signals_generated > 0 else 0
    avg_edge = total_edge / signals_generated if signals_generated > 0 else 0

    # ROI simulation (fixed 0.5% stake per signal)
    stake = 0.005
    total_staked = signals_generated * stake
    # For won bets: profit = stake * (odds - 1), for lost: -stake
    # Simplified: avg_odds ~ 2.0 (fair market)
    avg_odds = 2.0
    total_return = signals_won * stake * (avg_odds - 1) - signals_lost * stake
    roi = total_return / total_staked if total_staked > 0 else 0

    return {
        "total_evaluated": total_evaluated,
        "signals_generated": signals_generated,
        "signals_won": signals_won,
        "signals_lost": signals_lost,
        "hit_rate": hit_rate,
        "avg_ev": avg_ev,
        "avg_edge": avg_edge,
        "roi": roi,
        "p1_signals": p1_signals,
        "p2_signals": p2_signals,
        "p1_ratio": p1_signals / signals_generated if signals_generated > 0 else 0,
        "p2_ratio": p2_signals / signals_generated if signals_generated > 0 else 0,
        "by_tour": by_tour,
        "by_surface": by_surface,
        "skipped_no_features": skipped_no_features,
        "skipped_no_edge": skipped_no_edge,
        "skipped_tour": skipped_tour,
        "skipped_odds": skipped_odds,
        "skipped_ev_cap": skipped_ev_cap,
    }


def print_metrics(label: str, m: dict):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Matches evaluated:      {m['total_evaluated']}")
    print(f"  Signals generated:      {m['signals_generated']}")
    print(f"  Signals won:            {m['signals_won']}")
    print(f"  Signals lost:           {m['signals_lost']}")
    print(f"  Hit rate:               {m['hit_rate']:.1%}")
    print(f"  Avg EV:                 {m['avg_ev']:.3f}")
    print(f"  Avg edge:               {m['avg_edge']:.3f}")
    print(f"  Simulated ROI:          {m['roi']:.1%}")
    print(f"  P1 signals:             {m['p1_signals']} ({m['p1_ratio']:.0%})")
    print(f"  P2 signals:             {m['p2_signals']} ({m['p2_ratio']:.0%})")
    print(f"  Skipped (no features):  {m['skipped_no_features']}")
    print(f"  Skipped (no edge/EV):   {m['skipped_no_edge']}")
    if m['skipped_tour']:
        print(f"  Skipped (tour filter):  {m['skipped_tour']}")
    if m['skipped_odds']:
        print(f"  Skipped (odds filter):  {m['skipped_odds']}")
    if m['skipped_ev_cap']:
        print(f"  Skipped (EV cap):       {m['skipped_ev_cap']}")

    if m['by_tour']:
        print(f"\n  By tournament:")
        for tour, stats in sorted(m['by_tour'].items(), key=lambda x: -x[1]['total'])[:15]:
            hr = stats['won'] / stats['total'] if stats['total'] > 0 else 0
            print(f"    {tour:30s} {stats['total']:4d} signals, {stats['won']:3d}W/{stats['lost']:3d}L, HR={hr:.0%}")

    if m['by_surface']:
        print(f"\n  By surface:")
        for surf, stats in sorted(m['by_surface'].items(), key=lambda x: -x[1]['total']):
            hr = stats['won'] / stats['total'] if stats['total'] > 0 else 0
            print(f"    {surf:10s} {stats['total']:4d} signals, {stats['won']:3d}W/{stats['lost']:3d}L, HR={hr:.0%}")


def main():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=30)

    log.info("Loading historical matches...")
    historical = load_historical_matches(conn)
    pairs = build_match_pairs(historical)

    log.info("Running OLD pipeline (no guardrails, P1-only)...")
    old_metrics = simulate_pipeline(pairs, conn, use_guardrails=False)

    log.info("Running NEW pipeline (with guardrails, P1/P2)...")
    new_metrics = simulate_pipeline(pairs, conn, use_guardrails=True)

    print_metrics("OLD PIPELINE (no guardrails, P1-only)", old_metrics)
    print_metrics("NEW PIPELINE (guardrails + P1/P2)", new_metrics)

    # Comparison
    print(f"\n{'=' * 60}")
    print(f"  COMPARISON: OLD vs NEW")
    print(f"{'=' * 60}")

    sig_delta = new_metrics['signals_generated'] - old_metrics['signals_generated']
    hr_delta = new_metrics['hit_rate'] - old_metrics['hit_rate']
    ev_delta = new_metrics['avg_ev'] - old_metrics['avg_ev']
    roi_delta = new_metrics['roi'] - old_metrics['roi']

    print(f"  Signal count change:    {sig_delta:+d} ({sig_delta/old_metrics['signals_generated']:+.0%})")
    print(f"  Hit rate change:        {hr_delta:+.1%} ({old_metrics['hit_rate']:.1%} -> {new_metrics['hit_rate']:.1%})")
    print(f"  Avg EV change:          {ev_delta:+.3f} ({old_metrics['avg_ev']:.3f} -> {new_metrics['avg_ev']:.3f})")
    print(f"  ROI change:             {roi_delta:+.1%} ({old_metrics['roi']:.1%} -> {new_metrics['roi']:.1%})")
    print(f"  P1/P2 ratio:            OLD={old_metrics['p1_ratio']:.0%}/{old_metrics['p2_ratio']:.0%} -> NEW={new_metrics['p1_ratio']:.0%}/{new_metrics['p2_ratio']:.0%}")

    # Stability assessment
    print(f"\n{'=' * 60}")
    print(f"  STABILITY ASSESSMENT")
    print(f"{'=' * 60}")

    issues = []
    positives = []

    if new_metrics['hit_rate'] >= old_metrics['hit_rate']:
        positives.append("Hit rate maintained or improved")
    else:
        issues.append(f"Hit rate dropped by {abs(hr_delta):.1%}")

    if new_metrics['signals_generated'] > 0:
        positives.append(f"Still generating {new_metrics['signals_generated']} signals")
    else:
        issues.append("ZERO signals generated — guardrails too strict")

    if new_metrics['p2_ratio'] > 0.10:
        positives.append(f"P2 signals now {new_metrics['p2_ratio']:.0%} of total (was 0%)")
    else:
        issues.append(f"P2 signals still very low ({new_metrics['p2_ratio']:.0%})")

    if abs(new_metrics['roi']) < 0.50:
        positives.append("ROI within reasonable range")
    else:
        issues.append(f"ROI extreme ({new_metrics['roi']:.1%}) — possible model issue")

    for p in positives:
        print(f"  [+] {p}")
    for i in issues:
        print(f"  [-] {i}")

    verdict = "PASS" if len(positives) >= len(issues) else "FAIL"
    print(f"\n  VERDICT: {verdict} ({len(positives)} positives, {len(issues)} issues)")

    elapsed = time.time() - t0
    print(f"\n  Time: {elapsed:.1f}s")

    conn.close()


if __name__ == "__main__":
    main()
