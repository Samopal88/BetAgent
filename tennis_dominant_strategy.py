#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tennis_dominant_strategy.py

Test a tennis strategy: dominant winner → bet on them winning straight sets.

Join strategy:
  backtest_tennis_players (Jeff Sackmann, English)
  ← tennis_player_mapping (eng_name)
  → betting odds from backtest_tennis_matches via player names

Strategy: when a significantly higher-ranked player has been dominant
in recent matches, bet on them winning in straight sets (sets_loser = 0).

Two filter levels:
  STRICT:  winner_rank <= 20, rank_diff >= 50, dominant_pct >= 60 (last 10)
  RELAXED: winner_rank <= 30, rank_diff >= 30, dominant_pct >= 50
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "betagent.db")
OUTPUT = "/tmp/tennis_dominant_strategy.txt"

conn = sqlite3.connect(DB_PATH, timeout=30)
conn.execute("PRAGMA journal_mode=WAL")

out = []

def w(msg):
    out.append(msg)
    print(msg)


w("=" * 70)
w("TENNIS DOMINANT WINNER STRATEGY — Straight Sets")
w("=" * 70)

# ================================================================
# 1. JOIN coverage
# ================================================================
w("\n--- PART 1: JOIN COVERAGE ---\n")

total_player_names = conn.execute(
    "SELECT COUNT(*) FROM (SELECT DISTINCT LOWER(winner_name) FROM backtest_tennis_players UNION SELECT DISTINCT LOWER(loser_name) FROM backtest_tennis_players)"
).fetchone()[0]

eng_in_mapping = conn.execute(
    "SELECT COUNT(DISTINCT eng_name) FROM tennis_player_mapping WHERE needs_review=0"
).fetchone()[0]

w(f"Total unique player names (Jeff Sackmann):  {total_player_names}")
w(f"Eng names in confident mapping:             {eng_in_mapping}")
w(f"Mapped: {eng_in_mapping}/{total_player_names = } → {eng_in_mapping/total_player_names*100:.1f}%")

# Betz coverage
total_betz_names = conn.execute(
    "SELECT COUNT(DISTINCT n) FROM (SELECT player1 as n FROM backtest_tennis_matches UNION SELECT player2 as n FROM backtest_tennis_matches)"
).fetchone()[0]

lookup_count = conn.execute("SELECT COUNT(*) FROM tennis_name_lookup").fetchone()[0]

matches_both = conn.execute(
    "SELECT COUNT(*) FROM backtest_tennis_matches m "
    "JOIN tennis_name_lookup t1 ON t1.betz_name = m.player1 "
    "JOIN tennis_name_lookup t2 ON t2.betz_name = m.player2"
).fetchone()[0]

total_matches = conn.execute("SELECT COUNT(*) FROM backtest_tennis_matches").fetchone()[0]

w(f"\nTotal betz unique names:        {total_betz_names}")
w(f"Lookup entries (expanded):      {lookup_count}")
w(f"Betz matches BOTH mapped:       {matches_both}/{total_matches} ({matches_both/total_matches*100:.1f}%)")


# ================================================================
# 2. Build form features — for each match, compute rolling dominant_pct
# ================================================================
w("\n--- PART 2: STRATEGY — DOMINANT WINNER → STRAIGHT SETS ---\n")

# We use Jeff Sackmann data: it has winner_name, loser_name, winner_rank,
# sets_winner (2 or 3), best_of (3 or 5)
#
# For each match:
#   if winner_rank is low (<= 20 or 30)
#   and rank_diff >= 50 (winner significantly higher ranked)
#   and dominant_pct in last 10 matches >= 60%
#   → predict straight sets win
#
# Outcome: sets_loser == 0 means actual straight set win

# First, build a ranked history per player to compute rolling dominant_pct
# (dominant_pct = % of recent matches won in straight sets)

# Get ordered matches per player
w("Loading match history for form calculation...")

# Player history: for each winner_name, get previous matches as winner or loser
player_matches = defaultdict(list)  # name -> [(date, match_id, was_winner, sets_winner, sets_loser)]

# From backtest_tennis_players
rows = conn.execute("""
    SELECT tour, tourney_date, winner_name, loser_name,
           winner_rank, loser_rank, sets_winner, sets_loser,
           straight_sets, tourney_name, id
    FROM backtest_tennis_players
    WHERE winner_rank IS NOT NULL AND loser_rank IS NOT NULL
    ORDER BY winner_name, tourney_date
""").fetchall()

# Build per-player match sequences
player_history = defaultdict(list)  # player_lower -> [(date, id, won, sets_won, sets_lost)]

for row in rows:
    tour, date, wname, lname, wrank, lrank, sets_w, sets_l, straight, tname, mid = row
    wn = wname.lower()
    ln = lname.lower()

    # Winner's perspective
    player_history[wn].append((date, mid, True, sets_w, sets_l, wrank, lrank, wn, ln))
    # Loser's perspective
    player_history[ln].append((date, mid, False, sets_w, sets_l, lrank, wrank, ln, wn))

w(f"Total ranked matches loaded: {len(rows)}")
w(f"Players with ranked matches: {len(player_history)}")


def compute_dominant_pct(history, player_lower, match_date, n=10):
    """
    For a player at a given date, compute % of their previous n matches
    won in straight sets.
    """
    prev = [h for h in history.get(player_lower, []) if h[0] < match_date]
    prev.sort(key=lambda x: x[0], reverse=True)
    prev = prev[:n]
    if not prev:
        return None, 0
    straight_wins = sum(1 for h in prev if h[2] and h[4] == 0)
    # Only count matches where player WON (straight set only meaningful for wins)
    wins_only = [h for h in prev if h[2]]
    if not wins_only:
        return None, 0
    return straight_wins / len(wins_only) * 100, len(wins_only)


