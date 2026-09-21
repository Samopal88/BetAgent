import sqlite3
import sys
from collections import defaultdict

DB = "/root/betagent/betagent.db"
LEAGUES = ['DNK', 'SWE', 'FIN', 'IRL']

conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = conn.execute(f"""
    SELECT league, substr(match_date,1,4) as yr, match_date,
           home_team, away_team, home_score, away_score,
           odds_home, odds_draw, odds_away,
           odds_btts_yes, odds_btts_no,
           odds_over_2_5, odds_under_2_5
    FROM backtest_matches
    WHERE league IN ({','.join(['?']*len(LEAGUES))})
      AND home_score IS NOT NULL AND away_score IS NOT NULL
""", LEAGUES).fetchall()
conn.close()

print(f"Loaded {len(rows)} matches (DNK/SWE/FIN/IRL with scores)")

# Parse into dicts
data = []
for r in rows:
    data.append({
        'league': r[0], 'yr': r[1], 'mdate': r[2],
        'home': r[3], 'away': r[4],
        'hs': r[5], 'as': r[6],
        'odds_h': r[7], 'odds_d': r[8], 'odds_a': r[9],
        'btts_y': r[10], 'btts_n': r[11],
        'ov25': r[12], 'un25': r[13],
    })

def is_btts(r):
    return r['hs'] >= 1 and r['as'] >= 1
def is_home(r):
    return r['hs'] > r['as']
def is_draw(r):
    return r['hs'] == r['as']
def is_over25(r):
    return r['hs'] + r['as'] > 2.5

def roi(pct, avg_odds):
    return (pct/100.0 * avg_odds - 1) * 100

def by_league_year(d, filt_func, odds_key):
    """Group by league then year, return stats."""
    out = {}
    for lg in sorted(set(r['league'] for r in d)):
        lg_data = [r for r in d if r['league'] == lg]
        hits = sum(1 for r in lg_data if filt_func(r))
        pct = hits / len(lg_data) * 100
        avg_od = sum(r[odds_key] for r in lg_data) / len(lg_data)
        r_val = roi(pct, avg_od)
        out[lg] = {'yr_agg': {'ALL': (len(lg_data), hits, pct, avg_od, r_val)}}

        years = sorted(set(r['yr'] for r in lg_data))
        for yr in years:
            y = [r for r in lg_data if r['yr'] == yr]
            h = sum(1 for r in y if filt_func(r))
            p = h / len(y) * 100 if y else 0
            ao = sum(r[odds_key] for r in y) / len(y) if y else 0
            rv = roi(p, ao)
            out[lg]['yr_agg'][yr] = (len(y), h, p, ao, rv)
    return out

def print_table(d, label, filt_desc):
    print(f"\n{'='*80}")
    print(f"{label} — {filt_desc}")
    print(f"{'='*80}")
    print(f"{'League':<7} {'Year':<6} {'N':>5} {'Hits':>5} {'Hit%':>6} {'AvgOdds':>8} {'ROI':>7}")
    print(f"{'-'*80}")

    for lg in sorted(d.keys()):
        for yr in sorted(d[lg]['yr_agg'].keys()):
            n, h, p, ao, rv = d[lg]['yr_agg'][yr]
            print(f"{lg:<7} {yr:<6} {n:>5} {h:>5} {p:>5.1f}% {ao:>7.2f} {rv:>+5.1f}%")
        print(f"{'-'*80}")

# ================================================================
# 1. BTTS YES by odds range
# ================================================================
print("\n" + "#" * 60)
print("1. BTTS YES — odds ranges")
print("#" * 60)

for lo, hi, lbl in [(1.50,1.75,"1.50-1.75"), (1.75,2.00,"1.75-2.00"), (1.80,2.20,"1.80-2.20")]:
    btts_range = [r for r in data if r['btts_y'] is not None and lo <= r['btts_y'] <= hi]
    d = by_league_year(btts_range, is_btts, 'btts_y')
    print_table(d, f"BTTS YES odds {lbl}", f"is_btts AND {lo}<={lbl}<={hi}")

# BTTS by specific home teams (across 3+ seasons)
print(f"\n{'='*80}")
print("5. SPECIFIC HOME TEAMS — BTTS analysis (SUMMER_BTTS_HOME style)")
print(f"{'='*80}")

# Collect all BTTS-eligible matches by home team
team_btts = defaultdict(list)
for r in data:
    if r['btts_y'] is not None:
        team_btts[(r['league'], r['home'])].append(r)

