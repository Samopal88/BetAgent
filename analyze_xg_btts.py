import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, "/root/betagent")
from team_name_mapping import map_team

DB = "/root/betagent/betagent.db"
LEAGUES = ['EPL','SA','PD','FL1','RPL','BL1']
BETTS_MIN, BTTS_MAX = 1.80, 2.20
XG_H_MIN, XG_A_MIN = 1.2, 1.0
XG_COMBINED_MIN = 2.8

conn = sqlite3.connect(DB)
cur = conn.cursor()

# --- Load matches ---
placeholders = ','.join('?'*len(LEAGUES))
cur.execute(f"""
    SELECT league, season, match_date, home_team, away_team,
           home_score, away_score, odds_btts_yes
    FROM backtest_matches
    WHERE league IN ({placeholders})
      AND odds_btts_yes IS NOT NULL
      AND home_score IS NOT NULL AND away_score IS NOT NULL
""", LEAGUES)
matches_rows = cur.fetchall()
print(f"Loaded {len(matches_rows)} matches from {len(LEAGUES)} leagues")

# --- Load stats into dict: (date, home_rus, away_rus) -> {xg_h, xg_a} ---
cur.execute("SELECT match_date, home_team, away_team, shots_home, shots_away, xg_home_proxy, xg_away_proxy FROM backtest_football_stats")
stats = {}
for r in cur.fetchall():
    stats[(r[0], r[1], r[2])] = {'xg_h': r[5], 'xg_a': r[6]}
conn.close()

print(f"Loaded {len(stats)} stats rows")

# --- Map teams and join ---
print("\nMapping team names...")
unmapped_names = set()
merged = []  # each item is a dict

for row in matches_rows:
    league, season, mdate, home_eng, away_eng, hscore, ascore, btts_odds = row
    home_rus = map_team(home_eng, league)
    away_rus = map_team(away_eng, league)

    # RPL already has Russian names, skip "unmapped" check for it
    if league != 'RPL':
        if home_rus == home_eng:
            unmapped_names.add(f"{league}/home/{home_eng}")
        if away_rus == away_eng:
            unmapped_names.add(f"{league}/away/{away_eng}")

    xg = stats.get((mdate, home_rus, away_rus))
    if xg is None:
        xg = stats.get((mdate, away_rus, home_rus))

    merged.append({
        'league': league, 'season': season, 'mdate': mdate,
        'home_rus': home_rus, 'away_rus': away_rus,
        'home_score': hscore, 'away_score': ascore,
        'btts_odds': btts_odds,
        'xg_h': xg['xg_h'] if xg and xg.get('xg_h') else None,
        'xg_a': xg['xg_a'] if xg and xg.get('xg_a') else None,
    })

with_xg = [r for r in merged if r['xg_h'] is not None]
print(f"Matched: {len(with_xg)}/{len(merged)} ({len(with_xg)/len(merged)*100:.0f}%)")
if unmapped_names:
    print(f"\nUnmapped names ({len(unmapped_names)}):")
    for n in sorted(unmapped_names)[:30]:
        print(f"  {n}")
    if len(unmapped_names) > 30:
        print(f"  ...+{len(unmapped_names)-30} more")

# --- BTTS-eligible ---
btts = [r for r in with_xg if BETTS_MIN <= r['btts_odds'] <= BTTS_MAX]
print(f"\nBTTS-eligible (odds {BETTS_MIN}-{BTTS_MAX} + xG data): {len(btts)}")

def is_btts(r):
    return r['home_score'] >= 1 and r['away_score'] >= 1

def roi(pct, avg_odds):
    return (pct/100.0 * avg_odds - 1) * 100

def show_table(data, label):
    if not data:
        print(f"\n{label}: no data")
        return
    print(f"\n{'='*72}")
    print(f"{label}")
    print(f"{'='*72}")
    print(f"{'League':<6} {'Year':<7} {'N':>5} {'BTTS%':>6} {'Odds':>5} {'xgH':>5} {'xgA':>5} {'ROI':>6}")
    print(f"{'-'*72}")

    grand_btts = sum(1 for r in data if is_btts(r))
    grand_odds = sum(r['btts_odds'] for r in data) / len(data)
    grand_n = len(data)
    grand_pct = grand_btts / grand_n * 100

    by_league = defaultdict(list)
    for r in data:
        by_league[r['league']].append(r)

    for league in sorted(by_league):
        grp = by_league[league]
        btts_c = sum(1 for r in grp if is_btts(r))
        pct = btts_c / len(grp) * 100
        avg_odds = sum(r['btts_odds'] for r in grp) / len(grp)
        avg_xgh = sum(r['xg_h'] for r in grp if r['xg_h']) / max(sum(1 for r in grp if r['xg_h']), 1)
        avg_xga = sum(r['xg_a'] for r in grp if r['xg_a']) / max(sum(1 for r in grp if r['xg_a']), 1)
        print(f"{league:<6} {'ALL':<7} {len(grp):>5} {pct:>5.1f}% {avg_odds:>5.2f} {avg_xgh:>4.2f} {avg_xga:>4.2f} {roi(pct,avg_odds):>+5.1f}%")

        for year in sorted(set(r['season'] for r in grp)):
            sub = [r for r in grp if r['season'] == year]
            sc = sum(1 for r in sub if is_btts(r))
            sp = sc / len(sub) * 100
            so = sum(r['btts_odds'] for r in sub) / len(sub)
            sxg_h = sum(r['xg_h'] for r in sub if r['xg_h']) / max(sum(1 for r in sub if r['xg_h']), 1)
            sxg_a = sum(r['xg_a'] for r in sub if r['xg_a']) / max(sum(1 for r in sub if r['xg_a']), 1)
            print(f"{league:<6} {year:<7} {len(sub):>5} {sp:>5.1f}% {so:>5.2f} {sxg_h:>4.2f} {sxg_a:>4.2f} {roi(sp,so):>+5.1f}%")

    print(f"{'-'*72}")
    print(f"{'TOTAL':<13} {grand_n:>5} {grand_pct:>5.1f}% {grand_odds:>5.2f}")
    return grand_pct, grand_odds, grand_n

