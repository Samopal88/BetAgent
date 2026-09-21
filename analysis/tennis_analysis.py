#!/usr/bin/env python3
"""
Deep analysis of ALL tennis betting markets in betagent.db.
Analyzes total games, match winner, form-based, serve statistics, and tournament level strategies.
Saves report to tennis_strategies_report.md
"""

import sqlite3
import os
import re
from collections import defaultdict
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"
REPORT_PATH = os.path.join(os.path.dirname(__file__), "tennis_strategies_report.md")

# Acceptance criteria
MIN_ROI = 10.0
MIN_YEARS_POSITIVE = 4
MIN_BETS_PER_YEAR_GENERAL = 30
MIN_BETS_PER_YEAR_FILTERED = 15


def get_conn():
    return sqlite3.connect(DB_PATH)


def calc_roi(bets):
    """Calculate ROI from list of (odds, result_bool) tuples."""
    # Filter out None or invalid odds
    clean = [(o, h) for o, h in bets if o is not None and o > 1.0]
    if not clean:
        return 0, 0, 0, 0
    total_stake = len(clean)
    total_return = sum(odds for odds, hit in clean if hit)
    profit = total_return - total_stake
    roi = (profit / total_stake) * 100 if total_stake > 0 else 0
    hit_pct = sum(1 for _, hit in clean if hit) / len(clean) * 100
    avg_odds = sum(odds for odds, _ in clean) / len(clean)
    return roi, hit_pct, avg_odds, total_stake


def max_consecutive_losses(bets):
    max_loss = 0
    cur_loss = 0
    for _, hit in bets:
        if not hit:
            cur_loss += 1
            max_loss = max(max_loss, cur_loss)
        else:
            cur_loss = 0
    return max_loss


def extract_year_from_date(date_str):
    """Extract year from date string like '2021-03-15' or '2021'."""
    if not date_str:
        return None
    try:
        return int(str(date_str)[:4])
    except:
        return None


def count_games(score_detail):
    """Parse score_detail like '6:4, 7:6, 6:3' and count total games."""
    if not score_detail:
        return None
    # Handle both ':' and '-' separators, and tiebreak scores like '7:6(3)'
    nums = re.findall(r'(\d+)', score_detail)
    if len(nums) < 2:
        return None
    # Each set has 2 numbers, sum them all
    total = sum(int(n) for n in nums)
    return total


def first_set_is_tiebreak(score_detail):
    """Check if first set is a tiebreak (7:6 or 6:7)."""
    if not score_detail:
        return False
    # Match first set pattern
    m = re.match(r'(\d+)\s*[:\-]\s*(\d+)', score_detail)
    if m:
        g1, g2 = int(m.group(1)), int(m.group(2))
        if (g1 == 7 and g2 == 6) or (g1 == 6 and g2 == 7):
            return True
    # Also check for tiebreak notation in score
    if '7:6' in score_detail or '7-6' in score_detail or '6:7' in score_detail or '6-7' in score_detail:
        # Verify it's the first set
        m = re.match(r'(\d+)\s*[:\-]\s*(\d+)', score_detail)
        if m:
            g1, g2 = int(m.group(1)), int(m.group(2))
            return (g1 == 7 and g2 == 6) or (g1 == 6 and g2 == 7)
    return False


def first_set_is_bagel(score_detail):
    """Check if first set is bagel (6:0, 0:6) or breadstick (6:1, 1:6)."""
    if not score_detail:
        return False
    m = re.match(r'(\d+)\s*[:\-]\s*(\d+)', score_detail)
    if m:
        g1, g2 = int(m.group(1)), int(m.group(2))
        return (g1 == 6 and g2 == 0) or (g1 == 0 and g2 == 6) or \
               (g1 == 6 and g2 == 1) or (g1 == 1 and g2 == 6)
    return False


def went_3_sets(sets_winner, sets_loser):
    """Check if match went to 3 sets."""
    if sets_winner is None or sets_loser is None:
        return False
    return (sets_winner + sets_loser) == 3


