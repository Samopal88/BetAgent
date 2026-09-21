import sys
import sqlite3
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, "/root/betagent")
from team_name_mapping import map_team, CONVERSION_RATES

DB = "/root/betagent/betagent.db"
LEAGUES = ['EPL', 'SA', 'PD', 'FL1', 'RPL', 'BL1']
BETTS_MIN, BTTS_MAX = 1.80, 2.20
FORM_N = 5
FORM_MIN = 3  # minimum prior matches to trust the rolling avg
XG_H_MIN, XG_A_MIN = 1.2, 1.0

# Map short league codes → Russian league strings
LEAGUE_CODES = {
    "EPL": "Футбол. Англия. Премьер-лига.",
    "SA":  "Футбол. Италия. Серия A.",
    "PD":  "Футбол. Испания. Примера Дивизион.",
    "FL1": "Футбол. Франция. Лига 1.",
    "RPL": "Футбол. Россия. Премьер-Лига.",
    "BL1": "Футбол. Германия. Бундеслига.",
}

conn = sqlite3.connect(DB)
cur = conn.cursor()

# ──────────────────────────────────────────────────────────────
# 1. Load all matches
# ──────────────────────────────────────────────────────────────
placeholders = ','.join('?' * len(LEAGUES))
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

# ──────────────────────────────────────────────────────────────
# 2. Load stats into per-team timeline dicts
#    home_timeline[team_rus] = sorted list of (match_date, shots_as_home)
#    away_timeline[team_rus] = sorted list of (match_date, shots_as_away)
# ──────────────────────────────────────────────────────────────
cur.execute("SELECT league, match_date, home_team, away_team, shots_home, shots_away FROM backtest_football_stats")

home_timeline = defaultdict(list)  # (league_rus, team_rus) -> [(date, shots), ...]
away_timeline = defaultdict(list)

for r in cur.fetchall():
    league_rus, mdate, h_team, a_team, s_home, s_away = r
    if s_home is not None:
        home_timeline[(league_rus, h_team)].append((mdate, s_home))
    if s_away is not None:
        away_timeline[(league_rus, a_team)].append((mdate, s_away))

# Sort timelines
for key in home_timeline:
    home_timeline[key].sort()
for key in away_timeline:
    away_timeline[key].sort()

print(f"Home-team timelines: {len(home_timeline)}")
print(f"Away-team timelines: {len(away_timeline)}")

conn.close()

# ──────────────────────────────────────────────────────────────
# 3. For each match, compute rolling xG from PRIOR matches only
# ──────────────────────────────────────────────────────────────
print("\nComputing rolling xG from prior matches...")

unmapped_names = set()
results = []

for i, row in enumerate(matches_rows):
    league, season, mdate, home_eng, away_eng, hscore, ascore, btts_odds = row
    league_rus = LEAGUE_CODES[league]

    home_rus = map_team(home_eng, league)
    away_rus = map_team(away_eng, league)

    if league != 'RPL':
        if home_rus == home_eng:
            unmapped_names.add(f"{league}/home/{home_eng}")
        if away_rus == away_eng:
            unmapped_names.add(f"{league}/away/{away_eng}")

    # Get home team's prior HOME matches BEFORE this date
    h_tl = home_timeline.get((league_rus, home_rus), [])
    h_prior = [s for d, s in h_tl if d < mdate]
    h_last_n = h_prior[-FORM_N:] if len(h_prior) >= FORM_MIN else None

    # Get away team's prior AWAY matches BEFORE this date
    a_tl = away_timeline.get((league_rus, away_rus), [])
    a_prior = [s for d, s in a_tl if d < mdate]
    a_last_n = a_prior[-FORM_N:] if len(a_prior) >= FORM_MIN else None

    # Calculate rolling xG using league-specific conversion rates
    rates = CONVERSION_RATES.get(league, {"home": 0.32, "away": 0.32})
    xg_roll_h = None
    xg_roll_a = None

    if h_last_n:
        xg_roll_h = (sum(h_last_n) / len(h_last_n)) * rates["home"]
    if a_last_n:
        xg_roll_a = (sum(a_last_n) / len(a_last_n)) * rates["away"]

    results.append({
        'league': league, 'season': season, 'mdate': mdate,
        'home_rus': home_rus, 'away_rus': away_rus,
        'home_score': hscore, 'away_score': ascore,
        'btts_odds': btts_odds,
        'xg_roll_h': xg_roll_h,
        'xg_roll_a': xg_roll_a,
        'h_prior_n': len(h_prior),
        'a_prior_n': len(a_prior),
    })

    if (i + 1) % 2000 == 0:
        print(f"  Processed {i+1}/{len(matches_rows)}...")

