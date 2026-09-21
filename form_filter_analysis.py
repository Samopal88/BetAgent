#!/usr/bin/env python3
"""
Analyze form filter impact on strategy outcomes.
For each strategy, compute home/away form points from backtest_matches,
segment by form, and show draw_pct / btts_pct / over_pct + ROI per segment per year.
"""

import sqlite3
import json
from collections import defaultdict

DB = "betagent.db"

def form_points(results_str):
    """Calculate points from W/D/L string (3 for W, 1 for D, 0 for L)."""
    pts = 0
    for x in results_str:
        if x == 'W': pts += 3
        elif x == 'D': pts += 1
    return pts

def compute_form_for_team(conn, team_field, league, season_cutoff="2021"):
    """
    Returns dict: match_id -> list of last N results (H or A based on team_field)
    as W/D/L strings, up to 5 games.
    """
    # Get all finished matches sorted by date
    rows = conn.execute(f"""
        SELECT id, home_team, away_team, result, match_date, season
        FROM backtest_matches
        WHERE league = ? AND result IS NOT NULL AND season >= ?
        ORDER BY match_date ASC, id ASC
    """, (league, season_cutoff)).fetchall()

    # Build index: team -> list of (match_date, id, result_for_team)
    team_results = defaultdict(list)
    home_results = defaultdict(list)  # team -> list of results only at home
    away_results = defaultdict(list)  # team -> list of results only at away

    for r in rows:
        mid, ht, at, res, dt, seas = r
        if res in ('H', 'D', 'A'):
            if res == 'H':
                team_results[ht].append(('W', mid, dt))
                team_results[at].append(('L', mid, dt))
                home_results[ht].append(('W', mid, dt))
                away_results[at].append(('L', mid, dt))
            elif res == 'A':
                team_results[ht].append(('L', mid, dt))
                team_results[at].append(('W', mid, dt))
                home_results[ht].append(('L', mid, dt))
                away_results[at].append(('W', mid, dt))
            elif res == 'D':
                team_results[ht].append(('D', mid, dt))
                team_results[at].append(('D', mid, dt))
                home_results[ht].append(('D', mid, dt))
                away_results[at].append(('D', mid, dt))

    return home_results, away_results, team_results


def get_last_n(results_list, match_date, n, exclude_after_id=None):
    """Get last n W/D/L results for a team before a given match_date."""
    results = []
    for result, mid, dt in reversed(results_list):
        if exclude_after_id and mid >= exclude_after_id:
            continue
        if dt < match_date or (dt == match_date and (exclude_after_id is None or mid < exclude_after_id)):
            results.append(result)
        elif dt == match_date and exclude_after_id:
            continue
        else:
            continue
        if len(results) >= n:
            break
    return list(reversed(results))


def get_last_n_before_match(results_list, match_date, match_id, n):
    """Get last n results for a team before (match_date, match_id) from a pre-built results list."""
    results = []
    for result, mid, dt in reversed(results_list):
        if (dt, mid) >= (match_date, match_id):
            continue
        results.append(result)
        if len(results) >= n:
            break
    return list(reversed(results))


def analyze_strategy(draw_func, name):
    """Generic strategy analyzer."""
    print(f"\n{'='*80}")
    print(f"STRATEGY: {name}")
    print(f"{'='*80}")

    results = draw_func()
    if not results:
        print("No matches found.")
        return

    print(f"\nTotal matches matching rule: {len(results)}")

    # Aggregate by year
    year_stats = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'hits': 0, 'total_stake': 0.0, 'total_return': 0.0}))

    for r in results:
        year = r['season']
        segment = r['segment']
        odds = r['odds']
        won = r['won']

        ys = year_stats[year][segment]
        ys['n'] += 1
        if won:
            ys['hits'] += 1
        ys['total_stake'] += 1.0  # assume unit stake
        ys['total_return'] += odds if won else 0.0

    # Print per-segment per-year
    all_segments = set()
    all_years = sorted(year_stats.keys())
    for r in results:
        all_segments.add(r['segment'])
    all_segments = sorted(all_segments)

    print(f"\n{'Year':<7} | {'Segment':<25} | {'N':>5} | {'Hit%':>7} | {'ROI%':>7}")
    print("-" * 60)

    for year in all_years:
        for seg in all_segments:
            if seg not in year_stats[year]:
                continue
            s = year_stats[year][seg]
            pct = s['hits'] / s['n'] * 100 if s['n'] > 0 else 0
            roi = (s['total_return'] / s['total_stake'] - 1) * 100 if s['total_stake'] > 0 else 0
            print(f"{year:<7} | {seg:<25} | {s['n']:>5} | {pct:>6.1f}% | {roi:>6.1f}%")

        # Also print total for the year
        total_n = sum(s['n'] for s in year_stats[year].values())
        total_hits = sum(s['hits'] for s in year_stats[year].values())
        total_stake = sum(s['total_stake'] for s in year_stats[year].values())
        total_return = sum(s['total_return'] for s in year_stats[year].values())
        total_pct = total_hits / total_n * 100 if total_n > 0 else 0
        total_roi = (total_return / total_stake - 1) * 100 if total_stake > 0 else 0

    print("\n--- Overall totals ---")
    total_n = sum(s['n'] for yy in year_stats.values() for s in yy.values())
    total_hits = sum(s['hits'] for yy in year_stats.values() for s in yy.values())
    total_stake = sum(s['total_stake'] for yy in year_stats.values() for s in yy.values())
    total_return = sum(s['total_return'] for yy in year_stats.values() for s in yy.values())
    total_pct = total_hits / total_n * 100 if total_n > 0 else 0
    total_roi = (total_return / total_stake - 1) * 100 if total_stake > 0 else 0
    print(f"Overall: N={total_n}, Hit%={total_pct:.1f}%, ROI={total_roi:.1f}%")


