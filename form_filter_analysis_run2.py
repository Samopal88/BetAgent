#!/usr/bin/env python3
"""
Run just the 2 fixed analyses from form_filter_analysis.py.
"""

import sqlite3
import json
from collections import defaultdict

DB = "betagent.db"

def form_points(results_list):
    pts = 0
    for x in results_list:
        if x == 'W': pts += 3
        elif x == 'D': pts += 1
    return pts

def compute_form_for_team(conn, team_field, league, season_cutoff="2021"):
    rows = conn.execute(f"""
        SELECT id, home_team, away_team, result, match_date, season
        FROM backtest_matches
        WHERE league = ? AND result IS NOT NULL AND season >= ?
        ORDER BY match_date ASC, id ASC
    """, (league, season_cutoff)).fetchall()

    team_results = defaultdict(list)
    home_results = defaultdict(list)
    away_results = defaultdict(list)

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

    return dict(home_results), dict(away_results), dict(team_results)


def get_last_n_before_match(results_list, match_date, match_id, n):
    results = []
    for result, mid, dt in reversed(results_list):
        if (dt, mid) >= (match_date, match_id):
            continue
        results.append(result)
        if len(results) >= n:
            break
    return list(reversed(results))


def aggregate_and_print(all_results, metric_name, segments_order=None):
    """
    all_results: list of dicts with 'season', 'segment', 'odds', 'won', 'home_team'(optional), 'away_team'(optional)
    """
    year_stats = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'hits': 0, 'total_return': 0.0}))

    for r in all_results:
        year = r['season']
        segment = r['segment']
        odds = r['odds']
        won = r['won']

        ys = year_stats[year][segment]
        ys['n'] += 1
        if won:
            ys['hits'] += 1
        ys['total_return'] += odds if won else 0.0

    all_segments = sorted(all_results, key=lambda x: x['segment'])
    all_segments = sorted(set(r['segment'] for r in all_results))
    if segments_order:
        all_segments = [s for s in segments_order if s in set(all_segments)]

    all_years = sorted(year_stats.keys())

    print(f"\nTotal matches: {len(all_results)}")
    print(f"\n{'Year':<7} | {'Segment':<25} | {'N':>5} | {metric_name+chr(37):>7} | {'ROI%':>7}")
    print("-" * 60)

    for year in all_years:
        for seg in all_segments:
            if seg not in year_stats[year]:
                continue
            s = year_stats[year][seg]
            pct = s['hits'] / s['n'] * 100 if s['n'] > 0 else 0
            roi = (s['total_return'] / s['n'] - 1) * 100 if s['n'] > 0 else 0
            print(f"{year:<7} | {seg:<25} | {s['n']:>5} | {pct:>6.1f}% | {roi:>6.1f}%")

    # Overall
    total_n = sum(s['n'] for yy in year_stats.values() for s in yy.values())
    total_hits = sum(s['hits'] for yy in year_stats.values() for s in yy.values())
    total_stake = total_n
    total_return = sum(s['total_return'] for yy in year_stats.values() for s in yy.values())
    total_pct = total_hits / total_n * 100 if total_n > 0 else 0
    total_roi = (total_return / total_stake - 1) * 100 if total_stake > 0 else 0
    print(f"\nOverall: N={total_n}, {metric_name}={total_pct:.1f}%, ROI={total_roi:.1f}%")

    # Per-segment overall
    print(f"\n--- Per-segment overall ---")
    for seg in all_segments:
        sn = sum(year_stats[y].get(seg, {}).get('n', 0) for y in year_stats)
        sh = sum(year_stats[y].get(seg, {}).get('hits', 0) for y in year_stats)
        sr = sum(year_stats[y].get(seg, {}).get('total_return', 0) for y in year_stats)
        sp = sh / sn * 100 if sn > 0 else 0
        sroi = (sr / sn - 1) * 100 if sn > 0 else 0
        print(f"{seg:<25} | N={sn:>5} | {metric_name}={sp:>6.1f}% | ROI={sroi:>6.1f}%")

        # Per-year breakdown for this segment
        for year in all_years:
            ys = year_stats[year].get(seg)
            if ys:
                pp = ys['hits'] / ys['n'] * 100 if ys['n'] > 0 else 0
                proi = (ys['total_return'] / ys['n'] - 1) * 100 if ys['n'] > 0 else 0
                print(f"   {year}: N={ys['n']:>3}, {metric_name}={pp:>6.1f}%, ROI={proi:>6.1f}%")

    return all_results


print("=" * 80)
print("FORM FILTER ANALYSIS — FIXED ANALYSES")
print("=" * 80)

# ==========================================
# DRAW_BL1_FL1
# ==========================================
print("\n" + "=" * 80)
print("DRAW_BL1_FL1 — Bundesliga/Ligue1 draws (home form)")
print("=" * 80)

conn = sqlite3.connect(DB)