# Stats
with_roll = [r for r in results if r['xg_roll_h'] is not None and r['xg_roll_a'] is not None]
print(f"\nMatches with sufficient rolling data: {len(with_roll)}/{len(results)}")
print(f"Insufficient prior matches (skipped from filter): {len(results) - len(with_roll)}")

if unmapped_names:
    print(f"\nUnmapped names ({len(unmapped_names)}):")
    for n in sorted(unmapped_names):
        print(f"  {n}")

# ──────────────────────────────────────────────────────────────
# 4. Help functions
# ──────────────────────────────────────────────────────────────
def is_btts(r):
    return r['home_score'] >= 1 and r['away_score'] >= 1

def roi(pct, avg_odds):
    if avg_odds == 0:
        return 0
    return (pct / 100.0 * avg_odds - 1) * 100

def show_table(data, label):
    if not data:
        print(f"\n{label}: no data")
        return

    grand_btts = sum(1 for r in data if is_btts(r))
    grand_odds = sum(r['btts_odds'] for r in data) / len(data)
    grand_n = len(data)
    grand_pct = grand_btts / grand_n * 100

    by_league = defaultdict(list)
    for r in data:
        by_league[r['league']].append(r)

    lines = []
    for league in sorted(by_league):
        grp = by_league[league]
        btts_c = sum(1 for r in grp if is_btts(r))
        pct = btts_c / len(grp) * 100
        avg_odds = sum(r['btts_odds'] for r in grp) / len(grp)
        avg_xgh = sum(r['xg_roll_h'] for r in grp if r['xg_roll_h'] is not None) / max(sum(1 for r in grp if r['xg_roll_h'] is not None), 1)
        avg_xga = sum(r['xg_roll_a'] for r in grp if r['xg_roll_a'] is not None) / max(sum(1 for r in grp if r['xg_roll_a'] is not None), 1)
        lines.append(f"{league:<6} {'ALL':<7} {len(grp):>5} {pct:>5.1f}% {avg_odds:>5.2f} {avg_xgh:>4.2f} {avg_xga:>4.2f} {roi(pct,avg_odds):>+5.1f}%")

        for year in sorted(set(r['season'] for r in grp)):
            sub = [r for r in grp if r['season'] == year]
            sc = sum(1 for r in sub if is_btts(r))
            sp = sc / len(sub) * 100
            so = sum(r['btts_odds'] for r in sub) / len(sub)
            sxg_h = sum(r['xg_roll_h'] for r in sub if r['xg_roll_h'] is not None) / max(sum(1 for r in sub if r['xg_roll_h'] is not None), 1)
            sxg_a = sum(r['xg_roll_a'] for r in sub if r['xg_roll_a'] is not None) / max(sum(1 for r in sub if r['xg_roll_a'] is not None), 1)
            lines.append(f"{league:<6} {year:<7} {len(sub):>5} {sp:>5.1f}% {so:>5.2f} {sxg_h:>4.2f} {sxg_a:>4.2f} {roi(sp,so):>+5.1f}%")

    return lines, grand_pct, grand_odds, grand_n, grand_btts, len(data)

def format_table(lines, label):
    header = f"League Year        N  BTTS%  Odds  xgH   xgA    ROI"
    sep = "-" * len(header)
    out = []
    out.append(f"\n{'='*len(header)}")
    out.append(f"{label}")
    out.append(f"{'='*len(header)}")
    out.append(header)
    out.append(sep)
    out.extend(lines)
    out.append(sep)
    summary = lines[-1] if lines else ""
    return out

# ──────────────────────────────────────────────────────────────
# 5. Analysis
# ──────────────────────────────────────────────────────────────
btts_all = [r for r in results if BETTS_MIN <= r['btts_odds'] <= BTTS_MAX]
btts_with_roll = [r for r in btts_all if r['xg_roll_h'] is not None and r['xg_roll_a'] is not None]