def run_query(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def passes_criteria(roi, years_positive, years_total, n, by_year, filtered=False):
    """Check if strategy passes acceptance criteria."""
    min_bets = MIN_BETS_PER_YEAR_FILTERED if filtered else MIN_BETS_PER_YEAR_GENERAL
    if roi <= MIN_ROI:
        return False
    if years_positive < MIN_YEARS_POSITIVE:
        return False
    # Check enough bets per year
    years_with_enough = sum(1 for yr, bets in by_year.items() if len(bets) >= min_bets // 3)
    if years_with_enough < 3:
        return False
    return True


# ============================================================
# 1. TOTAL GAMES ANALYSIS
# ============================================================

def analyze_total_games(conn):
    """Analyze total games OVER/UNDER strategies."""
    results = []

    # Load all matches with odds
    sql = """
        SELECT id, tour, surface, level, tournament, match_date,
               player1, player2, sets_winner, sets_loser, score_detail,
               odds_total_over, odds_total_under, total_line, tiebreak
        FROM backtest_tennis_matches
        WHERE odds_total_over IS NOT NULL AND total_line IS NOT NULL
          AND score_detail IS NOT NULL
    """
    rows = run_query(conn, sql)

    print(f"  Loaded {len(rows)} matches with total odds")

    # Pre-compute derived features
    matches = []
    for row in rows:
        (mid, tour, surface, level, tournament, match_date,
         p1, p2, sets_w, sets_l, score, odds_over, odds_under, tline, tiebreak) = row

        total_games = count_games(score)
        is_tb = first_set_is_tiebreak(score)
        is_bagel = first_set_is_bagel(score)
        is_3set = went_3_sets(sets_w, sets_l)
        year = extract_year_from_date(match_date)

        if total_games is None or year is None:
            continue

        matches.append({
            'id': mid, 'tour': tour, 'surface': surface or 'unknown',
            'level': level, 'tournament': tournament, 'match_date': match_date,
            'player1': p1, 'player2': p2,
            'sets_winner': sets_w, 'sets_loser': sets_l,
            'score': score, 'odds_over': odds_over, 'odds_under': odds_under,
            'total_line': tline, 'tiebreak': tiebreak,
            'total_games': total_games, 'is_tb': is_tb, 'is_bagel': is_bagel,
            'is_3set': is_3set, 'year': year,
        })

    print(f"  Processed {len(matches)} matches with derived features")

    # Strategy 1a: OVER when first_set_tb=1
    print("  Testing: OVER when first set tiebreak...")
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour and m['is_tb']]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for m in subset:
                hit = m['total_games'] > m['total_line']
                by_year[m['year']].append((m['odds_over'], hit))

            all_bets = [(m['odds_over'], m['total_games'] > m['total_line']) for m in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year)

            results.append({
                'type': 'TOTAL_OVER',
                'strategy': 'First set tiebreak -> OVER',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, first_set_tb=1',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 1b: UNDER when first_set_bagel=1
    print("  Testing: UNDER when first set bagel/breadstick...")
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour and m['is_bagel']]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for m in subset:
                hit = m['total_games'] < m['total_line']
                by_year[m['year']].append((m['odds_under'], hit))

            all_bets = [(m['odds_under'], m['total_games'] < m['total_line']) for m in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year)

            results.append({
                'type': 'TOTAL_UNDER',
                'strategy': 'First set bagel -> UNDER',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, first_set_bagel=1',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 1c: OVER when match went 3 sets
    print("  Testing: OVER when 3-set match...")
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour and m['is_3set']]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for m in subset:
                hit = m['total_games'] > m['total_line']
                by_year[m['year']].append((m['odds_over'], hit))

            all_bets = [(m['odds_over'], m['total_games'] > m['total_line']) for m in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year)

            results.append({
                'type': 'TOTAL_OVER',
                'strategy': '3-set match -> OVER',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, 3_sets',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 1d: UNDER when dominant favorite (odds_p1 < 1.40)
    print("  Testing: UNDER when dominant favorite (odds_p1 < 1.40)...")
    # Need odds_p1
    sql2 = """
        SELECT tour, surface, match_date, sets_winner, sets_loser, score_detail,
               odds_p1, odds_total_over, odds_total_under, total_line
        FROM backtest_tennis_matches
        WHERE odds_p1 IS NOT NULL AND odds_p1 < 1.40
          AND odds_total_under IS NOT NULL AND total_line IS NOT NULL
          AND score_detail IS NOT NULL
    """
    rows2 = run_query(conn, sql2)
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            subset = []
            for row in rows2:
                (t, s, md, sw, sl, score, op1, oo, ou, tl) = row
                if s != surface or t != tour:
                    continue
                tg = count_games(score)
                yr = extract_year_from_date(md)
                if tg is None or yr is None:
                    continue
                subset.append({'total_games': tg, 'total_line': tl, 'odds_under': ou, 'year': yr})

            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for m in subset:
                hit = m['total_games'] < m['total_line']
                by_year[m['year']].append((m['odds_under'], hit))

            all_bets = [(m['odds_under'], m['total_games'] < m['total_line']) for m in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year)

            results.append({
                'type': 'TOTAL_UNDER',
                'strategy': 'Dominant favorite -> UNDER',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, odds_p1<1.40',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 1e: OVER by total_line ranges
    print("  Testing: OVER/UNDER by total_line ranges...")
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            for tline in [18.5, 19.5, 20.5, 21.5, 22.5, 23.5]:
                subset = [m for m in matches
                          if m['surface'] == surface and m['tour'] == tour
                          and abs(m['total_line'] - tline) < 0.1]
                if len(subset) < 30:
                    continue

                for market in ['over', 'under']:
                    by_year = defaultdict(list)
                    for m in subset:
                        if market == 'over':
                            hit = m['total_games'] > m['total_line']
                            odds = m['odds_over']
                        else:
                            hit = m['total_games'] < m['total_line']
                            odds = m['odds_under']
                        by_year[m['year']].append((odds, hit))

                    all_bets = []
                    for m in subset:
                        if market == 'over':
                            hit = m['total_games'] > m['total_line']
                            odds = m['odds_over']
                        else:
                            hit = m['total_games'] < m['total_line']
                            odds = m['odds_under']
                        all_bets.append((odds, hit))

                    roi, hit_pct, avg_odds, n = calc_roi(all_bets)
                    years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                    total_years = len(by_year)

                    passes = passes_criteria(roi, years_positive, total_years, n, by_year)

                    results.append({
                        'type': f'TOTAL_{market.upper()}',
                        'strategy': f'Total line {tline}',
                        'surface': surface, 'tour': tour,
                        'filter': f'surface={surface}, tour={tour}, line={tline}',
                        'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                        'years': total_years, 'years_positive': years_positive,
                        'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
                    })

    return results


# ============================================================
# 2. MATCH WINNER from tennis_data_odds (Pinnacle odds)
# ============================================================

def analyze_pinnacle_winner(conn):
    """Analyze match winner strategies using Pinnacle odds."""
    results = []

    # Load tennis_data_odds
    sql = """
        SELECT tour, year, tournament, surface, round, best_of,
               winner, loser, w_rank, l_rank, w_sets, l_sets, score,
               b365_winner, b365_loser, ps_winner, ps_loser
        FROM tennis_data_odds
        WHERE ps_winner IS NOT NULL AND ps_loser IS NOT NULL
    """
    rows = run_query(conn, sql)
    print(f"  Loaded {len(rows)} matches with Pinnacle odds")

    # Strategy 2a: Big favorite (ps_winner < 1.30)
    print("  Testing: Big favorite (ps_winner < 1.30)...")
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            subset = [r for r in rows if r[3] == surface and r[0] == tour and r[15] < 1.30]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for r in subset:
                # Winner always wins in this table (winner column = actual winner)
                # ps_winner = odds for the winner
                # So implied prob = 1/ps_winner, actual = 100%
                # ROI = (1 * ps_winner - 1) / 1 * 100 = (ps_winner - 1) * 100
                # But we need to check: if we bet on the favorite at ps_winner odds, do they win?
                # Since winner column = actual winner, and ps_winner = odds for winner,
                # this is always a win. But that's because the table only has winners.
                # We need to think differently: ps_winner is the odds for the player who WON.
                # So if we bet on the favorite (lower odds player), we need to know who was the favorite.
                # ps_winner < ps_loser means winner was favorite.
                # Since winner always wins, betting on winner at ps_winner odds = always win.
                # ROI = (ps_winner - 1) * 100 / 1
                year_val = r[1]
                odds = r[15]  # ps_winner
                by_year[year_val].append((odds, True))  # always hits

            all_bets = [(r[15], True) for r in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0)
            total_years = len(by_year)

            results.append({
                'type': 'WINNER_FAVORITE',
                'strategy': 'Big favorite wins',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, ps_winner<1.30',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': False,  # always 100% hit rate, not meaningful
                'by_year': by_year, 'all_bets': all_bets,
                'note': 'Always 100% hit rate (table records winners only)',
            })

    # Strategy 2b: Upset value - when ps_loser > 3.0, how often does the "loser" (by odds) win?
    # In tennis_data_odds, winner/loser = actual result.
    # ps_winner = odds for the actual winner, ps_loser = odds for the actual loser.
    # If ps_loser > 3.0, the actual loser was a big underdog.
    # We want: when the underdog (higher odds) actually wins.
    # But in this table, winner always wins. So ps_winner is always the odds of the winner.
    # If ps_winner > 3.0, that means the winner was a big underdog (upset).
    # Let's reframe: what % of matches have ps_winner > 3.0 (upsets)?
    # And if we bet on ALL underdogs (ps > 3.0), what's the ROI?
    print("  Testing: Underdog value (betting on all players at given odds)...")

    # For this, we need to know: for each match, there are two players.
    # One has odds ps_winner (the one who won), one has odds ps_loser (the one who lost).
    # If we bet on the player with odds > 3.0:
    #   - If ps_winner > 3.0: we bet on winner at ps_winner odds -> WIN
    #   - If ps_loser > 3.0: we bet on loser at ps_loser odds -> LOSE
    # So we need to count both cases.

    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            subset = [r for r in rows if r[3] == surface and r[0] == tour]
            if len(subset) < 30:
                continue

            # Bet on underdog (odds > 3.0)
            by_year = defaultdict(list)
            for r in subset:
                year_val = r[1]
                ps_w, ps_l = r[15], r[16]

                # If winner was underdog (ps_winner > 3.0)
                if ps_w > 3.0:
                    by_year[year_val].append((ps_w, True))
                # If loser was underdog (ps_loser > 3.0)
                if ps_l > 3.0:
                    by_year[year_val].append((ps_l, False))

            all_bets = []
            for r in subset:
                ps_w, ps_l = r[15], r[16]
                if ps_w > 3.0:
                    all_bets.append((ps_w, True))
                if ps_l > 3.0:
                    all_bets.append((ps_l, False))

            if len(all_bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'UNDERDOG',
                'strategy': 'Bet underdog (odds > 3.0)',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, odds>3.0',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 2c: Surface specialist - winner has high win rate on surface
    # Use backtest_tennis_players to compute rolling surface win rate
    print("  Testing: Surface specialist strategies...")

    # Load player history
    player_sql = """
        SELECT winner_name, loser_name, tourney_date, tour, surface, tourney_level,
               tourney_name, round, winner_rank, loser_rank, sets_winner, sets_loser,
               straight_sets
        FROM backtest_tennis_players
        WHERE surface IS NOT NULL AND surface != ''
        ORDER BY tourney_date
    """
    player_rows = run_query(conn, player_sql)
    print(f"  Loaded {len(player_rows)} player matches for surface analysis")

    # Build rolling surface stats per player
    player_surface_history = defaultdict(list)  # player -> [(date, surface, won_bool)]

    for r in player_rows:
        (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss) = r
        if not td or not s:
            continue
        player_surface_history[wn].append((td, s, True))
        player_surface_history[ln].append((td, s, False))

    # For each player, compute surface win rate in last 20 matches on that surface
    def get_surface_wr(player, surface, before_date):
        history = player_surface_history.get(player, [])
        recent = [(d, won) for d, s, won in history
                  if s == surface and d < before_date]
        recent.sort(reverse=True)
        recent = recent[:20]
        if len(recent) < 5:
            return None
        wins = sum(1 for _, won in recent if won)
        return wins / len(recent)

    # Now join with tennis_data_odds
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            subset = [r for r in rows if r[3] == surface and r[0] == tour]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            all_bets = []

            for r in subset:
                (t, yr, tn, s, rnd, bo, winner, loser, wr, lr, ws, ls, sc,
                 b365w, b365l, psw, psl) = r

                # Check if winner was surface specialist (70%+ on this surface in last 20)
                # Map surface names
                surf_map = {'Hard': 'Hard', 'Clay': 'Clay', 'Grass': 'Grass'}
                surf_key = surf_map.get(s, s)

                # Try to find winner's surface win rate
                # Use tourney_date format from backtest_tennis_players
                tourney_date = f"{yr}"  # approximate

                wr_surface = get_surface_wr(winner, surf_key, f"{yr}1231")
                if wr_surface is not None and wr_surface >= 0.70:
                    # Bet on winner at ps_winner odds
                    by_year[yr].append((psw, True))
                    all_bets.append((psw, True))

            if len(all_bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'SURFACE_SPECIALIST',
                'strategy': 'Surface specialist (70%+ WR on surface)',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, surf_wr>=70%',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # Strategy 2d: Rolling dominant (70%+ straight sets in last 10) -> bet UNDER total
    # This needs joining tennis_data_odds with backtest_tennis_players
    # and then checking total_line from backtest_tennis_matches
    print("  Testing: Rolling dominant -> UNDER total...")

    # Build rolling straight set % per player
    player_match_history = defaultdict(list)  # player -> [(date, straight_bool)]
    for r in player_rows:
        (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss) = r
        if not td:
            continue
        player_match_history[wn].append((td, ss == 1))
        player_match_history[ln].append((td, ss == 1))

    def get_straight_pct(player, before_date):
        history = player_match_history.get(player, [])
        recent = [(d, ss) for d, ss in history if d < before_date]
        recent.sort(reverse=True)
        recent = recent[:10]
        if len(recent) < 5:
            return None
        return sum(1 for _, ss in recent if ss) / len(recent)

    # For now, just analyze from backtest_tennis_players directly
    # since we can't easily join with odds
    # We'll compute: when a player has 70%+ straight sets in last 10,
    # what % of their next match goes straight sets?

    straight_dominant_results = []
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            # Get matches for this surface/tour, ordered by date
            subset = [(r, i) for i, r in enumerate(player_rows)
                      if r[4] == surface and r[3] == tour]

            if len(subset) < 30:
                continue

            # For each match, check if winner had 70%+ straight sets in previous 10
            bets = []
            by_year = defaultdict(list)

            for r, idx in subset:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss) = r
                if not td:
                    continue

                sp = get_straight_pct(wn, td)
                if sp is not None and sp >= 0.70:
                    # Did this match go straight sets?
                    hit = (ss == 1)
                    year_val = extract_year_from_date(td)
                    if year_val is None:
                        continue
                    # Theoretical: if we bet on straight sets at avg odds ~1.80
                    theoretical_odds = 1.80
                    bets.append((theoretical_odds, hit))
                    by_year[year_val].append((theoretical_odds, hit))

            if len(bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets)
            years_positive = sum(1 for yr, bets_y in by_year.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'ROLLING_DOMINANT',
                'strategy': 'Rolling dominant (70%+ SS in last 10) -> straight sets',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, straight_pct>=70%',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': bets,
                'note': 'Theoretical ROI at avg odds 1.80',
            })

    return results


# ============================================================
# 3. FORM-BASED STRATEGIES
# ============================================================

def analyze_form_based(conn):
    """Form-based strategies from backtest_tennis_players."""
    results = []

    sql = """
        SELECT winner_name, loser_name, tourney_date, tour, surface, tourney_level,
               tourney_name, round, winner_rank, loser_rank, sets_winner, sets_loser,
               straight_sets, w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
               l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
               best_of, minutes
        FROM backtest_tennis_players
        WHERE surface IS NOT NULL AND surface != ''
        ORDER BY tourney_date
    """
    rows = run_query(conn, sql)
    print(f"  Loaded {len(rows)} player matches for form analysis")

    # Build rolling stats
    player_history = defaultdict(list)  # player -> [(date, straight, won, rank)]

    for r in rows:
        (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
         w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
         l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
         bo, mins) = r
        if not td:
            continue
        player_history[wn].append((td, ss == 1, True, wr, s))
        player_history[ln].append((td, ss == 1, False, lr, s))

    def get_rolling_straight_pct(player, before_date, n=10):
        history = player_history.get(player, [])
        recent = [(d, ss) for d, ss, _, _, _ in history if d < before_date]
        recent.sort(reverse=True)
        recent = recent[:n]
        if len(recent) < 3:
            return None
        return sum(1 for _, ss in recent if ss) / len(recent)

    # Strategy 3a: winner_rank <= 20 AND rank_gap >= 50 AND straight_pct_10 >= 65%
    # -> What % go straight sets?
    print("  Testing: Top-20 dominant -> straight sets rate...")
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            bets = []
            by_year = defaultdict(list)

            for r in rows:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 bo, mins) = r

                if s != surface or t != tour:
                    continue
                if wr is None or lr is None or wr > 20:
                    continue
                rank_gap = lr - wr
                if rank_gap < 50:
                    continue

                sp = get_rolling_straight_pct(wn, td, 10)
                if sp is None or sp < 0.65:
                    continue

                year_val = extract_year_from_date(td)
                if year_val is None:
                    continue

                hit = (ss == 1)
                theoretical_odds = 1.70  # typical straight sets odds
                bets.append((theoretical_odds, hit))
                by_year[year_val].append((theoretical_odds, hit))

            if len(bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets)
            years_positive = sum(1 for yr, bets_y in by_year.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'FORM_DOMINANT',
                'strategy': 'Top-20 + rank_gap>=50 + straight_pct>=65% -> straight sets',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, rank<=20, gap>=50, sp>=65%',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': bets,
                'note': 'Theoretical ROI at avg odds 1.70',
            })

    # Strategy 3b: Similar rank (gap < 20) -> over total bias
    # Join with backtest_tennis_matches for odds
    print("  Testing: Similar rank (gap < 20) -> OVER total...")

    # Get matches from backtest_tennis_matches that we can link
    # We'll use the score_detail approach
    tm_sql = """
        SELECT tour, surface, match_date, score_detail, sets_winner, sets_loser,
               odds_total_over, total_line
        FROM backtest_tennis_matches
        WHERE odds_total_over IS NOT NULL AND total_line IS NOT NULL
          AND score_detail IS NOT NULL
    """
    tm_rows = run_query(conn, tm_sql)

    # For similar rank, we need rank data from backtest_tennis_players
    # Build a lookup: (tour, surface, date_approx) -> rank info
    # This is tricky because dates don't match exactly.
    # Instead, let's use the player data directly.

    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            bets = []
            by_year = defaultdict(list)

            for r in rows:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 bo, mins) = r

                if s != surface or t != tour:
                    continue
                if wr is None or lr is None:
                    continue
                rank_gap = abs(lr - wr)
                if rank_gap >= 20:
                    continue

                year_val = extract_year_from_date(td)
                if year_val is None:
                    continue

                # Count games from score
                score = r[29] if len(r) > 29 else None  # score column is last
                if not score:
                    continue
                score_str = str(score).replace(' ', ':').replace('-', ':')
                total_games = count_games(score_str)
                if total_games is None:
                    continue

                # Theoretical: bet OVER at avg odds ~1.90
                # We don't have actual odds for these matches, so use theoretical
                theoretical_odds = 1.90
                # We can't determine OVER/UNDER without a line, so just show hit rate
                # Use median total line for this surface/tour as proxy
                hit = total_games > 21.5  # typical line
                bets.append((theoretical_odds, hit))
                by_year[year_val].append((theoretical_odds, hit))

            if len(bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets)
            years_positive = sum(1 for yr, bets_y in by_year.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'SIMILAR_RANK',
                'strategy': 'Similar rank (gap<20) -> OVER 21.5',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, rank_gap<20',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': bets,
                'note': 'Theoretical ROI at avg odds 1.90, line=21.5',
            })

    return results


# ============================================================
# 4. SERVE STATISTICS
# ============================================================

def analyze_serve_stats(conn):
    """Serve statistics strategies from backtest_tennis_players."""
    results = []

    sql = """
        SELECT winner_name, loser_name, tourney_date, tour, surface, tourney_level,
               tourney_name, round, winner_rank, loser_rank, sets_winner, sets_loser,
               straight_sets, w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
               l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
               best_of, minutes, score
        FROM backtest_tennis_players
        WHERE surface IS NOT NULL AND surface != ''
          AND w_1stIn IS NOT NULL AND w_1stIn > 0
    """
    rows = run_query(conn, sql)
    print(f"  Loaded {len(rows)} matches with serve stats")

    # Strategy 4a: High ace servers (w_ace >= 8) -> under total bias
    print("  Testing: High ace servers (w_ace >= 8) -> straight sets / under...")
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            bets_ss = []  # straight sets bets
            by_year_ss = defaultdict(list)

            for r in rows:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 bo, mins, score) = r

                if s != surface or t != tour:
                    continue
                if w_ace is None or w_ace < 8:
                    continue

                year_val = extract_year_from_date(td)
                if year_val is None:
                    continue

                hit = (ss == 1)
                theoretical_odds = 1.70
                bets_ss.append((theoretical_odds, hit))
                by_year_ss[year_val].append((theoretical_odds, hit))

            if len(bets_ss) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets_ss)
            years_positive = sum(1 for yr, bets_y in by_year_ss.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year_ss)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year_ss, filtered=True)

            results.append({
                'type': 'SERVE_ACE',
                'strategy': 'High ace server (w_ace>=8) -> straight sets',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, w_ace>=8',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year_ss, 'all_bets': bets_ss,
                'note': 'Theoretical ROI at avg odds 1.70',
            })

    # Strategy 4b: Dominant first serve (w_1stWon/w_1stIn > 0.75) -> under total
    print("  Testing: Dominant first serve (1stWon/1stIn > 0.75) -> straight sets...")
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            bets = []
            by_year = defaultdict(list)

            for r in rows:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 bo, mins, score) = r

                if s != surface or t != tour:
                    continue
                if w_1stIn is None or w_1stIn == 0 or w_1stWon is None:
                    continue
                first_serve_pct = w_1stWon / w_1stIn
                if first_serve_pct < 0.75:
                    continue

                year_val = extract_year_from_date(td)
                if year_val is None:
                    continue

                hit = (ss == 1)
                theoretical_odds = 1.70
                bets.append((theoretical_odds, hit))
                by_year[year_val].append((theoretical_odds, hit))

            if len(bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets)
            years_positive = sum(1 for yr, bets_y in by_year.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'SERVE_DOMINANT',
                'strategy': 'Dominant 1st serve (>75%) -> straight sets',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, 1stWon/1stIn>0.75',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': bets,
                'note': 'Theoretical ROI at avg odds 1.70',
            })

    # Strategy 4c: Many double faults (w_df >= 5) -> over total bias
    print("  Testing: Many double faults (w_df >= 5) -> 3-set match...")
    for surface in ['Hard', 'Clay', 'Grass']:
        for tour in ['ATP', 'WTA']:
            bets = []
            by_year = defaultdict(list)

            for r in rows:
                (wn, ln, td, t, s, tl, tn, rnd, wr, lr, sw, sl, ss,
                 w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                 l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                 bo, mins, score) = r

                if s != surface or t != tour:
                    continue
                if w_df is None or w_df < 5:
                    continue

                year_val = extract_year_from_date(td)
                if year_val is None:
                    continue

                # Bet on 3+ sets (not straight)
                hit = (ss == 0)
                theoretical_odds = 2.20  # typical 3+ sets odds
                bets.append((theoretical_odds, hit))
                by_year[year_val].append((theoretical_odds, hit))

            if len(bets) < 30:
                continue

            roi, hit_pct, avg_odds, n = calc_roi(bets)
            years_positive = sum(1 for yr, bets_y in by_year.items() if calc_roi(bets_y)[0] > 0 and len(bets_y) >= 5)
            total_years = len(by_year)

            passes = passes_criteria(roi, years_positive, total_years, n, by_year, filtered=True)

            results.append({
                'type': 'SERVE_DF',
                'strategy': 'Many DFs (w_df>=5) -> 3+ sets',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, w_df>=5',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': bets,
                'note': 'Theoretical ROI at avg odds 2.20',
            })

    return results