def analyze_draw_sa():
    """DRAW_SA: Serie A draws, odds 3.0-4.5"""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT *, (CASE WHEN result = 'D' THEN 1 ELSE 0 END) as is_draw
        FROM backtest_matches
        WHERE league = 'SA'
          AND odds_draw BETWEEN 3.0 AND 4.5
          AND result IS NOT NULL
          AND season >= '2021'
        ORDER BY match_date ASC, id ASC
    """).fetchall()

    home_results, away_results, team_results = compute_form_for_team(conn, "home_team", "SA", "2021")

    results = []
    for r in rows:
        mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]
        last5_home = get_last_n_before_match(home_results.get(ht, []), dt, mid, 5)
        if not last5_home:
            continue
        h_pts = form_points(last5_home)
        if h_pts <= 5: seg = "home_pts<=5"
        elif h_pts <= 8: seg = "home_pts=6-8"
        elif h_pts <= 12: seg = "home_pts=9-12"
        else: seg = "home_pts>12"

        results.append({
            'season': seas,
            'segment': seg,
            'odds': float(od),
            'won': res == 'D',
            'home_form': ''.join(last5_home),
            'form_pts': h_pts,
        })
    conn.close()
    return results


def analyze_draw_bl1_fl1():
    """DRAW_BL1_FL1: Bundesliga/Ligue1 draws, odds 3.05-3.70"""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT *, (CASE WHEN result = 'D' THEN 1 ELSE 0 END) as is_draw
        FROM backtest_matches
        WHERE league IN ('BL1', 'FL1')
          AND odds_draw BETWEEN 3.05 AND 3.70
          AND result IS NOT NULL
          AND season >= '2021'
        ORDER BY match_date ASC, id ASC
    """).fetchall()

    combined_results = {}
    for lg in ['BL1', 'FL1']:
        h, a, t = compute_form_for_team(conn, "home_team", lg, "2021")
        combined_results[lg] = (h, a, t)

    results = []
    for r in rows:
        mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]
        h, a, t = combined_results.get(lg, (None, None, None))
        if h is None:
            continue
        last5_home = get_last_n_before_match(h.get(ht, []), dt, mid, 5)
        if not last5_home:
            continue
        h_pts = form_points(last5_home)
        if h_pts <= 5: seg = "home_pts<=5"
        elif h_pts <= 8: seg = "home_pts=6-8"
        elif h_pts <= 12: seg = "home_pts=9-12"
        else: seg = "home_pts>12"

        results.append({
            'season': seas,
            'segment': seg,
            'odds': float(od),
            'won': res == 'D',
            'home_form': ''.join(last5_home),
            'form_pts': h_pts,
        })
    conn.close()
    return results