# Filter teams with 3+ seasons and enough matches (avg 20/year)
print(f"\nTeams with >=3 seasons, avg >=20 matches/year:")
print(f"{'League':<7} {'Team':<25} {'Seasons':>8} {'Total':>6} {'BTTS%':>6} {'AvgOdds':>8} {'ROI':>7}")
print(f"{'-'*80}")

for (lg, team), matches in sorted(team_btts.items()):
    seasons = set(r['yr'] for r in matches)
    if len(seasons) < 3:
        continue
    avg_matches = len(matches) / len(seasons)
    if avg_matches < 15:
        continue
    btts_hits = sum(1 for r in matches if is_btts(r))
    btts_pct = btts_hits / len(matches) * 100
    avg_odds = sum(r['btts_y'] for r in matches if r['btts_y']) / max(sum(1 for r in matches if r['btts_y']), 1)
    rv = roi(btts_pct, avg_odds)
    print(f"{lg:<7} {team:<25} {len(seasons):>3} ({','.join(sorted(seasons))[:40]}) {len(matches):>6} {btts_pct:>5.1f}% {avg_odds:>7.2f} {rv:>+5.1f}%")

# BTTS for specific home teams at specific odds ranges
print(f"\n--- Home teams at BTTS odds 1.50-1.75 ---")
print(f"{'League':<7} {'Team':<25} {'Seasons':>8} {'N':>5} {'Hits':>5} {'BTTS%':>6} {'ROI':>7}")
print(f"{'-'*80}")

team_odds_btts = defaultdict(list)
for r in data:
    if r['btts_y'] is not None and 1.50 <= r['btts_y'] <= 1.75:
        team_odds_btts[(r['league'], r['home'])].append(r)

team_odds_results = []
for (lg, team), matches in sorted(team_odds_btts.items()):
    seasons = set(r['yr'] for r in matches)
    if len(seasons) < 2:
        continue
    btts_hits = sum(1 for r in matches if is_btts(r))
    btts_pct = btts_hits / len(matches) * 100 if matches else 0
    avg_odds = sum(r['btts_y'] for r in matches) / len(matches) if matches else 0
    rv = roi(btts_pct, avg_odds)
    team_odds_results.append((lg, team, len(seasons), len(matches), btts_hits, btts_pct, avg_odds, rv))

# Sort by ROI
team_odds_results.sort(key=lambda x: x[7], reverse=True)
for lg, team, seas, n, h, pct, ao, rv in team_odds_results:
    if n >= 15:
        print(f"{lg:<7} {team:<25} {seas:>3} yrs {n:>5} {h:>5} {pct:>5.1f}% {rv:>+5.1f}%")

# ================================================================
# 2. Home win at 1.40-1.65
# ================================================================
print(f"\n{'='*80}")
print("2. HOME WIN — odds 1.40-1.65 (like FIN showed +9.7%)")
print(f"{'='*80}")

home_range = [r for r in data if r['odds_h'] is not None and 1.40 <= r['odds_h'] <= 1.65]
d = by_league_year(home_range, is_home, 'odds_h')
print_table(d, "HOME WIN", f"odds_home 1.40-1.65")

# Also test 1.50-1.70
home_range2 = [r for r in data if r['odds_h'] is not None and 1.50 <= r['odds_h'] <= 1.70]
d2 = by_league_year(home_range2, is_home, 'odds_h')
print_table(d2, "HOME WIN", f"odds_home 1.50-1.70")

# ================================================================
# 3. Draw patterns
# ================================================================
print(f"\n{'='*80}")
print("3. DRAW — odds 3.0-4.0")
print(f"{'='*80}")

draw_range = [r for r in data if r['odds_d'] is not None and 3.0 <= r['odds_d'] <= 4.0]
d = by_league_year(draw_range, is_draw, 'odds_d')
print_table(d, "DRAW", f"odds_draw 3.0-4.0")

# Also 3.2-3.8 (tighter)
draw_range2 = [r for r in data if r['odds_d'] is not None and 3.2 <= r['odds_d'] <= 3.8]
d2 = by_league_year(draw_range2, is_draw, 'odds_d')
print_table(d2, "DRAW", f"odds_draw 3.2-3.8")

# ================================================================
# 4. Over 2.5 by league and odds
# ================================================================
print(f"\n{'='*80}")
print("4. OVER 2.5 — odds 1.60-1.90")
print(f"{'='*80}")

ov_range = [r for r in data if r['ov25'] is not None and 1.60 <= r['ov25'] <= 1.90]
d = by_league_year(ov_range, is_over25, 'ov25')
print_table(d, "OVER 2.5", f"odds_over_2_5 1.60-1.90")