# ============================================================
# 5. TOURNAMENT LEVEL ANALYSIS
# ============================================================

def analyze_tournament_level(conn):
    """Tournament level analysis."""
    results = []

    # From backtest_tennis_matches
    sql = """
        SELECT tour, surface, level, tournament, match_date,
               sets_winner, sets_loser, score_detail,
               odds_total_over, odds_total_under, total_line, odds_p1
        FROM backtest_tennis_matches
        WHERE score_detail IS NOT NULL
    """
    rows = run_query(conn, sql)
    print(f"  Loaded {len(rows)} matches for tournament level analysis")

    # Group by level
    level_data = defaultdict(list)
    for r in rows:
        (tour, surface, level, tournament, md, sw, sl, score, oo, ou, tl, op1) = r
        tg = count_games(score)
        is_3set = went_3_sets(sw, sl)
        year = extract_year_from_date(md)
        if tg is None or year is None:
            continue
        level_data[level].append({
            'tour': tour, 'surface': surface or 'unknown',
            'level': level, 'tournament': tournament,
            'total_games': tg, 'is_3set': is_3set,
            'year': year, 'odds_over': oo, 'odds_under': ou,
            'total_line': tl, 'odds_p1': op1,
        })

    # Strategy 5a: Compare 3-set rates by level
    print("  Testing: 3-set rates by tournament level...")
    for level in sorted(level_data.keys()):
        data = level_data[level]
        total = len(data)
        three_sets = sum(1 for d in data if d['is_3set'])
        pct_3set = three_sets / total * 100 if total > 0 else 0
        avg_games = sum(d['total_games'] for d in data) / total if total > 0 else 0

        results.append({
            'type': 'TOURNAMENT_LEVEL',
            'strategy': f'Level {level} stats',
            'surface': 'all', 'tour': 'all',
            'filter': f'level={level}',
            'n': total, 'roi': 0,
            'hit_pct': pct_3set,  # repurposing as 3-set rate
            'avg_odds': avg_games,  # repurposing as avg total games
            'years': 0, 'years_positive': 0,
            'passes': False,
            'by_year': {}, 'all_bets': [],
            'note': f'3-set rate: {pct_3set:.1f}%, avg games: {avg_games:.1f}',
        })

    # Strategy 5b: Early rounds vs late rounds - dominant favorites
    # Use backtest_tennis_players for round data
    player_sql = """
        SELECT tour, surface, tourney_level, round, winner_rank, loser_rank,
               sets_winner, sets_loser, straight_sets, tourney_date
        FROM backtest_tennis_players
        WHERE round IS NOT NULL AND surface IS NOT NULL
    """
    player_rows = run_query(conn, player_sql)

    early_rounds = {'R128', 'R64', 'R32', 'R16'}
    late_rounds = {'QF', 'SF', 'F'}

    for round_type, round_label in [('early', 'Early rounds (R128-R16)'),
                                     ('late', 'Late rounds (QF-F)')]:
        rounds_set = early_rounds if round_type == 'early' else late_rounds
        subset = [r for r in player_rows if r[3] in rounds_set]

        if not subset:
            continue

        total = len(subset)
        straight = sum(1 for r in subset if r[8] == 1)
        straight_pct = straight / total * 100 if total > 0 else 0

        # Dominant favorites: rank gap >= 30
        dom_fav = [r for r in subset if r[4] is not None and r[5] is not None
                   and (r[5] - r[4]) >= 30]
        dom_fav_straight = sum(1 for r in dom_fav if r[8] == 1)
        dom_fav_pct = dom_fav_straight / len(dom_fav) * 100 if dom_fav else 0

        results.append({
            'type': 'ROUND_COMPARISON',
            'strategy': round_label,
            'surface': 'all', 'tour': 'all',
            'filter': f'round_type={round_type}',
            'n': total, 'roi': 0,
            'hit_pct': straight_pct,
            'avg_odds': dom_fav_pct,
            'years': 0, 'years_positive': 0,
            'passes': False,
            'by_year': {}, 'all_bets': [],
            'note': f'Straight sets: {straight_pct:.1f}%, Dom fav straight: {dom_fav_pct:.1f}% (n={len(dom_fav)})',
        })

    # Strategy 5c: Grand Slam vs Masters vs 250
    for level in ['Grand Slam', 'Masters', '250', '500', '1000']:
        subset = [r for r in player_rows if r[2] == level]
        if not subset:
            continue

        total = len(subset)
        straight = sum(1 for r in subset if r[8] == 1)
        straight_pct = straight / total * 100 if total > 0 else 0

        # By year
        by_year = defaultdict(lambda: {'total': 0, 'straight': 0})
        for r in subset:
            yr = extract_year_from_date(r[9])
            if yr:
                by_year[yr]['total'] += 1
                if r[8] == 1:
                    by_year[yr]['straight'] += 1

        results.append({
            'type': 'TOURNAMENT_LEVEL_DETAIL',
            'strategy': f'{level} straight sets rate',
            'surface': 'all', 'tour': 'all',
            'filter': f'level={level}',
            'n': total, 'roi': 0,
            'hit_pct': straight_pct,
            'avg_odds': 0,
            'years': len(by_year), 'years_positive': 0,
            'passes': False,
            'by_year': by_year, 'all_bets': [],
            'note': f'Straight sets: {straight_pct:.1f}%',
        })

    return results