# ========== TEST 1: Individual xG thresholds ==========
baseline = btts
filt_ind = [r for r in btts if r['xg_h'] is not None and r['xg_a'] is not None and r['xg_h'] >= XG_H_MIN and r['xg_a'] >= XG_A_MIN]

print(f"\n{'#'*60}")
print(f"TEST 1: Individual xG filter (xgH >= {XG_H_MIN} AND xgA >= {XG_A_MIN})")
print(f"{'#'*60}")

show_table(baseline, f"BASELINE — all BTTS-eligible (no xG filter)")
bp, bo, bn = sum(1 for r in baseline if is_btts(r))/len(baseline)*100, sum(r['btts_odds'] for r in baseline)/len(baseline), len(baseline)
print(f"  -> {bn} bets, BTTS={bp:.1f}%, avg_odds={bo:.2f}, ROI={roi(bp,bo):+.1f}%")

show_table(filt_ind, f"FILTERED — xgH>={XG_H_MIN}, xgA>={XG_A_MIN}")
if filt_ind:
    fp = sum(1 for r in filt_ind if is_btts(r))/len(filt_ind)*100
    fo = sum(r['btts_odds'] for r in filt_ind)/len(filt_ind)
    print(f"  -> {len(filt_ind)} bets, BTTS={fp:.1f}%, avg_odds={fo:.2f}, ROI={roi(fp,fo):+.1f}%")
    print(f"\n  Lift: {roi(fp,fo)-roi(bp,bo):+.1f}pp  ({bn-len(filt_ind)} bets removed)")

# Per-league comparison
print(f"\nPer-league comparison:")
print(f"{'League':<6} {'BaseN':>5} {'Base%':>5} {'BaseROI':>7}   {'FiltN':>5} {'Filt%':>5} {'FiltROI':>7} {'Lift':>6}")
for lg in sorted(set(r['league'] for r in baseline)):
    b = [r for r in baseline if r['league'] == lg]
    f = [r for r in filt_ind if r['league'] == lg]
    bp_l = sum(1 for r in b if is_btts(r))/len(b)*100
    bo_l = sum(r['btts_odds'] for r in b)/len(b)
    fp_l = sum(1 for r in f if is_btts(r))/len(f)*100 if f else 0
    fo_l = sum(r['btts_odds'] for r in f)/len(f) if f else 0
    print(f"{lg:<6} {len(b):>5} {bp_l:>4.1f}% {roi(bp_l,bo_l):>+5.1f}%  |{len(f):>5} {fp_l:>4.1f}% {roi(fp_l,fo_l):>+5.1f}% {roi(fp_l,fo_l)-roi(bp_l,bo_l):>+5.1f}pp")

# ========== TEST 2: Combined xG sum ==========
print(f"\n{'#'*60}")
print(f"TEST 2: Combined xG filter (xgH + xgA >= threshold)")
print(f"{'#'*60}")

for thr in [XG_COMBINED_MIN]:
    sub = [r for r in btts if r['xg_h'] is not None and r['xg_a'] is not None and r['xg_h'] + r['xg_a'] >= thr]
    if not sub:
        continue
    show_table(sub, f"COMBINED — xgH+xgA>={thr}")
    sp = sum(1 for r in sub if is_btts(r))/len(sub)*100
    so = sum(r['btts_odds'] for r in sub)/len(sub)
    print(f"  -> {len(sub)} bets, BTTS={sp:.1f}%, avg_odds={so:.2f}, ROI={roi(sp,so):+.1f}%")

# Sweep
print(f"\nSweep: combined xG threshold")
print(f"{'Threshold':>10} {'N':>6} {'BTTS%':>6} {'ROI':>7} {'Remain%':>7}")
for thr in [2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6]:
    sub = [r for r in btts if r['xg_h'] is not None and r['xg_a'] is not None and r['xg_h'] + r['xg_a'] >= thr]
    if not sub:
        continue
    sp = sum(1 for r in sub if is_btts(r))/len(sub)*100
    so = sum(r['btts_odds'] for r in sub)/len(sub)
    print(f"{thr:>10.1f} {len(sub):>6} {sp:>5.1f}% {roi(sp,so):>+5.1f}% {len(sub)/len(btts)*100:>6.0f}%")

# Distribution
print(f"\nxG sum distribution:")
print(f"{'Range':<18} {'N':>6} {'BTTS%':>6} {'ROI':>7}")
for lo, hi in [(0,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,3.5),(3.5,4.0),(4.0,5.0),(5.0,100)]:
    sub = [r for r in btts if r['xg_h'] is not None and r['xg_a'] is not None and lo <= r['xg_h'] + r['xg_a'] < hi]
    if not sub:
        continue
    sp = sum(1 for r in sub if is_btts(r))/len(sub)*100
    so = sum(r['btts_odds'] for r in sub)/len(sub)
    hi_s = f"{hi:.0f}+" if hi > 50 else f"{hi:.1f}"
    print(f"{lo:.1f} - {hi_s:<12} {len(sub):>6} {sp:>5.1f}% {roi(sp,so):>+5.1f}%")