print(f"\nBTTS-eligible (odds {BETTS_MIN}-{BTTS_MAX}) with rolling xG data: {len(btts_with_roll)}/{len(btts_all)}")

# Matches with insufficient history — included in baseline but not filterable
btts_no_hist = [r for r in btts_all if r['xg_roll_h'] is None or r['xg_roll_a'] is None]

# Output buffer for saving
output = []
def emit(text):
    print(text)
    output.append(text)

# ── BASELINE ──
emit(f"\n{'#'*60}")
emit(f"BTTS ROLLING xG ANALYSIS — Out-of-Sample (no lookahead bias)")
emit(f"{'#'*60}")

bp_pct = sum(1 for r in btts_with_roll if is_btts(r)) / len(btts_with_roll) * 100 if btts_with_roll else 0
bp_odds = sum(r['btts_odds'] for r in btts_with_roll) / len(btts_with_roll) if btts_with_roll else 0
bp_roi = roi(bp_pct, bp_odds)

emit(f"\n--- BASELINE (all BTTS-eligible with rolling data, no xG filter) ---")
header = "League Year        N  BTTS%  Odds  xgH   xgA    ROI"
sep = "-" * len(header)
emit(f"\n{'='*len(header)}")
emit("BASELINE — all BTTS-eligible (no xG filter)")
emit(f"{'='*len(header)}")
emit(header)
emit(sep)

by_league = defaultdict(list)
for r in btts_with_roll:
    by_league[r['league']].append(r)

for league in sorted(by_league):
    grp = by_league[league]
    btts_c = sum(1 for r in grp if is_btts(r))
    pct = btts_c / len(grp) * 100
    avg_odds = sum(r['btts_odds'] for r in grp) / len(grp)
    avg_xgh = sum(r['xg_roll_h'] for r in grp if r['xg_roll_h'] is not None) / max(sum(1 for r in grp if r['xg_roll_h'] is not None), 1)
    avg_xga = sum(r['xg_roll_a'] for r in grp if r['xg_roll_a'] is not None) / max(sum(1 for r in grp if r['xg_roll_a'] is not None), 1)
    emit(f"{league:<6} {'ALL':<7} {len(grp):>5} {pct:>5.1f}% {avg_odds:>5.2f} {avg_xgh:>4.2f} {avg_xga:>4.2f} {roi(pct,avg_odds):>+5.1f}%")

    for year in sorted(set(r['season'] for r in grp)):
        sub = [r for r in grp if r['season'] == year]
        sc = sum(1 for r in sub if is_btts(r))
        sp = sc / len(sub) * 100
        so = sum(r['btts_odds'] for r in sub) / len(sub)
        sxg_h = sum(r['xg_roll_h'] for r in sub if r['xg_roll_h'] is not None) / max(sum(1 for r in sub if r['xg_roll_h'] is not None), 1)
        sxg_a = sum(r['xg_roll_a'] for r in sub if r['xg_roll_a'] is not None) / max(sum(1 for r in sub if r['xg_roll_a'] is not None), 1)
        emit(f"{league:<6} {year:<7} {len(sub):>5} {sp:>5.1f}% {so:>5.2f} {sxg_h:>4.2f} {sxg_a:>4.2f} {roi(sp,so):>+5.1f}%")

emit(sep)
emit(f"{'TOTAL':<13} {len(btts_with_roll):>5} {bp_pct:>5.1f}% {bp_odds:>5.2f}")
emit(f"\nBaseline: {len(btts_with_roll)} bets, BTTS={bp_pct:.1f}%, avg_odds={bp_odds:.2f}, ROI={bp_roi:+.1f}%")

# ── TEST 1: Individual rolling xG thresholds ──
filt_roll = [r for r in btts_with_roll if r['xg_roll_h'] >= XG_H_MIN and r['xg_roll_a'] >= XG_A_MIN]

emit(f"\n{'#'*60}")
emit(f"TEST 1: Rolling xG filter (xgH_roll >= {XG_H_MIN} AND xgA_roll >= {XG_A_MIN})")
emit(f"{'#'*60}")

emit(f"\n--- FILTERED (rolling xG thresholds, {FORM_N}-match lookback) ---")
emit(f"{'='*len(header)}")
emit(f"FILTERED — xgH_roll>={XG_H_MIN}, xgA_roll>={XG_A_MIN}")
emit(f"{'='*len(header)}")
emit(header)
emit(sep)