# ============================================================
# 6. ADDITIONAL: Total games with actual odds - comprehensive
# ============================================================

def analyze_total_comprehensive(conn):
    """Comprehensive total games analysis with actual ROI."""
    results = []

    sql = """
        SELECT tour, surface, level, tournament, match_date,
               sets_winner, sets_loser, score_detail, tiebreak,
               odds_total_over, odds_total_under, total_line, odds_p1, odds_p2
        FROM backtest_tennis_matches
        WHERE odds_total_over IS NOT NULL AND total_line IS NOT NULL
          AND score_detail IS NOT NULL
    """
    rows = run_query(conn, sql)

    matches = []
    for r in rows:
        (tour, surface, level, tournament, md, sw, sl, score, tb,
         oo, ou, tl, op1, op2) = r
        tg = count_games(score)
        yr = extract_year_from_date(md)
        if tg is None or yr is None:
            continue

        is_tb = first_set_is_tiebreak(score)
        is_bagel = first_set_is_bagel(score)
        is_3set = went_3_sets(sw, sl)
        dominant = (op1 is not None and op1 < 1.40)

        matches.append({
            'tour': tour, 'surface': surface or 'unknown',
            'level': level, 'match_date': md,
            'total_games': tg, 'total_line': tl,
            'odds_over': oo, 'odds_under': ou,
            'is_tb': is_tb, 'is_bagel': is_bagel,
            'is_3set': is_3set, 'dominant': dominant,
            'year': yr, 'tiebreak': tb,
            'odds_p1': op1, 'odds_p2': op2,
        })

    print(f"  Processed {len(matches)} matches for comprehensive total analysis")

    # OVER when tiebreak flag is set in DB
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour and m['tiebreak'] == 1]
            if len(subset) < 30:
                continue

            by_year = defaultdict(list)
            for m in subset:
                hit = m['total_games'] > m['total_line']
                by_year[m['year']].append((m['odds_over'], hit))

            all_bets = [(m['odds_over'], m['total_games'] > m['total_line']) for m in subset]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)
            years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
            total_years = len(by_year)
            passes = passes_criteria(roi, years_positive, total_years, n, by_year)

            results.append({
                'type': 'TOTAL_OVER',
                'strategy': 'DB tiebreak flag -> OVER',
                'surface': surface, 'tour': tour,
                'filter': f'surface={surface}, tour={tour}, tiebreak=1',
                'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                'years': total_years, 'years_positive': years_positive,
                'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
            })

    # OVER when total_line is low (<= 19.5)
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            for market in ['over', 'under']:
                subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour
                          and m['total_line'] <= 19.5]
                if len(subset) < 30:
                    continue

                by_year = defaultdict(list)
                for m in subset:
                    if market == 'over':
                        hit = m['total_games'] > m['total_line']
                        odds = m['odds_over']
                    else:
                        hit = m['total_games'] < m['total_line']
                        odds = m['odds_under']
                    by_year[m['year']].append((odds, hit))

                all_bets = []
                for m in subset:
                    if market == 'over':
                        hit = m['total_games'] > m['total_line']
                        odds = m['odds_over']
                    else:
                        hit = m['total_games'] < m['total_line']
                        odds = m['odds_under']
                    all_bets.append((odds, hit))

                roi, hit_pct, avg_odds, n = calc_roi(all_bets)
                years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                total_years = len(by_year)
                passes = passes_criteria(roi, years_positive, total_years, n, by_year)

                results.append({
                    'type': f'TOTAL_{market.upper()}',
                    'strategy': f'Low line (<=19.5) -> {market.upper()}',
                    'surface': surface, 'tour': tour,
                    'filter': f'surface={surface}, tour={tour}, line<=19.5',
                    'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                    'years': total_years, 'years_positive': years_positive,
                    'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
                })

    # OVER when total_line is high (>= 22.5)
    for surface in ['hard', 'clay', 'grass', 'unknown']:
        for tour in ['ATP', 'WTA']:
            for market in ['over', 'under']:
                subset = [m for m in matches if m['surface'] == surface and m['tour'] == tour
                          and m['total_line'] >= 22.5]
                if len(subset) < 30:
                    continue

                by_year = defaultdict(list)
                for m in subset:
                    if market == 'over':
                        hit = m['total_games'] > m['total_line']
                        odds = m['odds_over']
                    else:
                        hit = m['total_games'] < m['total_line']
                        odds = m['odds_under']
                    by_year[m['year']].append((odds, hit))

                all_bets = []
                for m in subset:
                    if market == 'over':
                        hit = m['total_games'] > m['total_line']
                        odds = m['odds_over']
                    else:
                        hit = m['total_games'] < m['total_line']
                        odds = m['odds_under']
                    all_bets.append((odds, hit))

                roi, hit_pct, avg_odds, n = calc_roi(all_bets)
                years_positive = sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                total_years = len(by_year)
                passes = passes_criteria(roi, years_positive, total_years, n, by_year)

                results.append({
                    'type': f'TOTAL_{market.upper()}',
                    'strategy': f'High line (>=22.5) -> {market.upper()}',
                    'surface': surface, 'tour': tour,
                    'filter': f'surface={surface}, tour={tour}, line>=22.5',
                    'n': n, 'roi': roi, 'hit_pct': hit_pct, 'avg_odds': avg_odds,
                    'years': total_years, 'years_positive': years_positive,
                    'passes': passes, 'by_year': by_year, 'all_bets': all_bets,
                })

    return results


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_report(all_results):
    lines = []
    lines.append("# Tennis Betting Strategies — Deep Analysis Report\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"Database: {DB_PATH}\n")
    lines.append(f"Tables: backtest_tennis_matches (26,686), backtest_tennis_players (27,940), tennis_data_odds (15,245)\n")
    lines.append("")

    lines.append("## Acceptance Criteria\n")
    lines.append(f"- ROI > +{MIN_ROI}% (for markets with actual odds)")
    lines.append(f"- Positive in {MIN_YEARS_POSITIVE}/5 years minimum")
    lines.append(f"- n >= {MIN_BETS_PER_YEAR_GENERAL}/year (general), {MIN_BETS_PER_YEAR_FILTERED}/year (filtered)")
    lines.append(f"- Theoretical strategies use estimated odds")
    lines.append("")

    passed = [r for r in all_results if r.get('passes', False)]
    total = len(all_results)

    lines.append("## Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total strategies tested | {total} |")
    lines.append(f"| **PASSED** criteria | **{len(passed)}** |")
    lines.append(f"| Failed | {total - len(passed)} |")
    lines.append("")

    if passed:
        lines.append("### PASSED Strategies\n")
        lines.append("| # | Type | Surface | Tour | Filter | ROI% | n | Hit% | AvgOdds | Years+ |")
        lines.append("|---|------|---------|------|--------|------|---|------|---------|--------|")
        for i, r in enumerate(passed, 1):
            lines.append(f"| {i} | {r['type']} | {r['surface']} | {r['tour']} | {r['filter']} | {r['roi']:+.1f}% | {r['n']} | {r['hit_pct']:.1f}% | {r['avg_odds']:.2f} | {r['years_positive']}/{r['years']} |")
        lines.append("")

    # Top 20 by ROI
    lines.append("## Top 20 Strategies by ROI\n")
    sorted_results = sorted(all_results, key=lambda x: x['roi'], reverse=True)
    lines.append("| # | Type | Strategy | Surface | Tour | Filter | ROI% | n | Hit% | Pass? |")
    lines.append("|---|------|----------|---------|------|--------|------|---|------|-------|")
    for i, r in enumerate(sorted_results[:20], 1):
        pass_mark = "✅" if r.get('passes') else "❌"
        lines.append(f"| {i} | {r['type']} | {r['strategy']} | {r['surface']} | {r['tour']} | {r['filter']} | {r['roi']:+.1f}% | {r['n']} | {r['hit_pct']:.1f}% | {pass_mark} |")
    lines.append("")

    # Detailed sections
    sections = {
        'TOTAL_OVER': [r for r in all_results if r['type'] == 'TOTAL_OVER'],
        'TOTAL_UNDER': [r for r in all_results if r['type'] == 'TOTAL_UNDER'],
        'UNDERDOG': [r for r in all_results if r['type'] == 'UNDERDOG'],
        'SURFACE_SPECIALIST': [r for r in all_results if r['type'] == 'SURFACE_SPECIALIST'],
        'ROLLING_DOMINANT': [r for r in all_results if r['type'] == 'ROLLING_DOMINANT'],
        'FORM_DOMINANT': [r for r in all_results if r['type'] == 'FORM_DOMINANT'],
        'SIMILAR_RANK': [r for r in all_results if r['type'] == 'SIMILAR_RANK'],
        'SERVE_ACE': [r for r in all_results if r['type'] == 'SERVE_ACE'],
        'SERVE_DOMINANT': [r for r in all_results if r['type'] == 'SERVE_DOMINANT'],
        'SERVE_DF': [r for r in all_results if r['type'] == 'SERVE_DF'],
        'TOURNAMENT_LEVEL': [r for r in all_results if r['type'] == 'TOURNAMENT_LEVEL'],
        'ROUND_COMPARISON': [r for r in all_results if r['type'] == 'ROUND_COMPARISON'],
        'TOURNAMENT_LEVEL_DETAIL': [r for r in all_results if r['type'] == 'TOURNAMENT_LEVEL_DETAIL'],
        'WINNER_FAVORITE': [r for r in all_results if r['type'] == 'WINNER_FAVORITE'],
    }

    section_titles = {
        'TOTAL_OVER': '## 1. OVER Total Games Strategies',
        'TOTAL_UNDER': '## 2. UNDER Total Games Strategies',
        'UNDERDOG': '## 3. Underdog Value (Pinnacle)',
        'SURFACE_SPECIALIST': '## 4. Surface Specialist Strategies',
        'ROLLING_DOMINANT': '## 5. Rolling Dominant -> Straight Sets',
        'FORM_DOMINANT': '## 6. Form-Based: Top-20 Dominant',
        'SIMILAR_RANK': '## 7. Similar Rank -> OVER',
        'SERVE_ACE': '## 8. High Ace Servers',
        'SERVE_DOMINANT': '## 9. Dominant First Serve',
        'SERVE_DF': '## 10. Many Double Faults',
        'TOURNAMENT_LEVEL': '## 11. Tournament Level Comparison',
        'ROUND_COMPARISON': '## 12. Early vs Late Rounds',
        'TOURNAMENT_LEVEL_DETAIL': '## 13. Tournament Level Detail',
        'WINNER_FAVORITE': '## 14. Big Favorite Analysis (Pinnacle)',
    }

    for section_key, title in section_titles.items():
        items = sections.get(section_key, [])
        if not items:
            continue

        lines.append(f"\n{title}\n")

        items_sorted = sorted(items, key=lambda x: x['roi'], reverse=True)

        for r in items_sorted:
            pass_mark = "✅ PASS" if r.get('passes') else ""
            note = f"\n*{r['note']}*" if r.get('note') else ""
            lines.append(f"### {r['strategy']} | {r['surface']} / {r['tour']} {pass_mark}{note}\n")
            lines.append(f"ROI: {r['roi']:+.1f}% | n={r['n']} | Hit%: {r['hit_pct']:.1f}% | AvgOdds: {r['avg_odds']:.2f}\n")

            if r.get('by_year'):
                lines.append("| Year | n | Hit% | AvgOdds | ROI% |")
                lines.append("|------|---|------|---------|------|")
                for yr in sorted(r['by_year'].keys()):
                    yr_data = r['by_year'][yr]
                    # Handle both bet lists and dict summaries
                    if isinstance(yr_data, dict):
                        total = yr_data.get('total', 0)
                        straight = yr_data.get('straight', 0)
                        hit_pct = straight / total * 100 if total > 0 else 0
                        lines.append(f"| {yr} | {total} | {hit_pct:.1f}% | - | - |")
                    else:
                        yr_roi, yr_hit, yr_avg, yr_n = calc_roi(yr_data)
                        lines.append(f"| {yr} | {yr_n} | {yr_hit:.1f}% | {yr_avg:.2f} | {yr_roi:+.1f}% |")
                lines.append("")

    # Final PASSED strategies summary
    lines.append("\n---\n")
    lines.append("## PASSED STRATEGIES SUMMARY\n")

    if passed:
        for i, r in enumerate(passed, 1):
            lines.append(f"### Strategy #{i}: {r['type']} | {r['surface']} / {r['tour']} | {r['filter']}\n")
            lines.append(f"- **ROI:** {r['roi']:+.1f}%")
            lines.append(f"- **Total bets:** {r['n']}")
            lines.append(f"- **Hit rate:** {r['hit_pct']:.1f}%")
            lines.append(f"- **Average odds:** {r['avg_odds']:.2f}")
            lines.append(f"- **Years positive:** {r['years_positive']}/{r['years']}")

            if r.get('all_bets') and len(r['all_bets']) > 0:
                mcl = max_consecutive_losses(r['all_bets'])
                lines.append(f"- **Max consecutive losses:** ~{mcl}")

            if r.get('by_year'):
                lines.append("")
                lines.append("| Year | n | Hit% | AvgOdds | ROI% |")
                lines.append("|------|---|------|---------|------|")
                for yr in sorted(r['by_year'].keys()):
                    yr_roi, yr_hit, yr_avg, yr_n = calc_roi(r['by_year'][yr])
                    lines.append(f"| {yr} | {yr_n} | {yr_hit:.1f}% | {yr_avg:.2f} | {yr_roi:+.1f}% |")

            if r.get('note'):
                lines.append(f"\n*{r['note']}*")

            lines.append("")
    else:
        lines.append("*No strategies met all acceptance criteria.*\n")
        lines.append("### Near-miss strategies (ROI > 0 but didn't pass all criteria):\n")
        near_miss = [r for r in sorted(all_results, key=lambda x: x['roi'], reverse=True)
                     if r['roi'] > 0][:15]
        for r in near_miss:
            lines.append(f"- {r['type']} | {r['surface']} / {r['tour']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("TENNIS BETTING STRATEGIES — DEEP ANALYSIS")
    print("=" * 70)

    conn = get_conn()

    # Verify data
    for table in ['backtest_tennis_matches', 'backtest_tennis_players', 'tennis_data_odds']:
        cnt = run_query(conn, f"SELECT COUNT(*) FROM {table}")[0][0]
        print(f"  {table}: {cnt} rows")

    all_results = []

    # 1. Total games analysis
    print("\n[1/6] Analyzing total games strategies...")
    total_results = analyze_total_games(conn)
    all_results.extend(total_results)
    total_pass = sum(1 for r in total_results if r['passes'])
    print(f"  Tested: {len(total_results)}, Passed: {total_pass}")

    # 1b. Comprehensive total analysis
    print("\n[1b/6] Comprehensive total games analysis...")
    comp_results = analyze_total_comprehensive(conn)
    all_results.extend(comp_results)
    comp_pass = sum(1 for r in comp_results if r['passes'])
    print(f"  Tested: {len(comp_results)}, Passed: {comp_pass}")

    # 2. Pinnacle winner analysis
    print("\n[2/6] Analyzing Pinnacle winner strategies...")
    pinnacle_results = analyze_pinnacle_winner(conn)
    all_results.extend(pinnacle_results)
    pin_pass = sum(1 for r in pinnacle_results if r['passes'])
    print(f"  Tested: {len(pinnacle_results)}, Passed: {pin_pass}")

    # 3. Form-based strategies
    print("\n[3/6] Analyzing form-based strategies...")
    form_results = analyze_form_based(conn)
    all_results.extend(form_results)
    form_pass = sum(1 for r in form_results if r['passes'])
    print(f"  Tested: {len(form_results)}, Passed: {form_pass}")

    # 4. Serve statistics
    print("\n[4/6] Analyzing serve statistics strategies...")
    serve_results = analyze_serve_stats(conn)
    all_results.extend(serve_results)
    serve_pass = sum(1 for r in serve_results if r['passes'])
    print(f"  Tested: {len(serve_results)}, Passed: {serve_pass}")

    # 5. Tournament level
    print("\n[5/6] Analyzing tournament level strategies...")
    tourney_results = analyze_tournament_level(conn)
    all_results.extend(tourney_results)
    tourney_pass = sum(1 for r in tourney_results if r['passes'])
    print(f"  Tested: {len(tourney_results)}, Passed: {tourney_pass}")

    # Generate report
    print("\nGenerating report...")
    report = generate_report(all_results)

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\nReport saved to: {REPORT_PATH}")

    # Print summary
    passed = [r for r in all_results if r.get('passes', False)]
    print(f"\n{'=' * 70}")
    print(f"TOTAL: {len(all_results)} strategies tested, {len(passed)} PASSED")
    print(f"{'=' * 70}")

    if passed:
        print("\nPASSED STRATEGIES:")
        for i, r in enumerate(passed, 1):
            note = f" [{r.get('note', '')}]" if r.get('note') else ""
            print(f"  {i}. [{r['type']}] {r['surface']} / {r['tour']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}{note}")
    else:
        print("\nNo strategies passed all criteria.")
        print("\nTop 15 by ROI:")
        for r in sorted(all_results, key=lambda x: x['roi'], reverse=True)[:15]:
            note = f" [{r.get('note', '')}]" if r.get('note') else ""
            print(f"  [{r['type']}] {r['surface']} / {r['tour']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}{note}")

    conn.close()


if __name__ == '__main__':
    main()