home_results = {}
away_results = {}
for lg in ['BL1', 'FL1']:
    h, a, t = compute_form_for_team(conn, "home_team", lg, "2021")
    home_results[lg] = h
    away_results[lg] = a

rows = conn.execute("""
    SELECT id, league, home_team, away_team, result, match_date, season, odds_draw
    FROM backtest_matches
    WHERE league IN ('BL1', 'FL1')
      AND odds_draw BETWEEN 3.05 AND 3.70
      AND result IS NOT NULL
      AND season >= '2021'
    ORDER BY match_date ASC, id ASC
""").fetchall()

results = []
for r in rows:
    mid, lg, ht, at, res, dt, seas, od = r
    h = home_results.get(lg, {})
    rl = h.get(ht, [])
    last5 = get_last_n_before_match(rl, dt, mid, 5)
    if not last5:
        continue
    pts = form_points(last5)
    if pts <= 5: seg = "home<=5"
    elif pts <= 8: seg = "home=6-8"
    elif pts <= 12: seg = "home=9-12"
    else: seg = "home>12"

    btts_odds = None
    if len(r) > 7:
        btts_odds = float(od) if od else None
    if btts_odds is None:
        continue

    results.append({
        'season': seas,
        'segment': seg,
        'odds': btts_odds,
        'won': res == 'D',
    })

aggregate_and_print(results, "Draw%")
conn.close()


# ==========================================
# MLS_BTTS_HOME
# ==========================================
print("\n" + "=" * 80)
print("MLS_BTTS_HOME — MLS BTTS target home teams")
print("=" * 80)

conn = sqlite3.connect(DB)

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

home_results_all, away_results_all, team_results_all = compute_form_for_team(conn, "home_team", "MLS", "2021")

results = []
for r in rows:
    mid, lg, lg_name, seas, dt, ht, at, hs, asc, res, oh, od, oa = r[:13]

    if ht not in target_teams:
        continue

    btts = (hs > 0 and asc > 0) if hs is not None and asc is not None else None
    if btts is None:
        continue

    last5_away = get_last_n_before_match(away_results_all.get(at, []), dt, mid, 5)
    last5_home = get_last_n_before_match(home_results_all.get(ht, []), dt, mid, 5)
    if not last5_away or not last5_home:
        continue

    a_pts = form_points(last5_away)
    h_pts = form_points(last5_home)

    if a_pts <= 5: a_seg = "away<=5"
    elif a_pts <= 9: a_seg = "away=6-9"
    else: a_seg = "away>9"

    if h_pts <= 6: h_seg = "home<=6"
    elif h_pts <= 9: h_seg = "home=7-9"
    else: h_seg = "home>9"

    seg = f"{h_seg} / {a_seg}"

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

# Analysis 1: by cross-segment
print("\n--- By cross-segment ---")
aggregate_and_print(results, "BTTS%")

# Analysis 2: by away form only (aggregating across all home form)
print("\n\n--- By away form only ---")
away_only = []
for r in results:
    away_only.append({
        'season': r['season'],
        'segment': r['away_segment'],
        'odds': r['odds'],
        'won': r['won'],
    })
aggregate_and_print(away_only, "BTTS%")

# Analysis 3: by home form only
print("\n\n--- By home form only ---")
home_only = []
for r in results:
    home_only.append({
        'season': r['season'],
        'segment': r['home_segment'],
        'odds': r['odds'],
        'won': r['won'],
    })
aggregate_and_print(home_only, "BTTS%")

# Analysis 4: Filter with away_form >= 6 effect
print("\n\n--- Effect of away_pts >= 6 filter ---")
target_teams_list = [
    "Интер Майами", "Портленд Тимберс", "ФК Торонто",
    "Атланта Юнайтед", "Орландо Сити", "Нэшвилл",
    "Лос-Анджелес Гэлакси", "Сан-Хосе Эртквейкс",
]

for year in ['2021', '2022', '2023', '2024', '2025']:
    base = [r for r in results if r['season'] == year]
    filtered = [r for r in base if r['away_form_pts'] >= 6]

    base_hits = sum(1 for r in base if r['won'])
    base_n = len(base)
    base_roi = (sum(r['odds'] for r in base if r['won']) / base_n - 1) * 100 if base_n > 0 else 0

    filt_hits = sum(1 for r in filtered if r['won'])
    filt_n = len(filtered)
    filt_roi = (sum(r['odds'] for r in filtered if r['won']) / filt_n - 1) * 100 if filt_n > 0 else 0

    print(f"{year}: Base N={base_n:>3}, BTTS={base_hits/base_n*100:.1f}%, ROI={base_roi:>6.1f}%  =>  "
          f"Filt away>=6 N={filt_n:>3}, BTTS={filt_hits/filt_n*100:.1f}%, ROI={filt_roi:>6.1f}%  "
          f"(delta ROI: {filt_roi - base_roi:+.1f}pp, n_lost={base_n - filt_n})")

conn.close()

print("\n" + "=" * 80)
print("DONE")