def analyze_pd_btts():
    """PD_BTTS_DOUBLE: La Liga BTTS"""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT * FROM backtest_matches
        WHERE league = 'PD'
          AND odds_btts_yes IS NOT NULL
          AND result IS NOT NULL
          AND season >= '2021'
        ORDER BY match_date ASC, id ASC
    """).fetchall()

    home_results, away_results, team_results = compute_form_for_team(conn, "home_team", "PD", "2021")

    results = []
    for r in rows:
        mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]
        # Check BTTS: both teams scored
        btts = (hs > 0 and asc > 0) if hs is not None and asc is not None else None
        if btts is None:
            continue

        last5_away = get_last_n_before_match(away_results.get(at, []), dt, mid, 5)
        if not last5_away:
            continue
        a_pts = form_points(last5_away)
        if a_pts <= 5: seg = "away_pts<=5"
        elif a_pts <= 9: seg = "away_pts=6-9"
        else: seg = "away_pts>9"

        results.append({
            'season': seas,
            'segment': seg,
            'odds': float(r[19] if len(r) > 19 else 1.9),  # odds_btts_yes
            'won': btts,
            'away_form': ''.join(last5_away),
            'form_pts': a_pts,
        })
    conn.close()
    return results


def analyze_rpl_over25():
    """RPL_OVER25_BTTS: RPL over 2.5"""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT * FROM backtest_matches
        WHERE league = 'RPL'
          AND odds_over_2_5 IS NOT NULL
          AND result IS NOT NULL
          AND season >= '2021'
        ORDER BY match_date ASC, id ASC
    """).fetchall()

    home_results, away_results, team_results = compute_form_for_team(conn, "home_team", "RPL", "2021")

    results = []
    for r in rows:
        mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]
        total = (hs + asc) if hs is not None and asc is not None else None
        if total is None:
            continue
        over25 = total > 2.5

        # Get last 5 home form for home team, last 5 away form for away team
        last5_home = get_last_n_before_match(home_results.get(ht, []), dt, mid, 5)
        last5_away = get_last_n_before_match(away_results.get(at, []), dt, mid, 5)
        if not last5_home or not last5_away:
            continue

        h_pts = form_points(last5_home)
        a_pts = form_points(last5_away)
        combined_pts = h_pts + a_pts

        if combined_pts <= 8: seg = "combined<=8"
        elif combined_pts <= 14: seg = "combined=9-14"
        elif combined_pts <= 20: seg = "combined=15-20"
        else: seg = "combined>20"

        odds = r[19] if len(r) > 19 else None
        if odds is None:
            continue

        results.append({
            'season': seas,
            'segment': seg,
            'odds': float(odds),
            'won': over25,
            'combined_form_pts': combined_pts,
            'home_form': ''.join(last5_home),
            'away_form': ''.join(last5_away),
        })
    conn.close()
    return results


def analyze_mls_btts_home():
    """MLS_BTTS_HOME: MLS BTTS, home teams from target list.
    Team names in DB are in Russian."""
    conn = sqlite3.connect(DB)

    # Russian team names as stored in backtest_matches
    target_teams = {
        "Интер Майами",
        "Портленд Тимберс",
        "ФК Торонто",
        "Атланта Юнайтед",
        "Орландо Сити",
        "Нэшвилл",
        "Лос-Анджелес Гэлакси",
        "Сан-Хосе Эртквейкс",
    }

    rows = conn.execute("""
        SELECT * FROM backtest_matches
        WHERE league = 'MLS'
          AND odds_btts_yes IS NOT NULL
          AND result IS NOT NULL
          AND season >= '2021'
        ORDER BY match_date ASC, id ASC
    """).fetchall()

    home_results, away_results, team_results = compute_form_for_team(conn, "home_team", "MLS", "2021")

    results = []
    for r in rows:
        mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]

        if ht not in target_teams:
            continue

        btts = (hs > 0 and asc > 0) if hs is not None and asc is not None else None
        if btts is None:
            continue

        last5_away = get_last_n_before_match(away_results.get(at, []), dt, mid, 5)
        last5_home = get_last_n_before_match(home_results.get(ht, []), dt, mid, 5)
        if not last5_away or not last5_home:
            continue

        a_pts = form_points(last5_away)
        h_pts = form_points(last5_home)

        # Segment by away form
        if a_pts <= 5: a_seg = "away_pts<=5"
        elif a_pts <= 9: a_seg = "away_pts=6-9"
        else: a_seg = "away_pts>9"

        if h_pts <= 6: h_seg = "home_pts<=6"
        elif h_pts <= 9: h_seg = "home_pts=7-9"
        else: h_seg = "home_pts>9"

        seg = f"{h_seg}/{a_seg}"

        odds = r[19] if len(r) > 19 else None
        if odds is None:
            continue

        results.append({
            'season': seas,
            'segment': seg,
            'away_segment': a_seg,
            'home_segment': h_seg,
            'odds': float(odds),
            'won': btts,
            'home_team': ht,
            'away_form_pts': a_pts,
            'home_form_pts': h_pts,
        })
    conn.close()
    return results


# ============================================================
# RUN ALL ANALYSES
# ============================================================

print("STARTING FORM FILTER IMPACT ANALYSIS")
print("=" * 80)

for name, func in [
    ("DRAW_SA — Serie A draws", analyze_draw_sa),
    ("DRAW_BL1_FL1 — Bundesliga/Ligue1 draws", analyze_draw_bl1_fl1),
    ("PD_BTTS_DOUBLE — La Liga BTTS", analyze_pd_btts),
    ("RPL_OVER25_BTTS — RPL over 2.5", analyze_rpl_over25),
    ("MLS_BTTS_HOME — MLS BTTS target home teams", analyze_mls_btts_home),
]:
    try:
        analyze_strategy(func, name)
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"ERROR in {name}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