by_league_f = defaultdict(list)
for r in filt_roll:
    by_league_f[r['league']].append(r)

for league in sorted(by_league_f):
    grp = by_league_f[league]
    btts_c = sum(1 for r in grp if is_btts(r))
    pct = btts_c / len(grp) * 100
    avg_odds = sum(r['btts_odds'] for r in grp) / len(grp)
    avg_xgh = sum(r['xg_roll_h'] for r in grp) / max(len(grp), 1)
    avg_xga = sum(r['xg_roll_a'] for r in grp) / max(len(grp), 1)
    emit(f"{league:<6} {'ALL':<7} {len(grp):>5} {pct:>5.1f}% {avg_odds:>5.2f} {avg_xgh:>4.2f} {avg_xga:>4.2f} {roi(pct,avg_odds):>+5.1f}%")

    for year in sorted(set(r['season'] for r in grp)):
        sub = [r for r in grp if r['season'] == year]
        sc = sum(1 for r in sub if is_btts(r))
        sp = sc / len(sub) * 100
        so = sum(r['btts_odds'] for r in sub) / len(sub)
        sxg_h = sum(r['xg_roll_h'] for r in sub) / max(len(sub), 1)
        sxg_a = sum(r['xg_roll_a'] for r in sub) / max(len(sub), 1)
        emit(f"{league:<6} {year:<7} {len(sub):>5} {sp:>5.1f}% {so:>5.2f} {sxg_h:>4.2f} {sxg_a:>4.2f} {roi(sp,so):>+5.1f}%")

emit(sep)

fp_pct = sum(1 for r in filt_roll if is_btts(r)) / len(filt_roll) * 100 if filt_roll else 0
fp_odds = sum(r['btts_odds'] for r in filt_roll) / len(filt_roll) if filt_roll else 0
emit(f"\nFiltered: {len(filt_roll)} bets, BTTS={fp_pct:.1f}%, avg_odds={fp_odds:.2f}, ROI={roi(fp_pct,fp_odds):+.1f}%")
emit(f"Lift: {roi(fp_pct,fp_odds)-bp_roi:+.1f}pp  ({len(btts_with_roll)-len(filt_roll)} bets removed)")

# Per-league comparison
emit(f"\nPer-league comparison:")
emit(f"{'League':<6} {'BaseN':>5} {'Base%':>5} {'BaseROI':>7}   {'FiltN':>5} {'Filt%':>5} {'FiltROI':>7} {'Lift':>6}")
for lg in sorted(set(r['league'] for r in btts_with_roll)):
    b = [r for r in btts_with_roll if r['league'] == lg]
    f = [r for r in filt_roll if r['league'] == lg]
    bp_l = sum(1 for r in b if is_btts(r)) / len(b) * 100
    bo_l = sum(r['btts_odds'] for r in b) / len(b)
    fp_l = sum(1 for r in f if is_btts(r)) / len(f) * 100 if f else 0
    fo_l = sum(r['btts_odds'] for r in f) / len(f) if f else 0
    emit(f"{lg:<6} {len(b):>5} {bp_l:>4.1f}% {roi(bp_l,bo_l):>+5.1f}%  |{len(f):>5} {fp_l:>4.1f}% {roi(fp_l,fo_l):>+5.1f}% {roi(fp_l,fo_l)-roi(bp_l,bo_l):>+5.1f}pp")

# Matches removed by the filter — what's their BTTS rate?
removed_by_filter = [r for r in btts_with_roll if r not in filt_roll]
if removed_by_filter:
    rm_pct = sum(1 for r in removed_by_filter if is_btts(r)) / len(removed_by_filter) * 100
    emit(f"\nMatches REJECTED by filter: {len(removed_by_filter)}, BTTS={rm_pct:.1f}%")

# ── TEST 2: Combined rolling xG sum sweep ──
emit(f"\n{'#'*60}")
emit(f"TEST 2: Combined rolling xG sum sweep (xgH_roll + xgA_roll)")
emit(f"{'#'*60}")