# ================================================================
# Strategy simulation
# ================================================================
from collections import defaultdict as dd

def run_strategy(winner_rank_max, rank_diff_min, dominant_pct_min, label):
    """
    For each match in backtest_tennis_players:
    - Filter: winner_rank <= winner_rank_max
    - Filter: rank_diff = loser_rank - winner_rank >= rank_diff_min
    - Filter: winner's rolling dominant_pct >= dominant_pct_min
    - Bet: straight set win (sets_loser == 0)
    - Record: year, tour, straight/lost
    """
    results = dd(lambda: {'n': 0, 'straight': 0, 'total_loses': 0})

    for row in rows:
        tour, date, wname, lname, wrank, lrank, sets_w, sets_l, straight, tname, mid = row

        # Year from date
        y = date[:4] if date else None
        if not y or len(y) != 4:
            continue

        # Filter 1: winner rank
        wr = int(wrank) if wrank else 999
        lr = int(lrank) if lrank else 0
        if wr > winner_rank_max:
            continue

        # Filter 2: rank difference
        rank_diff = lr - wr
        if rank_diff < rank_diff_min:
            continue

        # Filter 3: dominant pct
        dpct, n_prev = compute_dominant_pct(player_history, wname.lower(), date)
        if dpct is None or dpct < dominant_pct_min:
            continue

        # This qualifies as a bet
        key = (y, tour)
        results[key]['n'] += 1
        if sets_l == 0:
            results[key]['straight'] += 1
        else:
            results[key]['total_loses'] += 1

    return dict(results)


w("\n" + "=" * 70)
w("STRICT FILTER  |  winner_rank <= 20, rank_diff >= 50, dominant_pct >= 60%")
w("=" * 70)

strict = run_strategy(20, 50, 60, "STRICT")

# Sort by year then tour
w(f"\n{'Year':>4} {'Tour':>3} {'N':>5} {'Straight':>9} {'Straight%':>10} {'Lost':>6} {'ROI':>8}")
w("-" * 55)

total_n = 0
total_straight = 0
total_lost = 0
for key in sorted(strict.keys()):
    y, tour = key
    r = strict[key]
    pct = r['straight'] / r['n'] * 100 if r['n'] > 0 else 0
    # ROI: bet on straight sets, approximate odds ~1.50-1.70 (use average straight_pct*1.6 - 1)
    # Simpler: ROI = (win_count * avg_odds - total_bets) / total_bets
    # Without actual odds from Jeff data, we use implied probability from straight_pct
    # If straight% = 70%, fair odds = 1/0.70 = 1.43. Market typically ~1.50-1.60.
    est_odds = max(1.35, 1 / max(0.01, pct / 100) + 0.08)  # conservative +8% vig
    roi = (r['straight'] * est_odds - r['n']) / r['n'] * 100 if r['n'] > 0 else 0

    w(f"{y:>4} {tour:>3} {r['n']:>5} {r['straight']:>9} {pct:>9.1f}% {r['total_loses']:>6} {roi:>+8.1f}%")
    total_n += r['n']
    total_straight += r['straight']
    total_lost += r['total_loses']

if total_n > 0:
    overall_pct = total_straight / total_n * 100
    overall_odds = max(1.35, 1 / max(0.01, overall_pct / 100) + 0.08)
    overall_roi = (total_straight * overall_odds - total_n) / total_n * 100
    w("-" * 55)
    w(f"{'ALL':>4} {'':>3} {total_n:>5} {total_straight:>9} {overall_pct:>9.1f}% {total_lost:>6} {overall_roi:>+8.1f}%")
else:
    w("No bets qualified.")

# RELAXED
w("\n" + "=" * 70)
w("RELAXED FILTER |  winner_rank <= 30, rank_diff >= 30, dominant_pct >= 50%")
w("=" * 70)

relaxed = run_strategy(30, 30, 50, "RELAXED")

total_n_r = 0
total_straight_r = 0
total_lost_r = 0

w(f"\n{'Year':>4} {'Tour':>3} {'N':>5} {'Straight':>9} {'Straight%':>10} {'Lost':>6} {'ROI':>8}")
w("-" * 55)

for key in sorted(relaxed.keys()):
    y, tour = key
    r = relaxed[key]
    pct = r['straight'] / r['n'] * 100 if r['n'] > 0 else 0
    est_odds = max(1.35, 1 / max(0.01, pct / 100) + 0.08)
    roi = (r['straight'] * est_odds - r['n']) / r['n'] * 100 if r['n'] > 0 else 0

    w(f"{y:>4} {tour:>3} {r['n']:>5} {r['straight']:>9} {pct:>9.1f}% {r['total_loses']:>6} {roi:>+8.1f}%")
    total_n_r += r['n']
    total_straight_r += r['straight']
    total_lost_r += r['total_loses']

if total_n_r > 0:
    overall_pct_r = total_straight_r / total_n_r * 100
    overall_odds_r = max(1.35, 1 / max(0.01, overall_pct_r / 100) + 0.08)
    overall_roi_r = (total_straight_r * overall_odds_r - total_n_r) / total_n_r * 100
    w("-" * 55)
    w(f"{'ALL':>4} {'':>3} {total_n_r:>5} {total_straight_r:>9} {overall_pct_r:>9.1f}% {total_lost_r:>6} {overall_roi_r:>+8.1f}%")
else:
    w("No bets qualified.")


# ================================================================
# Save to file
# ================================================================
with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

w(f"\n\nResults saved to {OUTPUT}")

conn.close()