# Also 1.70-2.00
ov_range2 = [r for r in data if r['ov25'] is not None and 1.70 <= r['ov25'] <= 2.00]
d2 = by_league_year(ov_range2, is_over25, 'ov25')
print_table(d2, "OVER 2.5", f"odds_over_2_5 1.70-2.00")

# ================================================================
# SUMMARY: Top findings
# ================================================================
print(f"\n{'='*80}")
print("SUMMARY — Top findings (ROI >= +10%, positive 4/5 years, n>=20/yr)")
print(f"{'='*80}")

# Pre-compute all combos
analyses = []

# 1. BTTS combos
for lo, hi, lbl in [(1.50,1.75,"150-175"), (1.75,2.00,"175-200"), (1.80,2.20,"180-220")]:
    subset = [r for r in data if r['btts_y'] is not None and lo <= r['btts_y'] <= hi]
    for lg in LEAGUES:
        lg_sub = [r for r in subset if r['league'] == lg]
        if not lg_sub:
            continue
        hits = sum(1 for r in lg_sub if is_btts(r))
        pct = hits/len(lg_sub)*100
        odds = sum(r['btts_y'] for r in lg_sub)/len(lg_sub)
        analyses.append({'type':'BTTS', 'range':lbl, 'league':lg, 'data':lg_sub, 'pct':pct, 'odds':odds, 'roi':roi(pct,odds),
                          'total_n':len(lg_sub), 'total_hits':hits})
        by_yr = defaultdict(list)
        pos_yrs = 0
        for r in lg_sub:
            by_yr[r['yr']].append(r)
        for yr, grp in sorted(by_yr.items()):
            if yr == '2026' or yr == '2019':
                continue
            yr_pct = sum(1 for g in grp if is_btts(g))/len(grp)*100
            yr_odds = sum(g['btts_y'] for g in grp)/len(grp)
            if yr_pct * yr_odds / 100 - 1 > 0:
                pos_yrs += 1
        analyses[-1]['pos_yrs'] = pos_yrs
        analyses[-1]['n_yrs'] = len([y for y in by_yr if y not in ('2019','2026')])
        analyses[-1]['avg_yr_n'] = len(lg_sub)/max(len([y for y in by_yr if y not in ('2019','2026')]),1)

# 2. Home win combos
for lo, hi, lbl in [(1.40,1.65,"140-165"), (1.50,1.70,"150-170")]:
    subset = [r for r in data if r['odds_h'] is not None and lo <= r['odds_h'] <= hi]
    for lg in LEAGUES:
        lg_sub = [r for r in subset if r['league'] == lg]
        if not lg_sub:
            continue
        hits = sum(1 for r in lg_sub if is_home(r))
        pct = hits/len(lg_sub)*100
        odds = sum(r['odds_h'] for r in lg_sub)/len(lg_sub)
        analyses.append({'type':'HOME', 'range':lbl, 'league':lg, 'data':lg_sub, 'pct':pct, 'odds':odds, 'roi':roi(pct,odds),
                          'total_n':len(lg_sub), 'total_hits':hits})
        by_yr = defaultdict(list)
        pos_yrs = 0
        for r in lg_sub:
            by_yr[r['yr']].append(r)
        for yr, grp in sorted(by_yr.items()):
            if yr == '2026' or yr == '2019':
                continue
            yr_pct = sum(1 for g in grp if is_home(g))/len(grp)*100
            yr_odds = sum(g['odds_h'] for g in grp)/len(grp)
            if yr_pct * yr_odds / 100 - 1 > 0:
                pos_yrs += 1
        analyses[-1]['pos_yrs'] = pos_yrs
        analyses[-1]['n_yrs'] = len([y for y in by_yr if y not in ('2019','2026')])
        analyses[-1]['avg_yr_n'] = len(lg_sub)/max(len([y for y in by_yr if y not in ('2019','2026')]),1)