sum_header = f"{'Threshold':>10} {'N':>6} {'BTTS%':>6} {'ROI':>7} {'Remain%':>7}"
emit(f"\n{sum_header}")
for thr in [2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6]:
    sub = [r for r in btts_with_roll if (r['xg_roll_h'] or 0) + (r['xg_roll_a'] or 0) >= thr]
    if not sub:
        continue
    sp = sum(1 for r in sub if is_btts(r)) / len(sub) * 100
    so = sum(r['btts_odds'] for r in sub) / len(sub)
    emit(f"{thr:>10.1f} {len(sub):>6} {sp:>5.1f}% {roi(sp,so):>+5.1f}% {len(sub)/len(btts_with_roll)*100:>6.0f}%")

# Distribution
emit(f"\nxG_roll sum distribution:")
emit(f"{'Range':<18} {'N':>6} {'BTTS%':>6} {'ROI':>7}")
for lo, hi in [(0,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,3.5),(3.5,4.0),(4.0,5.0),(5.0,100)]:
    sub = [r for r in btts_with_roll if lo <= (r['xg_roll_h'] or 0) + (r['xg_roll_a'] or 0) < hi]
    if not sub:
        continue
    sp = sum(1 for r in sub if is_btts(r)) / len(sub) * 100
    so = sum(r['btts_odds'] for r in sub) / len(sub)
    hi_s = f"{hi:.0f}+" if hi > 50 else f"{hi:.1f}"
    emit(f"{lo:.1f} - {hi_s:<12} {len(sub):>6} {sp:>5.1f}% {roi(sp,so):>+5.1f}%")

# ── TEST 3: Optimal threshold per league ──
emit(f"\n{'#'*60}")
emit(f"TEST 3: Optimal combined xG sum threshold per league")
emit(f"{'#'*60}")

per_league_header = f"{'League':<6} {'Thr':>6} {'N':>6} {'BTTS%':>6} {'ROI':>7} {'BaseROI':>7} {'Lift':>6}"
emit(per_league_header)
emit("-" * len(per_league_header))
for lg in sorted(set(r['league'] for r in btts_with_roll)):
    sub = [r for r in btts_with_roll if r['league'] == lg]
    best_thr = None
    best_roi = -999
    for thr_val in range(18, 45):
        thr = thr_val / 10.0
        s = [r for r in sub if (r['xg_roll_h'] or 0) + (r['xg_roll_a'] or 0) >= thr]
        if len(s) < 15:
            continue
        sp = sum(1 for r in s if is_btts(r)) / len(s) * 100
        so = sum(r['btts_odds'] for r in s) / len(s)
        r_val = roi(sp, so)
        if r_val > best_roi and sp > 50:
            best_roi = r_val
            best_thr = thr
            best_n = len(s)
            best_pct = sp
    base_lg = [r for r in sub]
    base_lg_pct = sum(1 for r in base_lg if is_btts(r)) / len(base_lg) * 100
    base_odds = sum(r['btts_odds'] for r in base_lg) / len(base_lg)
    base_lg_roi = roi(base_lg_pct, base_odds)
    if best_thr is not None:
        emit(f"{lg:<6} {best_thr:>5.1f} {best_n:>6} {best_pct:>5.1f}% {best_roi:>+5.1f}% {base_lg_roi:>+5.1f}% {best_roi-base_lg_roi:>+5.1f}pp")

# ── Summary ──
emit(f"\n{'#'*60}")
emit(f"SUMMARY")
emit(f"{'#'*60}")
emit(f"Rolling xG (FORM={FORM_N}, MIN={FORM_MIN}):")
emit(f"  Baseline: {len(btts_with_roll)} bets, BTTS={bp_pct:.1f}%, ROI={bp_roi:+.1f}%")
emit(f"  Filtered (xgH>={XG_H_MIN}, xgA>={XG_A_MIN}): {len(filt_roll)} bets, BTTS={fp_pct:.1f}%, ROI={roi(fp_pct,fp_odds):+.1f}%")
emit(f"  Lift: {roi(fp_pct,fp_odds)-bp_roi:+.1f}pp")
emit(f"  Matches without enough history: {len(btts_no_hist)}")

# Save to file
with open("/tmp/xg_rolling_btts.txt", "w") as f:
    f.write("\n".join(output))
    f.write("\n")
print(f"\nResults saved to /tmp/xg_rolling_btts.txt")