# 3. Draw combos
for lo, hi, lbl in [(3.0,4.0,"300-400"), (3.2,3.8,"320-380")]:
    subset = [r for r in data if r['odds_d'] is not None and lo <= r['odds_d'] <= hi]
    for lg in LEAGUES:
        lg_sub = [r for r in subset if r['league'] == lg]
        if not lg_sub:
            continue
        hits = sum(1 for r in lg_sub if is_draw(r))
        pct = hits/len(lg_sub)*100
        odds = sum(r['odds_d'] for r in lg_sub)/len(lg_sub)
        analyses.append({'type':'DRAW', 'range':lbl, 'league':lg, 'data':lg_sub, 'pct':pct, 'odds':odds, 'roi':roi(pct,odds),
                          'total_n':len(lg_sub), 'total_hits':hits})
        by_yr = defaultdict(list)
        pos_yrs = 0
        for r in lg_sub:
            by_yr[r['yr']].append(r)
        for yr, grp in sorted(by_yr.items()):
            if yr == '2026' or yr == '2019':
                continue
            yr_pct = sum(1 for g in grp if is_draw(g))/len(grp)*100
            yr_odds = sum(g['odds_d'] for g in grp)/len(grp)
            if yr_pct * yr_odds / 100 - 1 > 0:
                pos_yrs += 1
        analyses[-1]['pos_yrs'] = pos_yrs
        analyses[-1]['n_yrs'] = len([y for y in by_yr if y not in ('2019','2026')])
        analyses[-1]['avg_yr_n'] = len(lg_sub)/max(len([y for y in by_yr if y not in ('2019','2026')]),1)

# 4. Over 2.5 combos
for lo, hi, lbl in [(1.60,1.90,"160-190"), (1.70,2.00,"170-200")]:
    subset = [r for r in data if r['ov25'] is not None and lo <= r['ov25'] <= hi]
    for lg in LEAGUES:
        lg_sub = [r for r in subset if r['league'] == lg]
        if not lg_sub:
            continue
        hits = sum(1 for r in lg_sub if is_over25(r))
        pct = hits/len(lg_sub)*100
        odds = sum(r['ov25'] for r in lg_sub)/len(lg_sub)
        analyses.append({'type':'OVER25', 'range':lbl, 'league':lg, 'data':lg_sub, 'pct':pct, 'odds':odds, 'roi':roi(pct,odds),
                          'total_n':len(lg_sub), 'total_hits':hits})
        by_yr = defaultdict(list)
        pos_yrs = 0
        for r in lg_sub:
            by_yr[r['yr']].append(r)
        for yr, grp in sorted(by_yr.items()):
            if yr == '2026' or yr == '2019':
                continue
            yr_pct = sum(1 for g in grp if is_over25(g))/len(grp)*100
            yr_odds = sum(g['ov25'] for g in grp)/len(grp)
            if yr_pct * yr_odds / 100 - 1 > 0:
                pos_yrs += 1
        analyses[-1]['pos_yrs'] = pos_yrs
        analyses[-1]['n_yrs'] = len([y for y in by_yr if y not in ('2019','2026')])
        analyses[-1]['avg_yr_n'] = len(lg_sub)/max(len([y for y in by_yr if y not in ('2019','2026')]),1)

# Filter top findings: ROI >= 10%, positive 4/5 yrs, n>=20/yr, roi > 0
findings = [a for a in analyses if a['roi'] >= 10.0 and a['pos_yrs'] >= 4
            and a.get('avg_yr_n', 0) >= 10]
findings.sort(key=lambda x: x['roi'], reverse=True)

print(f"\n{'Type':<8} {'League':<6} {'Range':<10} {'TotN':>5} {'Hit%':>6} {'Odds':>6} {'ROI':>7} {'PosYrs':>7} {'AvgYrN':>7}")
print(f"{'-'*80}")
for f in findings:
    print(f"{f['type']:<8} {f['league']:<6} {f['range']:<10} {f['total_n']:>5} {f['pct']:>5.1f}% {f['odds']:>5.2f} {f['roi']:>+5.1f}% {f['pos_yrs']:>4}/{f['n_yrs']} {f['avg_yr_n']:>6.0f}")

# Expanded: also show anything with ROI >= 5% and pos_yrs >= 3
print(f"\n--- Relaxed filter (ROI >= +5%, positive 3/5 years) ---")
findings2 = [a for a in analyses if a['roi'] >= 5.0 and a['pos_yrs'] >= 3 and a.get('avg_yr_n', 0) >= 10]
findings2.sort(key=lambda x: x['roi'], reverse=True)
print(f"{'Type':<8} {'League':<6} {'Range':<10} {'TotN':>5} {'Hit%':>6} {'Odds':>6} {'ROI':>7} {'PosYrs':>7} {'AvgYrN':>7}")
print(f"{'-'*80}")
for f in findings2[:30]:
    print(f"{f['type']:<8} {f['league']:<6} {f['range']:<10} {f['total_n']:>5} {f['pct']:>5.1f}% {f['odds']:>5.2f} {f['roi']:>+5.1f}% {f['pos_yrs']:>4}/{f['n_yrs']} {f['avg_yr_n']:>6.0f}")
